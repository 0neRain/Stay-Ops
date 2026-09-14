import os
from pathlib import Path

import pytest

from scripts.eval_embedding_snapshot import ReplayEmbeddingProvider
from scripts.rag_evaluation import (
    calculate_metrics,
    evaluate_thresholds,
    load_suite,
    run_evaluation,
)
from scripts.seed_mock_knowledge import MockSeedSettings

ROOT = Path(__file__).parents[1]
DATASET_PATH = ROOT / "evals" / "rag_v1.json"
SNAPSHOT_PATH = ROOT / "evals" / "fixtures" / "openrouter_embeddings_v1.manifest.json"


@pytest.mark.integration
async def test_snapshot_suite_against_postgres() -> None:
    database_url = os.environ.get("RAG_EVAL_DATABASE_URL")
    if not database_url:
        pytest.skip("RAG_EVAL_DATABASE_URL is not configured")

    suite = load_suite(DATASET_PATH)
    provider = ReplayEmbeddingProvider.from_manifest(SNAPSHOT_PATH)
    settings = MockSeedSettings(
        app_env="test",
        mock_database_url=database_url,
        openrouter_embedding_model=provider.source_model,
    )
    results = await run_evaluation(
        settings=settings,
        suite=suite,
        tenant_slug="snapshot-eval",
        property_external_id="snapshot-casa-aurora",
        embedding_provider=provider,
    )
    metrics = calculate_metrics(suite, results)
    gate = evaluate_thresholds(metrics, suite.thresholds)
    case_failures = [
        f"{result.case_id}: {'; '.join(result.failures)}" for result in results if not result.passed
    ]

    assert gate.passed, "\n".join(case_failures + list(gate.failures))
