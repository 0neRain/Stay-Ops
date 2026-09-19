# StayOps AI

StayOps AI is a human-supervised guest-support agent for short-term-rental
operators. The repository currently contains the project specification,
authentication foundation, and first PostgreSQL schema.

See [PROJECT.md](PROJECT.md) for the product and API specification.

## Local setup

1. Copy `.env.example` to `.env` and replace `JWT_SECRET_KEY`.
2. Start PostgreSQL: `docker compose up -d db`.
3. Create a virtual environment and install the project with its document and
   development dependencies: `pip install -e ".[documents,dev]"`.
4. Apply migrations with `alembic upgrade head`.
5. Optionally create the isolated mock database and apply the same migrations:

   ```powershell
   docker compose --profile mock up -d mock-db
   $env:DATABASE_URL="postgresql+psycopg://stayops:stayops@localhost:5433/stayops_mock"
   alembic upgrade head
   Remove-Item Env:DATABASE_URL
   ```

6. Set `OPENROUTER_API_KEY`, then populate the mock KB with real embeddings using
   `python -m scripts.seed_mock_knowledge`. The embedding model is preconfigured as
   `openai/text-embedding-3-small`.

   The mock seed writes only to `MOCK_DATABASE_URL`. Embeddings are cached by content hash,
   provider, model, and dimensions in `.cache/mock_embeddings.sqlite3`. Editing or adding mock
   chunks and rerunning the command embeds only new content. Changing the embedding model
   invalidates the relevant cache entries automatically.

   The mock database, seed, and cache are development-only. Seed code is excluded from
   distribution builds and refuses to run when `APP_ENV=production`.
7. Run `fastapi dev app/main.py`.

The API documentation is available at `http://localhost:8000/docs`.

The support pipeline uses published, tenant/property-scoped knowledge only. Add a shared
`OPENROUTER_API_KEY` to enable the configured `openai/gpt-5-mini` answering client and
`openai/text-embedding-3-small` pgvector retrieval. Optional
`OPENROUTER_CHAT_API_KEY` and `OPENROUTER_EMBEDDING_API_KEY` values override the shared key.
Without a key, the deterministic lexical fallback keeps local development and tests offline.

## Document ingestion

Owners and managers can upload UTF-8 TXT, Markdown, HTML, PDF, or DOCX files to
`POST /api/v1/knowledge/documents`. A document can belong to one property or be
organization-wide. The pipeline validates and stores the file, extracts and normalizes
its text, creates overlapping retrieval chunks, and requests OpenRouter embeddings when
credentials are configured. `GET /api/v1/knowledge/documents/{document_id}` exposes the
processing result.

Processed uploads enter `pending_review`; they are never published to the guest agent
automatically. Without an embedding key, content is retained with an explicit `pending`
embedding state. The current in-process background runner is suitable for local development;
a production deployment should move jobs to a durable queue and add malware scanning.

## Semantic risk index

After applying migrations, build or refresh the code-owned policy embedding index:

```powershell
python -m app.cli.build_policy_embeddings
```

The command embeds only new or changed policy examples. At runtime, high-similarity
matches can only add a human handoff; they cannot override deterministic authorization.
When embeddings are configured but the matching policy index is unavailable, validation
fails closed to handoff. Configure the calibrated cutoff with `SEMANTIC_RISK_THRESHOLD`.

## RAG evaluation

After migrating the isolated mock database, run the deterministic retrieval and routing
regression suite using the committed OpenRouter embedding snapshot. The runner creates the
mock scope and seeds the required knowledge and policy vectors inside the evaluation
transaction:

```powershell
python -m scripts.rag_evaluation
```

To intentionally refresh the snapshot after changing the dataset, mock knowledge, policy
examples, or embedding model, run:

```powershell
python -m scripts.capture_eval_embeddings
```

Snapshot refresh requires OpenRouter credentials. Review and commit both generated files in
`evals/fixtures`. To compare the snapshot with the provider's current behavior, run
`python -m scripts.rag_evaluation --embedding-mode live`.

The development-only dataset is stored in `evals/rag_v1.json`. It checks top-source
retrieval, grounded answer content, confidence thresholds, safety urgency, unsupported
questions, and prompt-injection behavior. All current cases are part of the baseline;
future aspirational cases can use the `known-gap` tag and `--include-known-gaps` option.
The runner also enforces decision invariants and suite-level gates for action accuracy,
automatic-answer precision, unsupported-request handoff, safety/access recall, retrieval
Recall@1, Recall@k, MRR, false handoffs, and provider errors. Gate thresholds are declared
in the dataset so changes are explicit and reviewable.
