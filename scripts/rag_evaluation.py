import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.cli.build_policy_embeddings import build_policy_index
from app.models.enums import EscalationUrgency
from app.services.embeddings import OpenRouterEmbeddingProvider
from app.services.knowledge import KnowledgeRetriever
from app.services.risk_validation import SemanticRiskValidator
from app.services.support_pipeline import PipelineDecision, SupportPipeline
from scripts.eval_embedding_snapshot import DEFAULT_SNAPSHOT_PATH, ReplayEmbeddingProvider
from scripts.mock_embedding_cache import MockEmbeddingCache
from scripts.mock_knowledge import seed_mock_knowledge
from scripts.seed_mock_knowledge import (
    MockSeedSettings,
    ensure_development_environment,
    ensure_mock_database,
    get_or_create_mock_scope,
)


class RagEvaluationCase(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    query: str = Field(min_length=1)
    expected_action: Literal["answered", "handoff"]
    expected_top_document: str | None = None
    expected_documents_at_k: list[str] = Field(default_factory=list)
    expected_answer_contains: list[str] = Field(default_factory=list)
    forbidden_answer_contains: list[str] = Field(default_factory=list)
    minimum_top_score: float | None = Field(default=None, ge=0, le=1)
    expected_urgency: EscalationUrgency | None = None
    expected_reason_category: str | None = None
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_expectations(self) -> "RagEvaluationCase":
        if self.expected_action == "answered" and not self.expected_answer_contains:
            raise ValueError("Answered cases must specify expected answer content")
        if self.expected_action == "handoff" and self.expected_urgency is None:
            raise ValueError("Handoff cases must specify expected urgency")
        if self.expected_action == "answered" and self.expected_urgency is not None:
            raise ValueError("Answered cases cannot specify expected urgency")
        if self.expected_action == "answered" and self.expected_reason_category is not None:
            raise ValueError("Answered cases cannot specify an expected reason category")
        if len(self.expected_documents_at_k) != len(set(self.expected_documents_at_k)):
            raise ValueError("Expected documents at k must be unique")
        return self


class RagEvaluationThresholds(BaseModel):
    minimum_case_pass_rate: float = Field(default=1.0, ge=0, le=1)
    minimum_action_accuracy: float = Field(default=1.0, ge=0, le=1)
    minimum_automatic_answer_precision: float = Field(default=1.0, ge=0, le=1)
    minimum_unsupported_handoff_rate: float = Field(default=1.0, ge=0, le=1)
    minimum_safety_access_recall: float = Field(default=1.0, ge=0, le=1)
    minimum_retrieval_recall_at_1: float = Field(default=1.0, ge=0, le=1)
    minimum_retrieval_recall_at_k: float = Field(default=1.0, ge=0, le=1)
    minimum_retrieval_mrr: float = Field(default=1.0, ge=0, le=1)
    maximum_false_handoff_rate: float = Field(default=0.0, ge=0, le=1)
    maximum_provider_error_rate: float = Field(default=0.0, ge=0, le=1)


class RagEvaluationSuite(BaseModel):
    name: str
    version: str
    description: str
    cases: list[RagEvaluationCase] = Field(min_length=1)
    thresholds: RagEvaluationThresholds = Field(default_factory=RagEvaluationThresholds)

    @model_validator(mode="after")
    def unique_case_ids(self) -> "RagEvaluationSuite":
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Evaluation case IDs must be unique")
        return self


class EvaluationPipeline(Protocol):
    async def run(self, *, tenant_id: UUID, property_id: UUID, query: str) -> PipelineDecision: ...


class EvaluationEmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_query(self, text: str) -> list[float]: ...

    async def embed_document(self, text: str) -> list[float]: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class RagEvaluationResult:
    case_id: str
    passed: bool
    failures: tuple[str, ...]
    actual_action: str
    actual_urgency: str | None
    top_document: str | None
    top_score: float | None
    decision_reason: str | None
    reason_category: str | None
    retrieved_documents: tuple[str, ...]
    retrieved_hits: tuple[str, ...]
    provider_error: bool


@dataclass(frozen=True)
class RagEvaluationMetrics:
    total_cases: int
    passed_cases: int
    case_pass_rate: float
    action_accuracy: float
    automatic_answer_precision: float
    unsupported_handoff_rate: float
    safety_access_recall: float
    retrieval_recall_at_1: float
    retrieval_recall_at_k: float
    retrieval_mrr: float
    false_handoff_rate: float
    provider_error_rate: float


@dataclass(frozen=True)
class RagEvaluationGate:
    passed: bool
    failures: tuple[str, ...]


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
        thresholds=suite.thresholds,
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
    reason_category = None
    if decision.static_risk is not None:
        reason_category = decision.static_risk.category
    elif decision.semantic_risk is not None and decision.semantic_risk.requires_handoff:
        reason_category = decision.semantic_risk.category

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
    retrieved_documents = tuple(hit.title for hit in decision.hits)
    for expected_document in case.expected_documents_at_k:
        if expected_document not in retrieved_documents:
            failures.append(
                f"document at k: expected {expected_document!r} in {retrieved_documents!r}"
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

    if (
        case.expected_reason_category is not None
        and case.expected_reason_category != reason_category
    ):
        failures.append(
            f"reason category: expected {case.expected_reason_category!r}, got {reason_category!r}"
        )

    if decision.action == "answered":
        if not answer.strip():
            failures.append("invariant: answered decision must include a non-empty answer")
        if not decision.hits:
            failures.append(
                "invariant: answered decision must include at least one citation source"
            )
        if decision.reason is not None:
            failures.append("invariant: answered decision cannot include a handoff reason")
        if decision.urgency is not None:
            failures.append("invariant: answered decision cannot include handoff urgency")
    else:
        if answer.strip():
            failures.append("invariant: handoff decision cannot include an automatic answer")
        if not decision.reason:
            failures.append("invariant: handoff decision must include a reason")
        if decision.urgency is None:
            failures.append("invariant: handoff decision must include urgency")

    return RagEvaluationResult(
        case_id=case.id,
        passed=not failures,
        failures=tuple(failures),
        actual_action=decision.action,
        actual_urgency=decision.urgency.value if decision.urgency else None,
        top_document=top_hit.title if top_hit else None,
        top_score=top_hit.score if top_hit else None,
        decision_reason=decision.reason,
        reason_category=reason_category,
        retrieved_documents=retrieved_documents,
        retrieved_hits=tuple(
            f"{hit.title}={hit.score:.3f}"
            + (" [human-review]" if hit.metadata.get("requires_human_review") is True else "")
            for hit in decision.hits
        ),
        provider_error=bool(decision.retrieval_error or decision.semantic_validation_error),
    )


def _rate(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def calculate_metrics(
    suite: RagEvaluationSuite,
    results: list[RagEvaluationResult],
) -> RagEvaluationMetrics:
    result_by_id = {result.case_id: result for result in results}
    if len(result_by_id) != len(results):
        raise ValueError("Evaluation results must have unique case IDs")
    missing_case_ids = {case.id for case in suite.cases} - result_by_id.keys()
    unexpected_case_ids = result_by_id.keys() - {case.id for case in suite.cases}
    if missing_case_ids or unexpected_case_ids:
        raise ValueError(
            "Evaluation results do not match the suite: "
            f"missing={sorted(missing_case_ids)}, unexpected={sorted(unexpected_case_ids)}"
        )

    action_correct = 0
    predicted_answered = 0
    correct_automatic_answers = 0
    expected_answered = 0
    false_handoffs = 0
    unsupported_total = 0
    unsupported_handoffs = 0
    safety_access_total = 0
    safety_access_handoffs = 0
    retrieval_total = 0
    retrieval_at_1 = 0
    retrieval_at_k = 0
    reciprocal_rank_total = 0.0

    for case in suite.cases:
        result = result_by_id[case.id]
        if result.actual_action == case.expected_action:
            action_correct += 1
        if result.actual_action == "answered":
            predicted_answered += 1
            if case.expected_action == "answered" and result.passed:
                correct_automatic_answers += 1
        if case.expected_action == "answered":
            expected_answered += 1
            if result.actual_action == "handoff":
                false_handoffs += 1

        if {"unsupported", "missing-knowledge"} & set(case.tags):
            unsupported_total += 1
            if result.actual_action == "handoff":
                unsupported_handoffs += 1

        if case.expected_action == "handoff" and {"safety", "access"} & set(case.tags):
            safety_access_total += 1
            if result.actual_action == "handoff":
                safety_access_handoffs += 1

        relevant_documents = set(case.expected_documents_at_k)
        if case.expected_top_document:
            relevant_documents.add(case.expected_top_document)
        if relevant_documents:
            retrieval_total += 1
            ranks = [
                rank
                for rank, document in enumerate(result.retrieved_documents, start=1)
                if document in relevant_documents
            ]
            if ranks:
                retrieval_at_k += 1
                reciprocal_rank_total += 1 / min(ranks)
                if min(ranks) == 1:
                    retrieval_at_1 += 1

    total_cases = len(results)
    return RagEvaluationMetrics(
        total_cases=total_cases,
        passed_cases=sum(result.passed for result in results),
        case_pass_rate=_rate(sum(result.passed for result in results), total_cases),
        action_accuracy=_rate(action_correct, total_cases),
        automatic_answer_precision=_rate(correct_automatic_answers, predicted_answered),
        unsupported_handoff_rate=_rate(unsupported_handoffs, unsupported_total),
        safety_access_recall=_rate(safety_access_handoffs, safety_access_total),
        retrieval_recall_at_1=_rate(retrieval_at_1, retrieval_total),
        retrieval_recall_at_k=_rate(retrieval_at_k, retrieval_total),
        retrieval_mrr=_rate(reciprocal_rank_total, retrieval_total),
        false_handoff_rate=_rate(false_handoffs, expected_answered),
        provider_error_rate=_rate(sum(result.provider_error for result in results), total_cases),
    )


def evaluate_thresholds(
    metrics: RagEvaluationMetrics,
    thresholds: RagEvaluationThresholds,
) -> RagEvaluationGate:
    failures: list[str] = []
    minimums = (
        ("case pass rate", metrics.case_pass_rate, thresholds.minimum_case_pass_rate),
        ("action accuracy", metrics.action_accuracy, thresholds.minimum_action_accuracy),
        (
            "automatic-answer precision",
            metrics.automatic_answer_precision,
            thresholds.minimum_automatic_answer_precision,
        ),
        (
            "unsupported handoff rate",
            metrics.unsupported_handoff_rate,
            thresholds.minimum_unsupported_handoff_rate,
        ),
        (
            "safety/access recall",
            metrics.safety_access_recall,
            thresholds.minimum_safety_access_recall,
        ),
        (
            "retrieval recall@1",
            metrics.retrieval_recall_at_1,
            thresholds.minimum_retrieval_recall_at_1,
        ),
        (
            "retrieval recall@k",
            metrics.retrieval_recall_at_k,
            thresholds.minimum_retrieval_recall_at_k,
        ),
        ("retrieval MRR", metrics.retrieval_mrr, thresholds.minimum_retrieval_mrr),
    )
    maximums = (
        (
            "false-handoff rate",
            metrics.false_handoff_rate,
            thresholds.maximum_false_handoff_rate,
        ),
        (
            "provider-error rate",
            metrics.provider_error_rate,
            thresholds.maximum_provider_error_rate,
        ),
    )
    for name, actual, minimum in minimums:
        if actual < minimum:
            failures.append(f"{name}: expected >= {minimum:.1%}, got {actual:.1%}")
    for name, actual, maximum in maximums:
        if actual > maximum:
            failures.append(f"{name}: expected <= {maximum:.1%}, got {actual:.1%}")
    return RagEvaluationGate(passed=not failures, failures=tuple(failures))


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
    embedding_provider: EvaluationEmbeddingProvider,
) -> list[RagEvaluationResult]:
    ensure_development_environment(settings)
    ensure_mock_database(settings.mock_database_url)
    engine = create_async_engine(settings.mock_database_url, pool_pre_ping=True)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        with MockEmbeddingCache(Path(":memory:")) as embedding_cache:
            async with session_factory() as session:
                tenant, property_record = await get_or_create_mock_scope(
                    session,
                    tenant_slug=tenant_slug,
                    property_external_id=property_external_id,
                )
                await seed_mock_knowledge(
                    session,
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    embedding_provider=embedding_provider,
                    embedding_cache=embedding_cache,
                )
                await build_policy_index(session, embedding_provider=embedding_provider)
                risk_validator = SemanticRiskValidator(
                    session,
                    embedding_provider=embedding_provider,
                    threshold=settings.semantic_risk_threshold,
                )
                pipeline = SupportPipeline(
                    KnowledgeRetriever(session, embedding_provider=embedding_provider),
                    risk_validator=risk_validator,
                )
                return await evaluate_suite(
                    pipeline,
                    tenant_id=tenant.id,
                    property_id=property_record.id,
                    suite=suite,
                )
    finally:
        await engine.dispose()


def _print_results(
    results: list[RagEvaluationResult],
    metrics: RagEvaluationMetrics,
    gate: RagEvaluationGate,
) -> None:
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        details = "; ".join(result.failures)
        print(f"[{marker}] {result.case_id}" + (f": {details}" if details else ""))
        if not result.passed:
            print(f"       reason: {result.decision_reason or '-'}")
            print(f"       hits: {', '.join(result.retrieved_hits) or '-'}")
    print(f"\nRAG evaluation: {metrics.passed_cases}/{metrics.total_cases} passed")
    print(
        "Metrics: "
        f"action_accuracy={metrics.action_accuracy:.1%}, "
        f"automatic_answer_precision={metrics.automatic_answer_precision:.1%}, "
        f"unsupported_handoff_rate={metrics.unsupported_handoff_rate:.1%}, "
        f"safety_access_recall={metrics.safety_access_recall:.1%}, "
        f"retrieval_recall@1={metrics.retrieval_recall_at_1:.1%}, "
        f"retrieval_recall@k={metrics.retrieval_recall_at_k:.1%}, "
        f"retrieval_mrr={metrics.retrieval_mrr:.3f}, "
        f"false_handoff_rate={metrics.false_handoff_rate:.1%}, "
        f"provider_error_rate={metrics.provider_error_rate:.1%}"
    )
    for failure in gate.failures:
        print(f"[GATE FAIL] {failure}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the development RAG evaluation suite")
    parser.add_argument("--dataset", type=Path, default=Path("evals/rag_v1.json"))
    parser.add_argument("--tenant", default="demo-stays")
    parser.add_argument("--property-external-id", default="demo-casa-aurora")
    parser.add_argument(
        "--embedding-mode",
        choices=("snapshot", "live"),
        default="snapshot",
        help="Replay committed embeddings (default) or call OpenRouter live",
    )
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT_PATH)
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
    if args.embedding_mode == "snapshot":
        replay_provider = ReplayEmbeddingProvider.from_manifest(args.snapshot)
        if replay_provider.dataset_version != suite.version:
            raise RuntimeError(
                f"Embedding snapshot targets dataset {replay_provider.dataset_version!r}, "
                f"not {suite.version!r}; refresh the snapshot"
            )
        if replay_provider.source_model != settings.openrouter_embedding_model:
            raise RuntimeError(
                f"Embedding snapshot uses model {replay_provider.source_model!r}, "
                "not configured model "
                f"{settings.openrouter_embedding_model!r}; refresh the snapshot or update "
                "configuration"
            )
        embedding_provider: EvaluationEmbeddingProvider = replay_provider
    else:
        if not settings.embedding_api_key:
            raise RuntimeError("OpenRouter embedding credentials are required for live evaluation")
        embedding_provider = OpenRouterEmbeddingProvider(
            api_key=settings.embedding_api_key,
            model=settings.openrouter_embedding_model,
        )
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    results = asyncio.run(
        run_evaluation(
            settings=settings,
            suite=suite,
            tenant_slug=args.tenant,
            property_external_id=args.property_external_id,
            embedding_provider=embedding_provider,
        )
    )
    metrics = calculate_metrics(suite, results)
    gate = evaluate_thresholds(metrics, suite.thresholds)
    _print_results(results, metrics, gate)
    if not gate.passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
