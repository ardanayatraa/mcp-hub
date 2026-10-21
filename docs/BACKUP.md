# Backup, upgrade and rollback

## Configuration backup

**Settings → Export configuration** (or `POST /api/admin/v1/operations/export`, super
admin) produces `mcp-hub-metadata-v1` JSON with apps, connector credentials (ciphertext),
contract history, data sources and field policy, tools with their routes and test runs,
admin app assignments and client key hashes. Admin users, sessions, MFA state and the
activity log are not included; keep a database dump for those.

**Restore** (`POST /operations/import`) validates the whole document before replacing
anything, inserts parents before children in one transaction, and rolls back on invalid
relationships. Invalid or unknown tool configurations are restored disabled. Unknown admin
ids are never granted access. Backups from 0.1 are accepted: their placeholder tables
(MCP profiles, skills) are ignored and tools left in the old `validated`/`approved` states
come back as drafts. A restore replaces all exported tables, so export first.

Restores need the `SECRET_ENCRYPTION_KEY` the backup was made with, as the current key or in
`SECRET_ENCRYPTION_KEY_PREVIOUS`; with another key, stored credentials cannot be decrypted. The request limit is 1 MB; use a database dump for larger states.

**Purge** removes activity, health checks, test runs and sessions older than
`AUDIT_RETENTION_DAYS` (default 90), plus expired MFA challenges and memories and model
gateway usage older than about a year. It runs every `PURGE_INTERVAL_HOURS` (default 6);
`POST /operations/purge` runs it at once. A purged passing test means that tool needs a new test before its
next publish.

## Database dumps

For PostgreSQL, schedule `pg_dump` and keep dumps off the host with restricted access. A
restore drill: stop the Hub, restore the dump, start it, sign in, and confirm a published
tool answers. Agree RPO/RTO before production. The encryption key lives in the secret
manager that injects the environment; losing it makes stored credentials unreadable.

## Upgrading

Releases ship forward Alembic migrations. Stop writes, take a dump, then run:

```powershell
cd backend
uv run --frozen alembic upgrade head
```

with `DATABASE_URL` pointing at the target database. The current head is `e5b1c3d7f902`.
The Hub checks the revision at startup and refuses to serve an older migrated database,
naming this command.

`e5b1c3d7f902` adds OpenAI-compatible model providers (keys stored encrypted) and allows chat
model names up to 120 characters. Downgrading drops the providers and moves apps that used one
back to Claude.

`c7f2a9d4e810` adds per-app tool switches and Hub chat settings. It only creates tables;
downgrading drops them (every tool is on again and chat settings are lost). Backups include
both. Conversations are never stored, so there is nothing else to back up for the chat.

`a41d7e6c9b20` adds skills, per-app memory settings and encrypted user memories. It only
creates tables; downgrading drops them. Backups include skills and memory settings, never
user memories, and restoring a backup deletes the memories of the apps it replaces.

`5c2e8d1f4a7b` (0.2) removes the unused placeholder tables (MCP profiles and links, skills,
approvals, jobs, artifacts, OpenAPI imports, command executions). It adds tool templates,
report settings and client key permissions, and turns `validated`/`approved` tools into
drafts. Published tools stay published and keep their test fingerprints. Downgrading
recreates the placeholder tables, re-links published read tools to a default profile, and
disables report and write tools (which 0.1 cannot run).

## Rolling back

Prefer restoring the pre-upgrade dump with the previous release. `alembic downgrade` is
tested on populated SQLite databases, but some steps refuse to run when the data cannot be
represented in the older schema. Never delete data just to force a downgrade.
`alembic downgrade base` drops every table and is only for disposable CI databases.

## Operational rollback

Pausing an app, disabling a data source or a tool, or revoking a key takes effect on the
next tool call, with no restart.
