import asyncio
from pathlib import Path
from uuid import uuid4

from app.services.home_profile_extraction import (
    HomeSourceDocument,
    extract_home_profile,
)

MOCK_GUIDE = Path(__file__).parents[1] / "mock_uploads" / "casa-oliva-guest-guide.md"


class StructuredExtractionModel:
    def with_structured_output(self, schema: object) -> "StructuredExtractionModel":
        del schema
        return self

    async def ainvoke(self, messages: object) -> object:
        del messages
        return {
            "name": {
                "value": "Casa Oliva from model",
                "source_number": 1,
                "evidence": "Welcome to Casa Oliva",
                "confidence": 0.99,
            },
            "timezone": {},
            "address": {},
            "property_type": {},
            "guest_capacity": {},
            "bedrooms": {},
            "bathrooms": {},
            "check_in_time": {},
            "check_out_time": {},
            "wifi_network": {},
            "parking_instructions": {},
            "access_instructions": {},
            "house_rules": {},
            "amenities": {},
            "emergency_information": {},
            "local_recommendations": {},
        }


class HangingExtractionModel:
    def with_structured_output(self, schema: object) -> "HangingExtractionModel":
        del schema
        return self

    async def ainvoke(self, messages: object) -> object:
        del messages
        await asyncio.Event().wait()
        raise AssertionError("The hanging model should only be stopped by a timeout")


def mock_source() -> HomeSourceDocument:
    return HomeSourceDocument(
        id=uuid4(),
        filename=MOCK_GUIDE.name,
        content=MOCK_GUIDE.read_text(encoding="utf-8"),
    )


async def test_narrative_guide_extracts_a_useful_profile_without_provider() -> None:
    result = await extract_home_profile([mock_source()], model=None)

    assert result.method == "rules"
    assert result.profile.name == "Casa Oliva"
    assert result.profile.address == "Via delle Ginestre 18, 55100 Lucca LU, Italy"
    assert result.profile.property_type == "cottage"
    assert result.profile.guest_capacity == "6"
    assert result.profile.bedrooms == "3"
    assert result.profile.check_in_time == "4:00 p.m."
    assert result.profile.check_out_time == "10:30 a.m."
    assert result.profile.wifi_network == "CasaOliva-Guest"
    assert "gravel area" in (result.profile.parking_instructions or "")
    assert "wooden garden gate" in (result.profile.access_instructions or "")
    assert "Emergency services: 112" == result.profile.emergency_information
    assert result.profile.house_rules is not None
    assert result.profile.house_rules.splitlines()[0].startswith("- ")
    assert len(result.profile.house_rules.splitlines()) == 7
    assert result.profile.amenities is not None
    assert all(line.startswith("- ") for line in result.profile.amenities.splitlines())
    assert "Item | Guest information" not in result.profile.amenities
    assert "| ---" not in result.profile.amenities
    assert "- Heating: Wall thermostats" in result.profile.amenities
    assert result.profile.local_recommendations is not None
    assert all(
        line.startswith("- ") for line in result.profile.local_recommendations.splitlines()
    )
    assert result.profile.timezone is None
    assert result.profile.bathrooms is None
    assert set(result.evidence) >= {
        "name",
        "address",
        "guest_capacity",
        "bedrooms",
        "check_in_time",
        "check_out_time",
        "wifi_network",
    }
    rendered = result.model_dump_json().casefold()
    assert "password" not in rendered
    assert "access code" not in rendered
    assert "key-safe" not in rendered


async def test_model_values_are_primary_and_local_extraction_fills_model_gaps() -> None:
    result = await extract_home_profile([mock_source()], model=StructuredExtractionModel())

    assert result.method == "openrouter"
    assert result.profile.name == "Casa Oliva from model"
    assert result.profile.address == "Via delle Ginestre 18, 55100 Lucca LU, Italy"
    assert result.profile.wifi_network == "CasaOliva-Guest"
    assert result.evidence["name"].confidence == 0.99
    assert result.evidence["address"].confidence == 0.86


async def test_provider_timeout_falls_back_to_local_extraction() -> None:
    result = await extract_home_profile(
        [mock_source()],
        model=HangingExtractionModel(),
        model_timeout_seconds=0.01,
    )

    assert result.method == "rules"
    assert result.profile.name == "Casa Oliva"
    assert result.profile.wifi_network == "CasaOliva-Guest"
