# Docker deployment through aaPanel

Use this controller for an existing Docker Compose installation. The systemd
controller described in `DEPLOY_AAPANEL_OTOMATIS.md` manages a different runtime.
Installing repository files alone does not enable automatic deployment.

## Release behavior

After a push to `main`, CI checks the backend, frontend, dependencies, Docker
application startup, and a real Docker deployment/rollback on a disposable stack.
Only then can the existing guarded SSH workflow deliver the tested commit.
The environment remains `aapanel-production`, deployment is serialized, and
superseded main commits are skipped.

The Docker controller accepts `status`, `upload <commit>`,
`upload-images <commit> <image-sha256>` and `deploy-images <commit> <source-sha256> <image-sha256>`.
Its protocol is `prebuilt-v1`; the previous server-build command is rejected.
The source uses the bounded, allowlisted archive format of the systemd controller.
The application checkout is never reset or cleaned.

Before changing running services, the controller:

1. Checks that the configured containers belong to the expected Compose project
   and are healthy. Configuration in the frozen Compose file must match their
   effective environment.
2. Requires both the database and the running backend to match the new schema.
   It never executes migrations or application bootstrap during automatic deployment.
3. Imports the exact backend and edge images built and tested on GitHub, delivered
   through the existing pinned SSH connection. No registry credential is needed.
   Image IDs, commit/schema labels, platform, archive members, checksums and sizes
   are validated. No build, dependency installation or compilation runs on the server.
4. Creates a private PostgreSQL custom-format backup and verifies its table of
   contents with `pg_restore --list`. A successful archive check is not a full
   restore rehearsal; rehearse restoration separately before the first cutover.
5. Checks protected-file hashes and unrelated container IDs again.

Activation runs Compose with `--no-deps --no-build` for `backend edge` only.
Existing network memberships attached manually to those containers are restored
after recreation and rollback. The controller connects only to the previously
recorded network IDs; it does not create networks or add new memberships.
PostgreSQL, existing secret volumes, reference applications and other projects
are outside the activation command. Health failure restores the previous image
IDs using the same schema. A database restore is never automatic.

After activation, storage mounts, published ports, network IDs and effective
environment and restart policies must match the previous containers. All three
main services must use `unless-stopped` before deployment can proceed. Protected files and unrelated
container IDs must remain unchanged. A failure triggers application rollback.
The previous Compose document, candidate document, backup and successful release
state stay on the server with private permissions. They may contain credentials
and must never be uploaded as CI artifacts.

Success also requires valid HTTPS responses through the configured public domain:
`/ready`, `/login`, and `/release-version.json` containing the new commit. An
unreachable domain, wrong release marker, or unhealthy container triggers rollback.
The public domain must already work before a release can start. Certificate checks
are never disabled. A private `probe_ca` file is available for isolated CI certificates.

Uploads/imports require at least 4 GiB free disk and 1 GiB available RAM. Imports
also reserve twice the expanded archive size plus 2 GiB. Compressed image archives
are limited to 512 MiB and expanded content to 2 GiB. Imports still consume disk
I/O and CPU; these safeguards reduce load rather than guarantee uninterrupted service.

## Installation prerequisites

Before enabling the workflow, record the actual project name, container names,
database role/name, mounts, ports, network IDs and image IDs. Review configuration
drift between the checkout and running containers. Do not resolve that drift by
blindly applying the checkout's Compose file.

Create a root-owned deployment directory outside the application checkout with
`shared/backups`, `incoming`, and `releases`. Its directories must not be writable
by other users. Create an empty root-owned `shared/hub.env` marker with mode `0600`.
It contains no application credentials; actual secrets remain in existing volumes.

Store a reviewed, fully resolved baseline Compose JSON in `shared/baseline.json`
with mode `0600`. Its backend/edge settings must describe the running containers.
Keep the original project, volume names, network names, bind paths and loopback
ports. Resolving Compose may include secrets: capture stdout directly to a private
file and do not print it or attach it to an issue.

Install `deploy.py`, `docker_deploy.py`, and `image_archive.py` together in a root-owned directory
outside the releases. Use a root-owned mode-`0600` configuration based on
`deploy/aapanel/docker.example.json`. Adapt every path and container identifier.
Protect the existing environment, Compose file, and secret-volume environment
file using `protected_files`.

Use a dedicated SSH key restricted to a root-owned forced-command wrapper that
invokes the installed Docker controller with its fixed configuration path.
Disable PTY, port forwarding, agent forwarding, X11 forwarding, and user RC for
that key. Do not grant an unrestricted shell or membership of the Docker group.
Review this persistent server access before adding the key.

Configure the existing GitHub environment secrets `AAPANEL_SSH_HOST`,
`AAPANEL_SSH_USER`, `AAPANEL_SSH_PRIVATE_KEY`, and `AAPANEL_SSH_KNOWN_HOSTS`.
Pin the host key verified through the existing authenticated panel session;
do not disable SSH host verification. Set the optional `AAPANEL_SSH_PORT` variable
if needed. Keep `AAPANEL_DEPLOY_ENABLED` unset until the first cutover and recovery
checks succeed.

### One-time transition from server builds

Keep `AAPANEL_DEPLOY_ENABLED=false` throughout preparation. Preserve the installed
controller/configuration before replacing any files. Set and verify
`restart: unless-stopped` for backend, edge and PostgreSQL in both the live runtime
and the server-owned Compose document. Do not change one-shot init/ready services.

Run the reviewed `prepare_prebuilt.py CONFIG_PATH HTTPS_ORIGIN` as the operator,
not through the deployment key. It makes a private backup, copies existing Nginx
configuration, certificates and cached assets **within the server**, and recreates
only the edge using its existing image. The copied paths are mounted read-only:
`shared/edge-config/nginx.conf`, `shared/edge-config/certs`, and
`shared/frontend-assets`. It checks the public site, unchanged backend/database
and other container IDs, and all original protected-file hashes. Failure restores
the previous edge configuration. No private server image or TLS material goes to CI.

Check that the restricted key reports protocol `prebuilt-v1`. Only enable automatic
deployment after the isolated Docker integration job and the first controlled
prebuilt deployment succeed. The installed controller is deliberately server-owned;
pushing repository changes does not replace this privileged controller automatically.

## First cutover and later schema changes

An installation on an older schema intentionally cannot deploy automatically.
Review the pending migrations and rehearse the complete upgrade and restore on
an isolated server-local database copy, keeping credentials and copied records
off CI. Check preservation of existing accounts, connector settings and secrets.

The first cutover requires a controlled maintenance window: stop Hub writes,
take and restore-test a fresh backup, apply the reviewed migrations, activate the
reviewed images, and verify readiness and existing functionality before reopening
traffic. Do not restart schema-incompatible old code or restore a database after
new production writes. Establish the successful image/schema baseline first.

Future schema changes stop the automated controller for the same operator
procedure. Ordinary code/frontend releases on that baseline can then deploy
automatically. This does not change a development-mode installation into a
production-safe one: use the production requirements in `DEPLOY.md`, including
authenticated shared Redis and the appropriate egress policy.

## Verification and retention

Run `python -m unittest discover -s deploy/aapanel/tests -v` for the controller
boundary tests. POSIX-only filesystem tests run in Linux CI. The
`docker-deploy-smoke` CI job additionally builds a uniquely named disposable
stack and verifies a real release, backup, preserved database administrator
records, stable volume/container identities, and rollback after an injected
backend startup failure. It refuses execution outside GitHub CI.

Keep enough disk space for build layers, previous images and database backups.
The controller does not prune images, delete volumes or remove unrelated Docker
resources. Review retention separately and retain at least the active and last
known-good images plus a restore-tested database backup.
