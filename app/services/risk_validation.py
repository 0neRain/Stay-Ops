from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import PolicyEmbedding
from app.models.enums import EscalationUrgency
from app.services.embeddings import EmbeddingProvider, EmbeddingProviderError


class RiskValidationError(Exception):
    pass


@dataclass(frozen=True)
class SemanticRiskAssessment:
    policy_key: str
    category: str
    urgency: EscalationUrgency
    score: float
    threshold: float

    @property
    def requires_handoff(self) -> bool:
        return self.score >= self.threshold


class SemanticRiskValidator:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider,
        threshold: float = 0.80,
    ) -> None:
        if not 0 <= threshold <= 1:
            raise ValueError("Semantic risk threshold must be between 0 and 1")
        self.session = session
        self.embedding_provider = embedding_provider
        self.threshold = threshold

    async def assess(self, query: str) -> SemanticRiskAssessment:
        if self.session.get_bind().dialect.name != "postgresql":
            raise RiskValidationError("Semantic risk validation requires PostgreSQL")
        try:
            query_embedding = await self.embedding_provider.embed_query(query)
        except EmbeddingProviderError as exc:
            raise RiskValidationError(str(exc)) from exc
        if len(query_embedding) != self.embedding_provider.dimensions:
            raise RiskValidationError("Query embedding has an unexpected dimension")

        embedding_column = cast(Any, PolicyEmbedding.embedding)
        distance = embedding_column.cosine_distance(query_embedding)
        try:
            row = (
                await self.session.execute(
                    select(PolicyEmbedding, distance.label("distance"))
                    .where(
                        PolicyEmbedding.is_active.is_(True),
                        PolicyEmbedding.model_name == self.embedding_provider.model,
                        PolicyEmbedding.dimensions == self.embedding_provider.dimensions,
                    )
                    .order_by(distance)
                    .limit(1)
                )
            ).one_or_none()
        except SQLAlchemyError as exc:
            raise RiskValidationError("Policy embedding lookup failed") from exc
        if row is None:
            raise RiskValidationError(
                "Policy embedding index is missing for the configured embedding model"
            )
        policy, vector_distance = row
        score = round(max(0.0, min(1.0, 1.0 - float(vector_distance))), 6)
        return SemanticRiskAssessment(
            policy_key=policy.policy_key,
            category=policy.category,
            urgency=policy.urgency,
            score=score,
            threshold=self.threshold,
        )
