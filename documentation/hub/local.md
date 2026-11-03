# Run the Hub locally

Install Python 3.12, uv, Node.js 22, and pnpm. Use a separate environment and ports from services that are already running.

```bash
git clone https://github.com/ardanayatraa/mcp-hub.git
cd mcp-hub
```

## Windows launcher

```powershell
.\dev.ps1
```

Alternatively, run `dev.cmd`. The launcher installs missing dependencies and creates `dev.env` with random keys on first use, then runs migrations, bootstraps the administrator, and starts the API and admin UI. Keep the generated credentials private.

Ports follow `HUB_PORT` and `UI_PORT` in the environment file. The launcher may stop a recognized older Hub or UI process on those ports. Use different ports for parallel instances. Ctrl+C stops the instance you started.

## Run components manually

Prepare the development configuration described in the [repository README](https://github.com/ardanayatraa/mcp-hub#quick-start-local-development): a SQLite database, encryption key, session signing key, initial administrator password, allowed hosts and origins, and public URLs matching your chosen ports.

From `backend`:

```bash
uv sync --frozen --group dev
uv run --frozen alembic upgrade head
uv run --frozen python -m app.bootstrap
uv run --frozen uvicorn app.main:app --host 127.0.0.1 --port 18080
```

From `frontend` in another terminal, point the proxy at the same backend port:

=== "PowerShell"

    ```powershell
    $env:HUB_API_TARGET = "http://127.0.0.1:18080"
    pnpm install --frozen-lockfile
    pnpm dev --host 127.0.0.1 --port 15180
    ```

=== "Bash"

    ```bash
    export HUB_API_TARGET=http://127.0.0.1:18080
    pnpm install --frozen-lockfile
    pnpm dev --host 127.0.0.1 --port 15180
    ```

Keep the frontend proxy, allowed origins, and MCP URL consistent with your ports. Use the launcher when you want it to manage local configuration automatically.

## Verify the installation

Sign in to the admin UI, check `/health` and `/ready`, register a test source, and create a read-only client key. Verify the catalog with a synthetic actor before enabling business access.

Local HTTP, loopback egress, and SQLite are development options. Public services should follow the [production guide](operations.md).
