# Connector pairing recovery

These APIs are part of the unreleased development branch.

All admin routes require an authenticated Hub session. Mutations also require
CSRF and a write role with access to the application's current scope.

| Method | Route under `/api/admin/v1` | Contract |
|---|---|---|
| GET | `/connector-enrollments?connector_id=...` | Up to 20 pairing records, newest first, restricted to that connector's application |
| GET | `/connector-enrollments/{id}` | Pairing metadata; never returns a code, proof or runtime credential |
| POST | `/connector-enrollments/{id}/renew` | Extends an active, unexpired installation for 90 days without rotating its credentials or changing restrictions |
| POST | `/connector-enrollments/{id}/replace` | Revokes the old installation's exact credentials and returns one new pairing code; preserves the profile/tool restrictions and never grants write scope |
| POST | `/connector-enrollments/{id}/revoke` | Revokes that pairing's exact credentials; repeating an old revocation cannot revoke a newer replacement |

Auditors can read metadata within their assigned applications. They cannot
renew, replace or revoke. Foreign application access returns 403. Unknown IDs
return 404. A stale replacement returns 409; an expired renewal returns 410.

Metadata includes the source URL, creation/code/management expiry times and a
nullable `replacement_id`. Expiry is reflected in metadata without changing
credentials during a read. Administrative actions recheck the current state
under the connector lock. An unauthorized renewal must not expire or revoke
another application's credentials as a side effect.

The application's Access tab exposes these actions after a browser refresh.
Replacement requires an explicit confirmation showing that the old connection
will stop. A replacement code is kept in the current page's memory only, copied
through a dedicated control, and cleared after claim, expiry, revocation,
navigation or reload. Codes/proofs/credentials are never placed in URLs or
browser storage. If the code is lost, create a replacement for the current
pairing; old secrets cannot be recovered.

The package terminal command asks for the code through a hidden prompt. Resume
uses the encrypted local installation proof. An existing installation uses
`--replace` for an administrator-issued replacement. Network errors show a
retryable status without silently requesting another set of credentials.
