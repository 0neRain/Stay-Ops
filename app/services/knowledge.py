import re
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
from app.models.enums import KnowledgeStatus
from app.services.embeddings import EmbeddingProvider, EmbeddingProviderError
from app.services.profile_knowledge import PROFILE_SOURCE_KIND

_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "can",
    "do",
    "for",
    "from",
    "how",
    "i",
    "ignore",
    "in",
    "instruction",
    "instructions",
    "is",
    "it",
    "may",
    "me",
    "my",
    "of",
    "on",
    "please",
    "say",
    "that",
    "the",
    "to",
    "we",
    "what",
    "when",
    "where",
    "with",
    "you",
}
_ALIASES = {
    "allowed": "permitted",
    "arrive": "checkin",
    "arrival": "checkin",
    "depart": "checkout",
    "departure": "checkout",
    "cat": "pet",
    "cats": "pet",
    "dog": "pet",
    "dogs": "pet",
    "internet": "wifi",
    "pets": "pet",
    "wireless": "wifi",
}


@dataclass(frozen=True)
class KnowledgeHit:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    title: str
    content: str
    score: float
    metadata: dict[str, object]


class KnowledgeRetrievalError(Exception):
    pass


def _tokens(value: str) -> set[str]:
    normalized = value.casefold().replace("wi-fi", "wifi").replace("check-in", "checkin")
    normalized = normalized.replace("check-out", "checkout")
    result: set[str] = set()
    for token in re.findall(r"[a-z0-9]+", normalized):
        token = _ALIASES.get(token, token)
        if token not in _STOP_WORDS and len(token) > 1:
            result.add(token)
    return result


def lexical_score(query: str, *, title: str, content: str) -> float:
    """Return a deterministic 0..1 retrieval score for the local MVP.

    Keeping this scorer behind ``KnowledgeRetriever`` makes it straightforward to
    replace with OpenRouter embeddings/pgvector without changing the pipeline.
    """
    query_tokens = _tokens(query)
    if not query_tokens:
        return 0.0
    content_tokens = _tokens(content)
    title_tokens = _tokens(title)
    coverage = len(query_tokens & (content_tokens | title_tokens)) / len(query_tokens)
    title_coverage = len(query_tokens & title_tokens) / len(query_tokens)
    return round(min(1.0, (coverage * 0.85) + (title_coverage * 0.15)), 6)


class KnowledgeRetriever:
    def __init__(
        self,
        session: AsyncSession,
        *,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self.session = session
        self.embedding_provider = embedding_provider

    async def search(
        self,
        *,
        tenant_id: UUID,
        property_id: UUID,
        query: str,
        limit: int = 4,
        minimum_score: float = 0.01,
    ) -> list[KnowledgeHit]:
        latest_versions = (
            select(
                KnowledgeVersion.document_id.label("document_id"),
                func.max(KnowledgeVersion.version).label("version"),
            )
            .where(
                KnowledgeVersion.approved_at.is_not(None),
            )
            .group_by(KnowledgeVersion.document_id)
            .subquery()
        )
        distance: Any = None
        if (
            self.embedding_provider is not None
            and self.session.get_bind().dialect.name == "postgresql"
        ):
            try:
                query_embedding = await self.embedding_provider.embed_query(query)
            except EmbeddingProviderError as exc:
                raise KnowledgeRetrievalError(str(exc)) from exc
            embedding_column = cast(Any, KnowledgeChunk.embedding)
            distance = embedding_column.cosine_distance(query_embedding)

        statement = (
            select(KnowledgeChunk, KnowledgeVersion, KnowledgeDocument, distance)
            .join(KnowledgeVersion, KnowledgeVersion.id == KnowledgeChunk.version_id)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeVersion.document_id)
            .join(
                latest_versions,
                and_(
                    latest_versions.c.document_id == KnowledgeVersion.document_id,
                    latest_versions.c.version == KnowledgeVersion.version,
                ),
            )
            .where(
                KnowledgeChunk.tenant_id == tenant_id,
                or_(
                    and_(
                        KnowledgeChunk.property_id == property_id,
                        KnowledgeDocument.property_id == property_id,
                    ),
                    and_(
                        KnowledgeChunk.property_id.is_(None),
                        KnowledgeDocument.property_id.is_(None),
                    ),
                ),
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.status == KnowledgeStatus.PUBLISHED,
                KnowledgeDocument.document_type != "support_policy",
            )
        )
        if distance is not None:
            statement = statement.order_by(distance)
        rows = (await self.session.execute(statement)).all()
        hits = [
            KnowledgeHit(
                chunk_id=chunk.id,
                document_id=document.id,
                version_id=version.id,
                title=document.title,
                content=chunk.content,
                score=round(
                    max(
                        lexical_score(query, title=document.title, content=chunk.content),
                        max(0.0, 1.0 - float(vector_distance))
                        if vector_distance is not None
                        else 0.0,
                    ),
                    6,
                ),
                metadata=dict(chunk.metadata_json),
            )
            for chunk, version, document, vector_distance in rows
        ]
        eligible = [hit for hit in hits if hit.score >= minimum_score]
        return sorted(
            eligible,
            key=lambda hit: (
                -hit.score,
                hit.metadata.get("source_kind") != PROFILE_SOURCE_KIND,
                hit.title,
                str(hit.chunk_id),
            ),
        )[:limit]
