# Combined platform contract v1

All IDs are opaque. Service requests use per-service secrets and sign `METHOD`,
path, Unix timestamp, nonce, and the SHA-256 hex digest of the exact raw body,
joined with newlines. Receivers allow five minutes of clock skew and reject a
nonce reused by the same service. JWT, where retained, is compatibility only.
Webhooks sign `timestamp + "." + raw_body`.

FarmSense calls `POST /api/v1/internal/service-requests` with a mandatory
`Idempotency-Key`. TaskAm and FarmSense call Logistics at `POST
/internal/v1/agricultural/quotes`, `POST /internal/v1/agricultural/bookings`,
and `GET /internal/v1/agricultural/bookings/{logistics_delivery_id}`.
Logistics responses use `{"success":true,"data":{"quote":...}}` or a
`booking` member.
