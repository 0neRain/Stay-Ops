import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.auth import Tenant
from app.models.domain import Property
from app.models.enums import EscalationUrgency
from app.services.embeddings import OpenRouterEmbeddingProvider
from app.services.knowledge import KnowledgeRetriever
from app.services.support_pipeline import PipelineDecision, SupportPipeline
from scripts.seed_mock_knowledge import (
    MockSeedSettings,
    ensure_development_environment,
    ensure_mock_database,
)


class RagEvaluationCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    query: str = Field(min_length=1)
    expected_action: Literal["answered", "handoff"]
    expected_top_document: str | None = None
    expected_answer_contains: list[str] = Field(default_factory=list)
    forbidden_answer_contains: list[str] = Field(default_factory=list)
    minimum_top_score: float | None = Field(default=None, ge=0, le=1)
    expected_urgency: EscalationUrgency | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expectations(self) -> "RagEvaluationCase":
        if self.expected_action == "answered" and not self.expected_answer_contains:
            raise ValueError("Answered cases must specify expected answer content")
        if self.expected_action == "handoff" and self.expected_urgency is None:
            raise ValueError("Handoff cases must specify expected urgency")
        return self


class RagEvaluationSuite(BaseModel):
    name: str
    version: str
    description: str
    cases: list[RagEvaluationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "RagEvaluationSuite":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")
        return self


class EvaluationPipeline(Protocol):
    async def run(self, *, tenant_id: UUID, property_id: UUID, query: str) -> PipelineDecision: ...


@dataclass(frozen=True)
class RagEvaluationResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...]
    actual_action: str
    actual_urgency: str | None
    top_document: str | None
    top_score: float | None


def load_suite(path: Path) -> RagEvaluationSuite:
    return RagEvaluationSuite.model_validate_json(path.read_text(encoding="utf-8"))


def select_cases(
    suite: RagEvaluationSuite,
    *,
    include_known_gaps: bool,
) -> RagEvaluationSuite:
    if include_known_gaps:
        return suite
    return RagEvaluationSuite(
        name=suite.name,
        version=suite.version,
        description=suite.description,
        cases=[case for case in suite.cases if "known-gap" not in case.tags],
    )


async def evaluate_case(
    pipeline: EvaluationPipeline,
    *,
    tenant_id: UUID,
    property_id: UUID,
    case: RagEvaluationCase,
) -> RagEvaluationResult:
    decision = await pipeline.run(
        tenant_id=tenant_id,
        property_id=property_id,
        query=case.query,
    )
    failures: list[str] = []
    top_hit = decision.hits[0] if decision.hits else None
    if decision.action != case.expected_action:
        failures.append(f"action: expected {case.expected_action}, got {decision.action}")
    if decision.urgency != case.expected_urgency:
        actual = decision.urgency.value if decision.urgency else None
        expected = case.expected_urgency.value if case.expected_urgency else None
        failures.append(f"urgency: expected {expected}, got {actual}")
    if case.expected_top_document and (
        top_hit is None or top_hit.title != case.expected_top_document
    ):
        failures.append(
            "top document: expected "
            f"{case.expected_top_document!r}, got {top_hit.title if top_hit else None!r}"
        )
    if case.minimum_top_score is not None and (
        top_hit is None or top_hit.score < case.minimum_top_score
    ):
        failures.append(
            f"top score: expected >= {case.minimum_top_score}, "
            f"got {top_hit.score if top_hit else None}"
        )

    answer = (decision.answer or "").casefold()
    for expected_text in case.expected_answer_contains:
        if expected_text.casefold() not in answer:
            failures.append(f"answer missing {expected_text!r}")
    for forbidden_text in case.forbidden_answer_contains:
        if forbidden_text.casefold() in answer:
            failures.append(f"answer contains forbidden text {forbidden_text!r}")

    return RagEvaluationResult(
        case_id=case.id,
        passed=not failures,
        failures=tuple(failures),
        actual_action=decision.action,
        actual_urgency=decision.urgency.value if decision.urgency else None,
        top_document=top_hit.title if top_hit else None,
        top_score=top_hit.score if top_hit else None,
    )


async def evaluate_suite(
    pipeline: EvaluationPipeline,
    *,
    tenant_id: UUID,
    property_id: UUID,
    suite: RagEvaluationSuite,
) -> list[RagEvaluationResult]:
    results: list[RagEvaluationResult] = []
    for case in suite.cases:
        results.append(
            await evaluate_case(
                pipeline,
                tenant_id=tenant_id,
                property_id=property_id,
                case=case,
            )
        )
    return results


async def run_evaluation(
    *,
    settings: MockSeedSettings,
    suite: RagEvaluationSuite,
    tenant_slug: str,
    property_external_id: str,
) -> list[RagEvaluationResult]:
    ensure_development_environment(settings)
    ensure_mock_database(settings.mock_database_url)
    engine = create_async_engine(settings.mock_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    provider = OpenRouterEmbeddingProvider(
        api_key=settings.embedding_api_key,
        model=settings.openrouter_embedding_model,
    )
    try:
        async with session_factory() as session:
            tenant = await session.scalar(select(Tenant).where(Tenant.slug == tenant_slug))
            if tenant is None:
                raise RuntimeError(f"Mock tenant {tenant_slug!r} was not found; run the seed first")
            property_record = await session.scalar(
                select(Property).where(
                    Property.tenant_id == tenant.id,
                    Property.external_id == property_external_id,
                )
            )
            if property_record is None:
                raise RuntimeError(
                    f"Mock property {property_external_id!r} was not found; run the seed first"
                )
            pipeline = SupportPipeline(KnowledgeRetriever(session, embedding_provider=provider))
            return await evaluate_suite(
                pipeline,
                tenant_id=tenant.id,
                property_id=property_record.id,
                suite=suite,
            )
    finally:
        await engine.dispose()


def _print_results(results: list[RagEvaluationResult]) -> None:
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        details = "; ".join(result.failures)
        print(f"[{marker}] {result.case_id}" + (f": {details}" if details else ""))
    passed = sum(result.passed for result in results)
    print(f"\nRAG evaluation: {passed}/{len(results)} passed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the development RAG evaluation suite")
    parser.add_argument("--dataset", type=Path, default=Path("evals/rag_v1.json"))
    parser.add_argument("--tenant", default="demo-stays")
    parser.add_argument("--property-external-id", default="demo-casa-aurora")
    parser.add_argument(
        "--include-known-gaps",
        action="store_true",
        help="Include aspirational cases currently expected to expose a product gap",
    )
    args = parser.parse_args()
    settings = MockSeedSettings()
    suite = select_cases(
        load_suite(args.dataset),
        include_known_gaps=args.include_known_gaps,
    )
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    results = asyncio.run(
        run_evaluation(
            settings=settings,
            suite=suite,
            tenant_slug=args.tenant,
            property_external_id=args.property_external_id,
        )
    )
    _print_results(results)
    if not all(result.passed for result in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
