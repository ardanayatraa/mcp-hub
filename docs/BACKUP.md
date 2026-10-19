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

Restores need the same `SECRET_ENCRYPTION_KEY`; with another key, stored credentials
cannot be decrypted. The request limit is 1 MB; use a database dump for larger states.

**Purge** (`POST /operations/purge`) removes activity, health checks, test runs and
sessions older than `AUDIT_RETENTION_DAYS` (default 90). Schedule it together with
off-host database dumps. A purged passing test means that tool needs a new test before its
next publish.

## Database dumps

For PostgreSQL, schedule `pg_dump` and keep dumps off the host with restricted access. A
restore drill: stop the Hub, restore the dump, start it, sign in, and confirm a published
tool answers. Agree RPO/RTO before production. The encryption key lives in the secret
manager that injects the environment; losing it makes stored credentials unreadable.

## Upgrading

Stop writes, take a dump, then run:

```powershell
cd hub
npm run migrate
```

with `DATABASE_URL` pointing at the target database. An empty database gets the whole
schema; an older one is upgraded to the current revision, `f3a8d2c6b1e4`. SQLite gets a
`.pre-node-*.bak` copy first; PostgreSQL relies on your dump. The revision ids are the
Python edition's Alembic ids (the `mcp-py` branch), so either edition can open the
database. The Hub checks the revision and answers `503 NOT_READY` until it is current.
Containers set `HUB_AUTO_MIGRATE=true` to run this on start.

The notes below describe what each revision changed.

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

Restore the pre-upgrade dump with the previous release. `npm run migrate` only moves
forward. Never delete data just to force a downgrade.

## Operational rollback

Pausing an app, disabling a data source or a tool, or revoking a key takes effect on the
next tool call, with no restart.
