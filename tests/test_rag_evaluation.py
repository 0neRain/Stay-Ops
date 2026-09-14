from pathlib import Path
from uuid import UUID, uuid4

from app.services.knowledge import KnowledgeHit
from app.services.support_pipeline import PipelineDecision
from scripts.rag_evaluation import RagEvaluationCase, evaluate_case, load_suite, select_cases

DATASET_PATH = Path(__file__).parents[1] / "evals" / "rag_v1.json"


class StaticPipeline:
    def __init__(self, decision: PipelineDecision) -> None:
        self.decision = decision

    async def run(self, *, tenant_id: UUID, property_id: UUID, query: str) -> PipelineDecision:
        return self.decision


def _answered_decision() -> PipelineDecision:
    hit = KnowledgeHit(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        title="Wi-Fi and home office",
        content="The network is CasaAurora_Guest and the password is welcome-aurora.",
        score=0.91,
        metadata={},
    )
    return PipelineDecision(
        action="answered",
        answer=hit.content,
        reason=None,
        urgency=None,
        summary=None,
        proposed_reply=None,
        hits=[hit],
        retrieval_error=None,
    )


def test_rag_dataset_is_valid_and_covers_core_behaviors() -> None:
    suite = load_suite(DATASET_PATH)
    assert suite.name == "stayops-rag-core"
    assert len(suite.cases) == 22
    assert {case.expected_action for case in suite.cases} == {"answered", "handoff"}

    tags = {tag for case in suite.cases for tag in case.tags}
    assert {"retrieval", "handoff", "safety", "security", "prompt-injection"} <= tags
    assert sum("known-gap" in case.tags for case in suite.cases) == 1

    baseline = select_cases(suite, include_known_gaps=False)
    assert len(baseline.cases) == 21
    assert all("known-gap" not in case.tags for case in baseline.cases)
    assert len(select_cases(suite, include_known_gaps=True).cases) == 22


async def test_evaluator_accepts_a_grounded_result() -> None:
    case = RagEvaluationCase(
        id="test-wifi",
        query="What is the Wi-Fi password?",
        expected_action="answered",
        expected_top_document="Wi-Fi and home office",
        expected_answer_contains=["CasaAurora_Guest", "welcome-aurora"],
        minimum_top_score=0.35,
        forbidden_answer_contains=["unknown-network"],
        tags=["retrieval"],
    )
    result = await evaluate_case(
        StaticPipeline(_answered_decision()),
        tenant_id=uuid4(),
        property_id=uuid4(),
        case=case,
    )
    assert result.passed
    assert result.failures == ()


async def test_evaluator_reports_action_source_score_and_grounding_failures() -> None:
    case = RagEvaluationCase(
        id="test-mismatch",
        query="What are the quiet hours?",
        expected_action="handoff",
        expected_urgency="normal",
        expected_top_document="House rules",
        minimum_top_score=0.95,
        forbidden_answer_contains=["welcome-aurora"],
        tags=["regression"],
    )
    result = await evaluate_case(
        StaticPipeline(_answered_decision()),
        tenant_id=uuid4(),
        property_id=uuid4(),
        case=case,
    )
    assert not result.passed
    assert len(result.failures) == 5
    assert any(failure.startswith("action:") for failure in result.failures)
    assert any(failure.startswith("urgency:") for failure in result.failures)
    assert any(failure.startswith("top document:") for failure in result.failures)
    assert any(failure.startswith("top score:") for failure in result.failures)
    assert any("forbidden text" in failure for failure in result.failures)
