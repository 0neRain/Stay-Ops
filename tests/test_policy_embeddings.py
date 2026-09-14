from dataclasses import replace
from typing import Any, cast
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli.build_policy_embeddings import build_policy_index
from app.models.domain import PolicyEmbedding
from app.models.enums import EscalationUrgency
from app.policy.risk_examples import RISK_EXAMPLES
from app.services.knowledge import KnowledgeHit
from app.services.risk_validation import (
    RiskValidationError,
    SemanticRiskAssessment,
)
from app.services.support_pipeline import SupportPipeline


class FakeBatchEmbeddingProvider:
    model = "test/policy-embedding-model"
    dimensions = 1536

    def __init__(self) -> None:
        self.calls = 0

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [[float(index + 1) / 100] * self.dimensions for index, _ in enumerate(texts)]


class StaticRetriever:
    async def search(self, **_: object) -> list[KnowledgeHit]:
        return [
            KnowledgeHit(
                chunk_id=uuid4(),
                document_id=uuid4(),
                version_id=uuid4(),
                title="House rules",
                content="Parties are not allowed.",
                score=0.90,
                metadata={},
            )
        ]


class StaticRiskValidator:
    def __init__(self, assessment: SemanticRiskAssessment) -> None:
        self.assessment = assessment

    async def assess(self, _: str) -> SemanticRiskAssessment:
        return self.assessment


class FailingRiskValidator:
    async def assess(self, _: str) -> SemanticRiskAssessment:
        raise RiskValidationError("Policy index unavailable")


async def test_policy_index_builder_is_incremental_and_deactivates_removed_examples(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    provider = FakeBatchEmbeddingProvider()
    examples = RISK_EXAMPLES[:2]
    async with db_session_factory() as session:
        first = await build_policy_index(
            session,
            embedding_provider=provider,
            examples=examples,
        )
        await session.commit()
        second = await build_policy_index(
            session,
            embedding_provider=provider,
            examples=examples,
        )
        await session.commit()
        changed = (replace(examples[0], text="A revised refund example."),)
        third = await build_policy_index(
            session,
            embedding_provider=provider,
            examples=changed,
        )
        await session.commit()
        active_count = await session.scalar(
            select(func.count()).select_from(PolicyEmbedding).where(PolicyEmbedding.is_active)
        )

    assert first.inserted == 2
    assert second.unchanged == 2
    assert third.updated == 1
    assert third.deactivated == 1
    assert active_count == 1
    assert provider.calls == 2


async def test_high_semantic_risk_can_only_add_a_handoff() -> None:
    assessment = SemanticRiskAssessment(
        policy_key="access-03",
        category="access",
        urgency=EscalationUrgency.HIGH,
        score=0.91,
        threshold=0.80,
    )
    pipeline = SupportPipeline(
        cast(Any, StaticRetriever()),
        risk_validator=StaticRiskValidator(assessment),
    )
    decision = await pipeline.run(
        tenant_id=uuid4(),
        property_id=uuid4(),
        query="Could you share the keypad PIN?",
    )

    assert decision.action == "handoff"
    assert decision.urgency == EscalationUrgency.HIGH
    assert decision.reason == "Semantic risk match: access"
    assert decision.semantic_risk == assessment


async def test_low_semantic_risk_does_not_override_normal_grounding_checks() -> None:
    assessment = SemanticRiskAssessment(
        policy_key="access-03",
        category="access",
        urgency=EscalationUrgency.HIGH,
        score=0.40,
        threshold=0.80,
    )
    pipeline = SupportPipeline(
        cast(Any, StaticRetriever()),
        risk_validator=StaticRiskValidator(assessment),
    )
    decision = await pipeline.run(
        tenant_id=uuid4(),
        property_id=uuid4(),
        query="Are parties permitted?",
    )

    assert decision.action == "answered"
    assert decision.answer == "Parties are not allowed."
    assert decision.semantic_risk == assessment


async def test_semantic_validation_failure_hands_off() -> None:
    pipeline = SupportPipeline(
        cast(Any, StaticRetriever()),
        risk_validator=FailingRiskValidator(),
    )
    decision = await pipeline.run(
        tenant_id=uuid4(),
        property_id=uuid4(),
        query="Could you help with something sensitive?",
    )

    assert decision.action == "handoff"
    assert decision.reason == "Semantic risk validation failed"
    assert decision.semantic_validation_error == "Policy index unavailable"
