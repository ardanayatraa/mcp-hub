# Verification evidence

The Laravel contract fixture and integration report describe the current adapter.
The PRD audit and dependency scans are historical records, retained for traceability.

| Files | What they record |
|---|---|
| `PRD_AUDIT_*` | The first audit of the 0.1 code against PRD v1.2, with reproduction probes. |
| `PRD_FIX_*`, `PRD_LIVE_*` | Fixes and verification of that audit. |
| `DEPENDENCY_AUDIT.json`, `FRONTEND_DEPENDENCY_AUDIT.json` | Dependency vulnerability scans from that round. |
| `LARAVEL_CRUD_CONTRACT.json` | Laravel-generated dummy contract with a neutral application key, used by current Hub regression tests. |
| `LARAVEL_INTEGRATION_EVIDENCE.json` | Current integration checks; `integrations/laravel/verify.py` refreshes the live read catalog. |

Screenshots, raw JUnit XML reports and temporary installer fixtures are kept out
of Git. Metadata summaries above and the maintained `backend/tests` suite provide
the verification record. Ignored local copies are not included in the repository.

The Python scripts here drive the 0.1 admin API (separate approve step, `/revise`,
`process_dataset`) and are not meant to run against 0.2. Current behaviour is covered by
`backend/tests`.
