import asyncio
from pathlib import Path
from uuid import UUID

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.routes.knowledge import get_document_job_queue
from app.core.config import Settings, get_settings
from app.main import app
from app.models.domain import Property
from app.models.enums import PropertyOnboardingStatus
from app.services.document_ingestion import InProcessDocumentQueue
from app.services.property_onboarding import can_attach_documents

REGISTRATION = {
    "email": "onboarding-owner@example.com",
    "password": "correct horse battery staple",
    "full_name": "Onboarding Owner",
    "organization_name": "Onboarding Stays",
}


async def _register(api_client: httpx.AsyncClient) -> tuple[str, UUID]:
    response = await api_client.post("/api/v1/auth/register", json=REGISTRATION)
    assert response.status_code == 201
    body = response.json()
    return body["access_token"], UUID(body["active_tenant_id"])


class BlockingExtractionModel:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    def with_structured_output(self, schema: object) -> "BlockingExtractionModel":
        del schema
        return self

    async def ainvoke(self, messages: object) -> object:
        del messages
        self.started.set()
        await self.release.wait()
        raise RuntimeError("Use the local extraction fallback")


async def test_documents_prefill_review_and_activate_home(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_env="test",
        document_storage_root=tmp_path / "uploads",
        openrouter_api_key=None,
        openrouter_chat_api_key=None,
        openrouter_embedding_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_job_queue] = lambda: InProcessDocumentQueue(
        db_session_factory,
        settings=settings,
        embedding_provider=None,
    )
    token, tenant_id = await _register(api_client)
    headers = {"Authorization": f"Bearer {token}"}

    draft_response = await api_client.post("/api/v1/properties/onboarding", headers=headers)
    assert draft_response.status_code == 201
    draft = draft_response.json()
    assert draft["status"] == "documents"
    assert draft["is_active"] is False

    manual = """Property name: Casa Verde
Timezone: Europe/Rome
Address: Via Verde 12, Florence, Italy
Check-in: 15:00
Check-out: 10:00
Wi-Fi network: CasaVerde_Guest
Wi-Fi password: must-not-be-extracted
Access instructions: Enter through the courtyard gate.
House rules: No smoking; quiet hours after 22:00.
Amenities: Air conditioning; washer; travel cot.
"""
    upload = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={
            "title": "Casa Verde manual",
            "document_type": "house_manual",
            "property_id": draft["id"],
        },
        files={"file": ("casa-verde.md", manual.encode(), "text/markdown")},
    )
    assert upload.status_code == 202

    extraction_model = BlockingExtractionModel()
    monkeypatch.setattr(
        "app.api.routes.properties.configured_answering_model",
        lambda settings, max_tokens: extraction_model,
    )
    extraction_task = asyncio.create_task(
        api_client.post(
            f"/api/v1/properties/{draft['id']}/onboarding/extract",
            headers=headers,
        )
    )
    try:
        await asyncio.wait_for(extraction_model.started.wait(), timeout=2)
        progress_response = await api_client.get(
            f"/api/v1/properties/{draft['id']}/onboarding",
            headers=headers,
        )
        progress = progress_response.json()
        assert progress["status"] == "extracting"
        assert progress["extraction_progress"] == 10
        assert progress["extraction_stage"] == "extracting_profile"
        assert 0 <= progress["extraction_eta_seconds"] <= 20
    finally:
        extraction_model.release.set()
    extraction = await extraction_task
    assert extraction.status_code == 200
    review = extraction.json()
    assert review["status"] == "review"
    assert review["extraction_progress"] == 100
    assert review["extraction_stage"] == "complete"
    assert review["extraction_eta_seconds"] == 0
    assert review["extraction_method"] == "rules"
    assert review["profile"]["name"] == "Casa Verde"
    assert review["profile"]["check_in_time"] == "15:00"
    assert review["profile"]["wifi_network"] == "CasaVerde_Guest"
    assert "password" not in str(review).casefold()
    assert review["evidence"]["address"]["source_filename"] == "casa-verde.md"

    confirmed_profile = {key: value or "" for key, value in review["profile"].items()}
    confirmed_profile.update(
        name="Casa Verde Firenze",
        parking_instructions="Paid street parking is available nearby.",
    )
    completion = await api_client.patch(
        f"/api/v1/properties/{draft['id']}/onboarding",
        headers=headers,
        json=confirmed_profile,
    )
    assert completion.status_code == 200
    completed = completion.json()
    assert completed["status"] == "completed"
    assert completed["is_active"] is True
    assert completed["profile"]["name"] == "Casa Verde Firenze"

    async with db_session_factory() as session:
        property_record = await session.get(Property, UUID(draft["id"]))
        assert property_record is not None
        assert property_record.tenant_id == tenant_id
        assert property_record.name == "Casa Verde Firenze"
        assert property_record.address_json["formatted"] == "Via Verde 12, Florence, Italy"
        assert property_record.operational_details["check_in_time"] == "15:00"


async def test_narrative_mock_profile_is_returned_by_extraction_api(
    api_client: httpx.AsyncClient,
    db_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    settings = Settings(
        app_env="test",
        document_storage_root=tmp_path / "uploads",
        openrouter_api_key=None,
        openrouter_chat_api_key=None,
        openrouter_embedding_api_key=None,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_document_job_queue] = lambda: InProcessDocumentQueue(
        db_session_factory,
        settings=settings,
        embedding_provider=None,
    )
    token, _ = await _register(api_client)
    headers = {"Authorization": f"Bearer {token}"}
    draft = (
        await api_client.post("/api/v1/properties/onboarding", headers=headers)
    ).json()
    mock_path = Path(__file__).parents[1] / "mock_uploads" / "casa-oliva-guest-guide.md"

    upload = await api_client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        data={
            "title": "Casa Oliva guest guide",
            "document_type": "house_manual",
            "property_id": draft["id"],
        },
        files={"file": (mock_path.name, mock_path.read_bytes(), "text/markdown")},
    )
    assert upload.status_code == 202

    response = await api_client.post(
        f"/api/v1/properties/{draft['id']}/onboarding/extract",
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "review"
    assert payload["profile"]["name"] == "Casa Oliva"
    assert payload["profile"]["address"] == "Via delle Ginestre 18, 55100 Lucca LU, Italy"
    assert payload["profile"]["guest_capacity"] == "6"
    assert payload["profile"]["bedrooms"] == "3"
    assert payload["profile"]["check_in_time"] == "4:00 p.m."
    assert payload["profile"]["wifi_network"] == "CasaOliva-Guest"
    assert payload["profile"]["house_rules"].startswith("- ")
    assert "\n- " in payload["profile"]["amenities"]
    assert "Item | Guest information" not in payload["profile"]["amenities"]
    assert payload["profile"]["timezone"] is None
    assert payload["profile"]["bathrooms"] is None
    assert payload["evidence"]["name"]["source_filename"] == mock_path.name
    assert "password" not in response.text.casefold()


async def test_home_onboarding_requires_authentication(api_client: httpx.AsyncClient) -> None:
    response = await api_client.post("/api/v1/properties/onboarding")

    assert response.status_code == 401


def test_only_active_properties_and_valid_onboarding_drafts_accept_documents() -> None:
    inactive_property = Property(
        name="Imported but disabled",
        timezone="UTC",
        operational_details={},
        is_active=False,
    )
    onboarding_property = Property(
        name="Untitled home",
        timezone="UTC",
        operational_details={"onboarding": {"status": PropertyOnboardingStatus.DOCUMENTS.value}},
        is_active=False,
    )
    active_property = Property(
        name="Published home",
        timezone="UTC",
        operational_details={},
        is_active=True,
    )

    assert not can_attach_documents(inactive_property)
    assert can_attach_documents(onboarding_property)
    assert can_attach_documents(active_property)
