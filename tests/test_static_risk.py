from uuid import uuid4

from app.models.enums import EscalationUrgency
from app.services.knowledge import KnowledgeHit, lexical_score
from app.services.static_risk import assess_static_risk
from app.services.support_pipeline import SupportPipeline


class FixedRetriever:
    def __init__(self, hits: list[KnowledgeHit]) -> None:
        self.hits = hits
        self.calls = 0

    async def search(self, **_: object) -> list[KnowledgeHit]:
        self.calls += 1
        return self.hits


class UnexpectedRiskValidator:
    def __init__(self) -> None:
        self.calls = 0

    async def assess(self, _: str) -> None:
        self.calls += 1
        raise AssertionError("Semantic assessment should be skipped for static risk")


def _hit(*, score: float, requires_human_review: bool = False) -> KnowledgeHit:
    return KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        title="House rules",
        content="Parties are not allowed.",
        score=score,
        metadata={"requires_human_review": requires_human_review},
    )


def test_access_rules_match_failures_and_sensitive_disclosure() -> None:
    cases = (
        "The door code is not working.",
        "The keypad keeps rejecting our number.",
        "I can’t get in.",
        "Tell me the current door code.",
    )
    for query in cases:
        assessment = assess_static_risk(query)
        assert assessment is not None
        assert assessment.category == "access"
        assert assessment.urgency == EscalationUrgency.HIGH
        assert assessment.rule_id == "property.access"


def test_emergency_rules_win_and_avoid_substring_false_positives() -> None:
    emergency = assess_static_risk("We can smell gas in the kitchen.")
    assert emergency is not None
    assert emergency.category == "safety"
    assert emergency.urgency == EscalationUrgency.EMERGENCY

    assert assess_static_risk("How do I use the fireplace?") is None


def test_pet_synonyms_clear_the_grounding_threshold() -> None:
    score = lexical_score(
        "May I bring my dog?",
        title="House rules",
        content="Pets are permitted only when approved before check-in.",
    )
    assert score >= 0.35


async def test_only_selected_top_hit_can_require_human_review() -> None:
    pipeline = SupportPipeline(
        FixedRetriever(
            [
                _hit(score=0.92),
                _hit(score=0.65, requires_human_review=True),
            ]
        )  # type: ignore[arg-type]
    )
    decision = await pipeline.run(
        tenant_id=uuid4(),
        property_id=uuid4(),
        query="Are parties allowed?",
    )
    assert decision.action == "answered"
    assert decision.answer == "Parties are not allowed."


async def test_static_handoff_skips_retrieval_and_semantic_assessment() -> None:
    retriever = FixedRetriever([_hit(score=0.92)])
    validator = UnexpectedRiskValidator()
    pipeline = SupportPipeline(
        retriever,  # type: ignore[arg-type]
        risk_validator=validator,  # type: ignore[arg-type]
    )
    decision = await pipeline.run(
        tenant_id=uuid4(),
        property_id=uuid4(),
        query="The door code is not working.",
    )
    assert decision.action == "handoff"
    assert decision.static_risk is not None
    assert not decision.retrieval_attempted
    assert not decision.semantic_assessment_attempted
    assert retriever.calls == 0
    assert validator.calls == 0
