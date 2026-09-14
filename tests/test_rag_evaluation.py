from pathlib import Path
from uuid import UUID, uuid4

from app.services.knowledge import KnowledgeHit
from app.services.support_pipeline import PipelineDecision
from scripts.rag_evaluation import (
    RagEvaluationCase,
    RagEvaluationMetrics,
    RagEvaluationResult,
    RagEvaluationSuite,
    calculate_metrics,
    evaluate_case,
    evaluate_thresholds,
    load_suite,
    select_cases,
)

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
    assert suite.version == "1.1.0"
    assert suite.thresholds.minimum_safety_access_recall == 1.0
    assert suite.thresholds.maximum_provider_error_rate == 0.0

    tags = {tag for case in suite.cases for tag in case.tags}
    assert {"retrieval", "handoff", "safety", "security", "prompt-injection"} <= tags
    assert sum("known-gap" in case.tags for case in suite.cases) == 0

    baseline = select_cases(suite, include_known_gaps=False)
    assert len(baseline.cases) == 22
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
    assert result.decision_reason is None
    assert result.retrieved_hits == ("Wi-Fi and home office=0.910",)


async def test_evaluator_enforces_handoff_decision_invariants() -> None:
    case = RagEvaluationCase(
        id="invalid-handoff",
        query="Please handle this",
        expected_action="handoff",
        expected_urgency="normal",
        tags=["handoff"],
    )
    invalid_handoff = PipelineDecision(
        action="handoff",
        answer="This must not be sent automatically.",
        reason=None,
        urgency=None,
        summary=None,
        proposed_reply=None,
        hits=[],
        retrieval_error=None,
    )

    result = await evaluate_case(
        StaticPipeline(invalid_handoff),
        tenant_id=uuid4(),
        property_id=uuid4(),
        case=case,
    )

    assert not result.passed
    assert "invariant: handoff decision cannot include an automatic answer" in result.failures
    assert "invariant: handoff decision must include a reason" in result.failures
    assert "invariant: handoff decision must include urgency" in result.failures


def _metric_result(
    *,
    case_id: str,
    passed: bool,
    action: str,
    documents: tuple[str, ...] = (),
    provider_error: bool = False,
) -> RagEvaluationResult:
    return RagEvaluationResult(
        case_id=case_id,
        passed=passed,
        failures=(),
        actual_action=action,
        actual_urgency=None,
        top_document=documents[0] if documents else None,
        top_score=0.9 if documents else None,
        decision_reason=None,
        reason_category=None,
        retrieved_documents=documents,
        retrieved_hits=(),
        provider_error=provider_error,
    )


def test_metrics_report_category_rates_and_threshold_failures() -> None:
    suite = RagEvaluationSuite(
        name="metrics",
        version="1",
        description="Metric calculation fixture",
        cases=[
            RagEvaluationCase(
                id="supported",
                query="Known question",
                expected_action="answered",
                expected_top_document="Guide",
                expected_answer_contains=["known"],
                tags=["retrieval"],
            ),
            RagEvaluationCase(
                id="unsupported",
                query="Unknown question",
                expected_action="handoff",
                expected_urgency="normal",
                tags=["unsupported"],
            ),
            RagEvaluationCase(
                id="emergency",
                query="Emergency",
                expected_action="handoff",
                expected_urgency="emergency",
                tags=["safety"],
            ),
        ],
    )
    results = [
        _metric_result(case_id="supported", passed=True, action="answered", documents=("Guide",)),
        _metric_result(case_id="unsupported", passed=False, action="answered"),
        _metric_result(case_id="emergency", passed=True, action="handoff", provider_error=True),
    ]

    metrics = calculate_metrics(suite, results)

    assert metrics.case_pass_rate == 2 / 3
    assert metrics.action_accuracy == 2 / 3
    assert metrics.automatic_answer_precision == 1 / 2
    assert metrics.unsupported_handoff_rate == 0.0
    assert metrics.safety_access_recall == 1.0
    assert metrics.retrieval_recall_at_1 == 1.0
    assert metrics.retrieval_recall_at_k == 1.0
    assert metrics.retrieval_mrr == 1.0
    assert metrics.false_handoff_rate == 0.0
    assert metrics.provider_error_rate == 1 / 3

    gate = evaluate_thresholds(metrics, suite.thresholds)
    assert not gate.passed
    assert any(failure.startswith("case pass rate:") for failure in gate.failures)
    assert any(failure.startswith("unsupported handoff rate:") for failure in gate.failures)
    assert any(failure.startswith("provider-error rate:") for failure in gate.failures)


def test_threshold_gate_accepts_compliant_metrics() -> None:
    metrics = RagEvaluationMetrics(
        total_cases=1,
        passed_cases=1,
        case_pass_rate=1.0,
        action_accuracy=1.0,
        automatic_answer_precision=1.0,
        unsupported_handoff_rate=1.0,
        safety_access_recall=1.0,
        retrieval_recall_at_1=1.0,
        retrieval_recall_at_k=1.0,
        retrieval_mrr=1.0,
        false_handoff_rate=0.0,
        provider_error_rate=0.0,
    )
    suite = load_suite(DATASET_PATH)

    gate = evaluate_thresholds(metrics, suite.thresholds)

    assert gate.passed
    assert gate.failures == ()
