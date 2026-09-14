import hashlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain import KnowledgeChunk, KnowledgeDocument, KnowledgeVersion
from app.models.enums import KnowledgeStatus
from scripts.mock_embedding_cache import MockEmbeddingCache


class DocumentEmbeddingProvider(Protocol):
    @property
    def model(self) -> str: ...

    @property
    def dimensions(self) -> int: ...

    async def embed_document(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class MockDocument:
    title: str
    document_type: str
    chunks: tuple[str, ...]
    global_scope: bool = False
    requires_human_review: bool = False


MOCK_KNOWLEDGE: tuple[MockDocument, ...] = (
    MockDocument(
        title="Arrival and departure guide",
        document_type="operating_instructions",
        chunks=(
            (
                "Check-in begins at 3:00 PM. Early check-in is available only with prior "
                "approval from the property team. Smart-lock instructions are sent to the "
                "verified guest 24 hours before arrival; the door code is never stored in "
                "the knowledge base."
            ),
            (
                "Check-out is by 10:00 AM. Before leaving, place used towels in the bathroom, "
                "load and start the dishwasher, switch off lights and air conditioning, and "
                "close the door firmly behind you."
            ),
        ),
    ),
    MockDocument(
        title="Wi-Fi and home office",
        document_type="amenities",
        chunks=(
            (
                "The Wi-Fi network is CasaAurora_Guest and the password is welcome-aurora. "
                "The router is on the living-room bookshelf. If the connection drops, unplug "
                "the router for 20 seconds and allow up to three minutes for it to reconnect."
            ),
        ),
    ),
    MockDocument(
        title="House rules",
        document_type="house_rules",
        chunks=(
            (
                "Quiet hours are from 10:00 PM to 8:00 AM. Smoking, parties, and unregistered "
                "overnight guests are not allowed. Pets are permitted only when they were "
                "approved before check-in."
            ),
            (
                "Household waste goes in the bins inside the courtyard. Blue is paper, yellow "
                "is plastic and metal, brown is organic waste, and grey is general waste."
            ),
        ),
    ),
)


@dataclass(frozen=True)
class MockSeedStats:
    inserted_chunks: int = 0
    embedded_chunks: int = 0
    cache_hits: int = 0
    unchanged_documents: int = 0


async def seed_mock_knowledge(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    property_id: UUID,
    embedding_provider: DocumentEmbeddingProvider,
    embedding_cache: MockEmbeddingCache,
    provider_name: str = "openrouter",
    approved_by_id: UUID | None = None,
    documents: Sequence[MockDocument] = MOCK_KNOWLEDGE,
) -> MockSeedStats:
    """Version mock documents and embed only content absent from the local cache."""
    inserted_chunks = 0
    embedded_chunks = 0
    cache_hits = 0
    unchanged_documents = 0
    now = datetime.now(timezone.utc)
    for mock_document in documents:
        scoped_property_id = None if mock_document.global_scope else property_id
        document = await session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.tenant_id == tenant_id,
                KnowledgeDocument.property_id == scoped_property_id,
                KnowledgeDocument.title == mock_document.title,
            )
        )
        content = "\n\n".join(mock_document.chunks)
        content_sha256 = hashlib.sha256(content.encode()).hexdigest()
        embedding_metadata = {
            "provider": provider_name,
            "model": embedding_provider.model,
            "dimensions": embedding_provider.dimensions,
        }

        latest_version: KnowledgeVersion | None = None
        if document is None:
            document = KnowledgeDocument(
                tenant_id=tenant_id,
                property_id=scoped_property_id,
                title=mock_document.title,
                document_type=mock_document.document_type,
                status=KnowledgeStatus.PUBLISHED,
            )
            session.add(document)
            await session.flush()
        else:
            latest_version = await session.scalar(
                select(KnowledgeVersion)
                .where(KnowledgeVersion.document_id == document.id)
                .order_by(KnowledgeVersion.version.desc())
                .limit(1)
            )
            if (
                latest_version is not None
                and latest_version.content_sha256 == content_sha256
                and latest_version.embedding_status == "ready"
                and latest_version.metadata_json.get("embedding") == embedding_metadata
            ):
                unchanged_documents += 1
                continue

        next_version = latest_version.version + 1 if latest_version else 1
        version = KnowledgeVersion(
            document_id=document.id,
            version=next_version,
            content=content,
            content_sha256=content_sha256,
            source=f"mock://stayops/demo-kb/v{next_version}",
            approved_by_id=approved_by_id,
            approved_at=None,
            embedding_status="pending",
            metadata_json={"mock": True, "embedding": embedding_metadata},
        )
        session.add(version)
        await session.flush()

        for index, chunk_content in enumerate(mock_document.chunks):
            chunk_sha256 = hashlib.sha256(chunk_content.encode()).hexdigest()
            embedding = embedding_cache.get(
                content_sha256=chunk_sha256,
                provider=provider_name,
                model=embedding_provider.model,
                dimensions=embedding_provider.dimensions,
            )
            if embedding is None:
                embedding = await embedding_provider.embed_document(chunk_content)
                if len(embedding) != embedding_provider.dimensions:
                    raise ValueError("Embedding provider returned an unexpected dimension")
                embedding_cache.put(
                    content_sha256=chunk_sha256,
                    provider=provider_name,
                    model=embedding_provider.model,
                    dimensions=embedding_provider.dimensions,
                    embedding=embedding,
                )
                embedded_chunks += 1
            else:
                cache_hits += 1
            session.add(
                KnowledgeChunk(
                    version_id=version.id,
                    tenant_id=tenant_id,
                    property_id=scoped_property_id,
                    chunk_index=index,
                    content=chunk_content,
                    token_count=len(chunk_content.split()),
                    embedding=embedding,
                    metadata_json={
                        "mock": True,
                        "content_sha256": chunk_sha256,
                        "embedding": embedding_metadata,
                        "requires_human_review": mock_document.requires_human_review,
                    },
                )
            )
            inserted_chunks += 1
        version.embedding_status = "ready"
        version.approved_at = now
        document.status = KnowledgeStatus.PUBLISHED
    await session.flush()
    return MockSeedStats(
        inserted_chunks=inserted_chunks,
        embedded_chunks=embedded_chunks,
        cache_hits=cache_hits,
        unchanged_documents=unchanged_documents,
    )
