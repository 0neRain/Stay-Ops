# StayOps AI

StayOps AI is a human-supervised guest-support agent for short-term-rental
operators. The repository currently contains the project specification,
authentication foundation, and first PostgreSQL schema.

See [PROJECT.md](PROJECT.md) for the product and API specification.

## Local setup

1. Copy `.env.example` to `.env` and replace `JWT_SECRET_KEY`.
2. Start PostgreSQL: `docker compose up -d db`.
3. Create a virtual environment and install the project.
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

After seeding the isolated mock database, run the retrieval and routing regression suite:

```powershell
python -m scripts.rag_evaluation
```

The development-only dataset is stored in `evals/rag_v1.json`. It checks top-source
retrieval, grounded answer content, confidence thresholds, safety urgency, unsupported
questions, and prompt-injection behavior. All current cases are part of the baseline;
future aspirational cases can use the `known-gap` tag and `--include-known-gaps` option.
