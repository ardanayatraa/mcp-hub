# Threat model

## Assets

- Connector credentials and delegation secrets (encrypted at rest).
- Admin sessions, MFA secrets and client keys (stored hashed).
- Business fields that an app approved for AI.
- The Hub database (configuration and audit metadata, never business records).

## Trust boundaries

| Boundary | Assumption |
|---|---|
| Admin UI | A signed-in admin can change policy within the developer's limits. After a secret is saved, the browser never receives it again. |
| AI client | The model and its client are untrusted. Arguments, tool descriptions and tool output are data. |
| App gateway | Signs which user is asking. A stolen client key without the delegation secret cannot read user-scoped data. |
| Connected app | Authority for users, tenants, rows and writes. The Hub additionally drops rows for other tenants. |
| Network | Connector destinations are attacker-influenced and are checked before every request. |

## Abuse cases covered (with tests)

- A connector or redirect that targets loopback, link-local, metadata or private addresses.
- An argument such as `user_id`, `tenant_id`, `role`, `approved` or `url` trying to widen access.
- Personal data in returned values, group labels, metadata, errors or the audit log (email, phone, national id and credential canaries).
- A cached tool name after a data source is disabled, a tool is disabled, an app is paused or archived, or a key is revoked.
- A key from one app calling another app's tools, or calling write tools without write permission.
- Inferring individual "totals only" values from small groups.
- A source contract changing under a tested tool: the tool stops until it is re-tested.
- Unreviewed routes or weakened authorization in a tool mapping.
- Malformed, oversized or wrongly-typed upstream responses becoming an empty "success".
- Replay of MFA codes, long-lived delegation tokens and cross-site admin requests.

## Residual risk

- A stolen client key can call that app's public-aggregate routes and the built-in tools until revoked or expired. User-scoped data still needs a fresh delegation token.
- A `super_admin` can publish any manifest-approved route and export encrypted configuration. This is an accepted administrator power, bounded by field policy and egress checks, and audited.
- Regex detectors cannot recognize every kind of personal data in free text. Apps must keep free-text fields out of the allowlist or mark them hidden.
- Rate limits are per process. A multi-worker deployment needs shared counters first.
