# TaskAm Backend

WhatsApp-native micro-job marketplace backend. Merchants post gigs via WhatsApp
voice note/text, Gemini turns them into structured tasks, students claim and
deliver, OPay handles payment.

## Stack

- **API:** FastAPI (Python 3.12)
- **DB: PostgreSQL 16 + SQLAlchemy 2.0 + Alembic + Psycopg 3
- **Queue/cache:** Redis
- **Storage:** Cloudflare R2 / S3-compatible (presigned uploads)
- **AI:** Gemini
- **Payments:** OPay

## Production deployment (single VM)

```bash
cp .env.example .env      # fill in real secrets, DOMAIN, POSTGRES_PASSWORD
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml exec app alembic upgrade head
docker compose -f docker-compose.prod.yml exec app python -m app.scripts.seed_admin \
  --phone "+2348000000000" --password "changeme123" --name "TaskAm Admin"
```

This runs: the API (gunicorn + uvicorn workers), the WhatsApp worker, the AI
parse worker, notification retry worker, daily backup service, Postgres,
Redis, and Caddy in front handling automatic HTTPS
via Let's Encrypt (point `DOMAIN`'s DNS A record at the VM first). Point
your WhatsApp webhook URL at `https://<DOMAIN>/api/v1/webhooks/whatsapp` and
your OPay webhook URL at `https://<DOMAIN>/api/v1/webhooks/opay`.

Production Compose now includes backups, worker retries/dead-letter queues,
structured JSON logging, optional Sentry reporting, notification retries, and
webhook rate limiting. Backups must still be mounted to durable off-site
storage, and external-provider calls must be verified with sandbox credentials.

## Local development

```bash
cp .env.example .env          # fill in real secrets before Phase 4+
docker compose up --build
```

- App: http://localhost:8000
- Health: http://localhost:8000/api/v1/health
- DB health: http://localhost:8000/api/v1/health/db
- Interactive docs: http://localhost:8000/docs

### Running migrations

```bash
docker compose exec app alembic upgrade head
```

To generate a new migration after changing models in `app/models/`:

```bash
docker compose exec app alembic revision --autogenerate -m "describe change"
```

### Seeding the first admin

```bash
docker compose exec app python -m app.scripts.seed_admin \
  --phone "+2348000000000" --password "changeme123" --name "TaskAm Admin"
```

## Project layout

```
app/
  core/       # config, security (JWT/bcrypt), auth dependencies (RBAC)
  db/         # SQLAlchemy engine/session
  models/     # ORM models — one file per entity, base.py has enums + state machine
  schemas/    # Pydantic request/response schemas
  routers/    # FastAPI routers (one per module)
  services/   # business logic, called by routers
  workers/    # background job handlers (Redis-backed queue)
  scripts/    # one-off scripts (admin seeding, etc.)
alembic/      # migrations
```

## Data model

11 core tables: `users`, `merchants`, `students`, `tasks`, `task_claims`,
`payments`, `deliverables`, `notifications`, `webhook_events`, `audit_logs`,
`disputes`. See `app/models/` for the full schema and `app/models/base.py`
for the task state machine (`TASK_STATE_TRANSITIONS`).

## Payments: OPay + Paystack

Both gateways are supported side by side. `payments.provider` records which
one was used per task; `payments.provider_reference` is that gateway's own
transaction reference. A merchant picks a provider (or omits it to use
`DEFAULT_PAYMENT_PROVIDER` from `.env`) when calling
`POST /tasks/{id}/payments/initiate`:

```json
{"provider": "PAYSTACK", "email": "merchant@example.com"}
```

Webhook endpoints: `/api/v1/webhooks/opay` and `/api/v1/webhooks/paystack`,
each independently HMAC-verified and idempotent. Adding a third gateway
means: a `<gateway>_service.py` with `initialize_transaction`/
`verify_webhook_signature`, a branch in `payment_service.initiate_payment`
and `handle_payment_webhook`, a webhook route, and an enum value added to
`WebhookSource` (needs its own migration — see
`alembic/versions/efaa893f5971_*.py` for the `ALTER TYPE ... ADD VALUE`
pattern, since Alembic's autogenerate doesn't detect Postgres enum value
additions on its own).

## Critical engineering rules baked into the design

1. **Webhook idempotency** — `webhook_events` has a unique constraint on
   `(source, external_id)`; every inbound WhatsApp/OPay event is written
   there before any processing.
2. **Transactional claiming** — task claiming uses `SELECT FOR UPDATE` in the
   service layer, backed by a partial unique index allowing one active claim.
3. **Payment verification** — OPay webhooks are HMAC-verified before use; the
   raw payload is stored on the `payments` row for replay/audit.
4. **Direct-to-storage uploads** — deliverables are uploaded via presigned
   URLs; the backend never proxies file binaries.
5. **Append-only audit log** — `audit_logs` rows are written in the same DB
   transaction as the state change they record.

## Build progress

- [x] Phase 1 — Project scaffolding (FastAPI, Docker, docker-compose, health checks)
- [x] Phase 2 — Data layer (all 11 tables, Alembic migrations, verified against real Postgres)
- [x] Phase 3 — Auth (JWT, bcrypt, RBAC middleware, merchant/student signup, login, admin seed script — tested end-to-end)
- [x] Phase 4 — WhatsApp webhook intake (verification handshake, idempotent inbound handling, Redis queue, background worker, voice note download to storage, merchant auto-provisioning, DRAFT task creation — tested end-to-end incl. duplicate-delivery dedup)
- [x] Phase 5 — AI parsing (Gemini schema validation, code-fence stripping, retry logic, full DRAFT→AI_PARSED→PENDING_MERCHANT_CONFIRMATION pipeline, CONFIRM/CANCEL WhatsApp reply handling — tested end-to-end with a mocked Gemini call)
- [x] Phase 6 — Marketplace & claiming (browse published tasks, transactional SELECT FOR UPDATE claiming — load-tested with 6 truly concurrent claim requests on one task: exactly 1 success, 5 correctly rejected)
- [x] Phase 7 — Payments (OPay order creation, HMAC webhook verification, idempotent webhook handling, CLAIMED→FUNDED transition — tested end-to-end incl. invalid-signature rejection and replay dedup via the real HTTP endpoint)
- [x] Phase 8 — Delivery (presigned upload flow, deliverable registration, submission, merchant approval, payout release — tested end-to-end through FUNDED→IN_PROGRESS→SUBMITTED→APPROVED→COMPLETED)
- [x] Phase 9 — Notifications (wired into every lifecycle event), disputes (raise + admin resolution both directions), admin (student verification, task oversight, audit log queries) — all tested end-to-end via the real HTTP API
- [x] Phase 10 — Deployment (production Dockerfile w/ gunicorn+healthcheck, docker-compose.prod.yml, Caddy reverse proxy for automatic HTTPS, deployment docs)

## What's built vs. what's verified against real external services

Everything in this codebase has been exercised against **real Postgres, real
Redis, and the real HTTP API** in this environment — not just written and
assumed to work. Specifically tested end-to-end: signup/login/RBAC, the full
webhook→worker→task pipeline, AI parsing state transitions (with a mocked
Gemini call), concurrent claiming (real race condition, 6 parallel requests),
payment funding (with a mocked OPay call, but real HMAC verification and
real idempotency over HTTP), the full delivery→approval→payout flow, and
disputes/admin end-to-end.

**Three integrations could NOT be tested against the live third-party API**,
because this sandbox has no network route to Google's, OPay's, or
Paystack's domains:

- `app/services/ai_service.py` — the Gemini SDK call shape
  (`client.models.generate_content(...)`, audio `Part.from_bytes(...)`).
  Schema validation, retry logic, and error handling around it are tested;
  the actual request/response shape against a live Gemini API key is not.
- `app/services/opay_service.py` — the OPay create-order endpoint path and
  request body. HMAC webhook verification IS tested (with a known secret,
  computed and checked exactly as OPay's docs describe), but order creation
  itself is not.
- `app/services/paystack_service.py` — the `/transaction/initialize`
  request/response fields. HMAC webhook verification (SHA512, raw body,
  `x-paystack-signature` header) IS tested end-to-end over real HTTP,
  including signature rejection and replay dedup — this is Paystack's
  well-documented, stable webhook scheme, so it's lower-risk than the
  create-order call shape.

All three have a comment at the top flagging this and pointing to where to
verify. Test all three against real API keys/sandbox credentials before
considering Phases 5 and 7 production-ready.

## Notes / decisions made so far

- Built in **Python/FastAPI** rather than Go — no architectural reason, just
  environment convenience. Swap is possible but would mean rewriting the
  models/services/routers in Go idioms.
- Used **bcrypt** directly instead of `passlib` — passlib's bcrypt backend is
  broken against recent bcrypt releases (throws on the internal self-test).
- `task_claims` retains history and uses a partial unique index to guarantee
  only one active claim. An unfunded claim can be released and reclaimed.
- Background jobs use Redis lists and delayed sorted sets, with exponential
  retry and dead-letter retention. The
  worker (`app/workers/whatsapp_worker.py`) runs as its own process/container
  (see `worker` service in docker-compose).
- Merchants aren't required to sign up before messaging the bot — first
  WhatsApp contact **auto-provisions** a minimal Merchant record
  (`app/services/merchant_service.py`). They can attach dashboard credentials
  later through the WhatsApp-code account-claim endpoints.

## Production hardening added

- WhatsApp/AI jobs retry with exponential backoff and exhausted jobs are kept
  in Redis dead-letter lists (`<queue>:dead`). Failed notifications are retried
  by a dedicated worker; SMTP email is supported when configured.
- Public webhooks use a shared Redis rate limit. Failed webhook processing is
  recorded and becomes eligible for retry on a later provider delivery.
- WhatsApp-created merchants can securely claim their dashboard account using
  the `/auth/claim-merchant/request` and `/complete` code flow.
- Students can release an unfunded claim; claim history remains available and
  only one active claim is permitted per task.
- Real gateway payout/refund calls are guarded by
  `PAYMENT_SETTLEMENT_ENABLED`. Students configure payout details through
  `PUT /api/v1/auth/student/payout-account`; provider references and errors are
  retained for reconciliation. Verify the enabled OPay merchant-product
  endpoints against your account before switching settlement on.
- `/health/ready` checks PostgreSQL and Redis and `/health/queues` exposes
  ready, delayed, and dead-letter counts. Production Compose includes daily
  PostgreSQL dumps with configurable retention. Mount `./backups` on durable
  off-site storage so backups survive loss of the VM.

## FarmSense integration — Phase 1

TaskAm now accepts agricultural service requests without removing the legacy
merchant/student marketplace. Supported categories are transport, labour,
tractor rental, veterinary, irrigation, warehousing, soil testing, extension
support, and other. Existing students are treated as legacy providers;
dedicated service providers can register at
`POST /api/v1/auth/signup/service-provider` with multiple provider types and
service categories.

FarmSense creates a request through
`POST /api/v1/internal/service-requests`. The raw request body is signed as
`HMAC-SHA256(secret, METHOD + "\\n" + PATH + "\\n" + timestamp + "\\n" + nonce + "\\n" + SHA256(raw_body))` using the
`X-FarmSense-Timestamp` and `X-FarmSense-Signature` headers. Timestamps outside
`SERVICE_AUTH_MAX_SKEW_SECONDS` are rejected. `external_request_id` is the
idempotency key: an exact replay returns the original TaskAm request, while
reusing the key with a different payload returns `409`.

Task status changes create transactional outbox rows. The
`outbound_webhook_worker` delivers canonical JSON to
`FARMSENSE_STATUS_WEBHOOK_URL`, signed with `X-TaskAm-Timestamp` and
`X-TaskAm-Signature`. Delivery retries with exponential backoff. Transport
requests require structured pickup/drop-off data and receive a stable
`TAM-LOG-*` handoff reference that FarmSense can pass to its logistics domain.

Agricultural WhatsApp text and voice requests use the same Gemini pipeline as
legacy tasks, with structured farm location, crop/livestock, acreage,
quantity, labour/equipment, urgency, and transport fields included in the
validated extraction and merchant confirmation.

Payment settlement is intentionally not part of the FarmSense Phase 1
contract. `PAYMENT_SETTLEMENT_ENABLED=false` remains the safe default. When it
is enabled, TaskAm calls the configured provider before changing local payment
state, but provider acceptance is not proof of final bank settlement. A later
phase must reconcile transfer/refund webhooks before the combined platform can
represent settlement as final.
