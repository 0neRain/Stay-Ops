# StayOps AI — Project Specification

## Project description

StayOps AI is a multi-tenant, human-supervised support agent for short-term-rental
owners and property managers. It receives guest questions from a web interface or
a property-management-system (PMS) inbox, combines live reservation data with
approved property knowledge, and sends an answer only when application policy
allows it. Risky, ambiguous, unsupported, or action-oriented requests are handed
to a human with a summary, supporting context, and a proposed reply.

OpenRouter is the model gateway. LangChain provides model, tool, and retrieval
interfaces, while LangGraph coordinates the stateful workflow and pauses it for
human review. PostgreSQL is the source of truth; pgvector stores property-scoped
knowledge embeddings.

The system is intended to demonstrate production-oriented AI engineering:
provider abstraction, multi-tenancy, RAG, tool use, durable workflows, explicit
authorization, human handoff, evaluation, and controlled knowledge improvement.

## Features

### Guest support

- Receive guest messages through web chat and PMS webhooks.
- Resolve the tenant, property, reservation, guest, and conversation.
- Retrieve live reservation, listing, calendar, and conversation information.
- Search approved, property-scoped house rules and operating instructions.
- Generate source-grounded answers in the property's preferred tone and language.
- Prevent automatic replies when required information is missing or conflicting.

### PMS and model integrations

- Provider-neutral PMS interface with Hostaway, Guesty, and demo implementations.
- Idempotent webhook ingestion and safe handling of out-of-order events.
- OpenRouter-backed chat and embedding adapters.
- Configurable model selection without business logic depending on a model name.
- Retries, timeouts, rate-limit handling, and recorded tool executions.

### Human handoff

- Escalate refunds, cancellations, safety incidents, access problems, conflicting
  information, failed tools, and unsupported requests.
- Persist LangGraph state so an interrupted run can resume after review.
- Present conversation context, escalation reason, evidence, and a proposed reply.
- Let a human approve, edit, reject, or respond directly.
- Lock human-owned conversations to prevent simultaneous automated replies.

### Controlled improvement

- Accept property-specific or organization-wide TXT, Markdown, HTML, PDF, and DOCX
  sources through an authenticated upload endpoint.
- Validate file type, signature, encoding, compressed size, and extracted-text size;
  then extract, normalize, and chunk text for retrieval.
- Store raw files behind random internal keys and expose processing status without
  exposing storage paths.
- Detect missing knowledge and frequently corrected answers.
- Redact personal data and generate a draft knowledge candidate.
- Require an authorized reviewer before publication.
- Version knowledge, retain its source, and support rollback.
- Reindex approved content and run relevant regression evaluations.
- Never train on or publish a guest conversation automatically.

### Owner operations

- Manage organizations, memberships, properties, and integrations.
- Role-based access for owners, managers, support agents, and viewers.
- Review conversations, escalations, knowledge, feedback, and audit events.
- Track response latency, escalation correctness, corrections, tool errors, and cost.

## Security safeguards

- Every domain record is tenant-scoped; authorization checks use active tenant
  membership rather than accepting a tenant ID from an untrusted request body.
- Passwords are hashed with Argon2 and are never encrypted or logged.
- Short-lived JWT access tokens are paired with rotating refresh tokens.
- Refresh tokens are stored only as SHA-256 hashes and sent in HttpOnly cookies.
- Reuse of a revoked or rotated refresh token is rejected and recorded.
- PMS credentials and webhook secrets must be encrypted at rest with keys held
  outside the database.
- Sensitive access information is released only to a verified reservation and
  within configured stay windows.
- Model tools are allow-listed and schema-validated; the model cannot construct
  arbitrary URLs or directly execute external side effects.
- Refunds, cancellations, reservation changes, payments, and security-sensitive
  actions require deterministic authorization and human approval.
- Guest messages and uploaded documents are untrusted data and cannot override
  system policy or tool authorization.
- Document uploads use an allow-list, size limits, content checks, path-safe random
  storage keys, integrity hashes, and tenant/property authorization. Extracted
  content remains unavailable to the agent until an authorized review publishes it.
- Webhooks are authenticated where the provider supports it, deduplicated, queued,
  and processed idempotently.
- Logs redact secrets and unnecessary personal data. Tool calls, model decisions,
  automated replies, and human actions are auditable.
- CORS is allow-listed. Production startup rejects default secrets and insecure
  refresh-cookie configuration.
- Rate limiting, request-size limits, retention controls, data export, and deletion
  workflows are required before a public production launch.

## Project API

All routes are versioned under `/api/v1`. `Implemented` describes the current
foundation; `Planned` routes define the intended public contract.

### System and authentication

| Method | Route | Status | Purpose |
|---|---|---:|---|
| GET | `/health` | Implemented | Process health check |
| POST | `/api/v1/auth/register` | Implemented | Create an organization and owner account |
| POST | `/api/v1/auth/login` | Implemented | Authenticate and select an active tenant |
| POST | `/api/v1/auth/refresh` | Implemented | Rotate the refresh token and issue an access token |
| POST | `/api/v1/auth/logout` | Implemented | Revoke the current refresh session |
| GET | `/api/v1/auth/me` | Implemented | Return the authenticated user and memberships |

### Properties and integrations

| Method | Route | Status | Purpose |
|---|---|---:|---|
| GET/POST | `/api/v1/properties` | Planned | List or create properties |
| GET/PATCH | `/api/v1/properties/{property_id}` | Planned | Read or update a property |
| GET/POST | `/api/v1/integrations` | Planned | List or connect PMS providers |
| GET | `/api/v1/integrations/{integration_id}/health` | Planned | Check provider access |
| POST | `/api/v1/webhooks/{provider}` | Planned | Receive authenticated PMS events |

### Conversations and handoff

| Method | Route | Status | Purpose |
|---|---|---:|---|
| POST | `/api/v1/chat/messages` | Implemented | Receive and route a web-chat message |
| GET | `/api/v1/conversations` | Planned | Search tenant conversations |
| GET | `/api/v1/conversations/{conversation_id}` | Planned | Read a conversation timeline |
| POST | `/api/v1/conversations/{conversation_id}/messages` | Planned | Send a human reply |
| GET | `/api/v1/escalations` | Implemented | List the human handoff queue |
| POST | `/api/v1/escalations/{escalation_id}/claim` | Implemented | Lock and assign a conversation |
| POST | `/api/v1/escalations/{escalation_id}/resolve` | Implemented | Send or record a resolution |

### Knowledge and evaluation

| Method | Route | Status | Purpose |
|---|---|---:|---|
| POST | `/api/v1/knowledge/documents` | Implemented | Upload and enqueue a knowledge source for processing |
| GET | `/api/v1/knowledge/documents/{document_id}` | Implemented | Read tenant-scoped processing and review status |
| GET | `/api/v1/knowledge/candidates` | Planned | List suggested improvements |
| POST | `/api/v1/knowledge/candidates/{candidate_id}/approve` | Planned | Publish a reviewed candidate |
| POST | `/api/v1/knowledge/candidates/{candidate_id}/reject` | Planned | Reject a candidate with a reason |
| POST | `/api/v1/evaluations/run` | Planned | Run regression and safety cases |
| GET | `/api/v1/analytics/overview` | Planned | Return operational metrics |

## Authentication contract

Registration and login return a short-lived bearer token. They also set a rotating
refresh token in an HttpOnly cookie. Clients send the access token as
`Authorization: Bearer <token>`. Refresh and logout use the cookie and do not
return it to JavaScript. If a user belongs to multiple organizations, login must
specify the desired `tenant_id`.
