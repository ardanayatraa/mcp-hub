#!/usr/bin/env python3
"""Server-owned aaPanel release controller. Install outside the Git checkout."""

import contextlib
import gzip
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import uuid
from pathlib import Path, PurePosixPath

SHA = re.compile(r"[a-f0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_EXPANDED = 250 * 1024 * 1024
MAX_TAR_BYTES = MAX_EXPANDED + 16 * 1024 * 1024


class DeploymentError(RuntimeError):
    pass


class BoundedTarReader:
    def __init__(self, file):
        self.file = file

    def read(self, size=-1):
        if size < 0 or size > 16*1024**2:
            raise DeploymentError("TAR_METADATA_TOO_LARGE")
        return self.file.read(size)

    def __getattr__(self, name):
        return getattr(self.file, name)


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def atomic_json(path, value):
    temporary = path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    try:
        with temporary.open("x") as handle:
            os.chmod(temporary, 0o600)
            json.dump(value, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def locked(path):
    import fcntl
    with path.open("a") as handle:
        os.chmod(path, 0o600)
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeploymentError("DEPLOYMENT_BUSY") from None
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def load_config(path):
    file = Path(path)
    info = file.stat()
    if file.is_symlink() or info.st_mode & 0o022 or info.st_uid != 0:
        raise DeploymentError("DEPLOY_CONFIG_MUST_BE_ROOT_OWNED_AND_NOT_WRITABLE_BY_GROUP_OR_OTHERS")
    data = json.loads(file.read_text())
    required = {"base", "service", "python", "uv", "pg_dump", "health_url", "health_host"}
    if set(data) != required or not all(isinstance(value, str) for value in data.values()):
        raise DeploymentError("INVALID_DEPLOY_CONFIG")
    if not re.fullmatch(r"[a-zA-Z0-9_-]+\.service", data["service"]):
        raise DeploymentError("INVALID_SERVICE")
    if not re.fullmatch(r"http://127\.0\.0\.1:[0-9]{2,5}/ready", data["health_url"]):
        raise DeploymentError("PROBE_MUST_USE_LOCAL_LOOPBACK")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]{1,5})?", data["health_host"]):
        raise DeploymentError("INVALID_HEALTH_HOST")
    for key in ("base", "python", "uv", "pg_dump"):
        if not Path(data[key]).is_absolute():
            raise DeploymentError("ABSOLUTE_PATHS_REQUIRED")
    return data


class SystemRuntime:
    def __init__(self, config):
        self.config = config

    def run(self, command, cwd, env=None, timeout=900):
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, timeout=timeout)
        if result.returncode:
            raise DeploymentError("SERVER_COMMAND_FAILED")
        return result.stdout

    def prepare(self, release):
        environment = os.environ.copy()
        environment.update(UV_PYTHON_DOWNLOADS="never", UV_NO_MANAGED_PYTHON="1",
                           UV_CACHE_DIR=str(release.parent.parent/"shared"/"uv-cache"))
        self.run([self.config["uv"], "sync", "--frozen", "--no-dev", "--no-install-project",
                  "--python", self.config["python"]], release/"backend", env=environment)

    def helper(self, release, *arguments):
        environment = os.environ.copy()
        # Configuration comes from the server-owned .env, not SSH's inherited env.
        environment["PYTHONPATH"] = str(release/"backend")
        raw = self.run([str(release/"backend/.venv/bin/python"), str(release/"deploy/aapanel/runtime.py"), *arguments],
                       release/"backend", env=environment)
        try:
            return json.loads(raw)
        except (ValueError, UnicodeError):
            raise DeploymentError("INVALID_RUNTIME_RESPONSE") from None

    def inspect(self, release):
        return self.helper(release, "inspect")

    def backup(self, release, destination):
        self.helper(release, "backup", self.config["pg_dump"], str(destination))

    def restart(self):
        self.run(["/usr/bin/sudo", "-n", "/usr/bin/systemctl", "restart", self.config["service"]], Path("/"), timeout=90)

    def ready(self):
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPHandler())
        deadline = time.monotonic()+45
        while time.monotonic() < deadline:
            try:
                request = urllib.request.Request(self.config["health_url"], headers={"Host": self.config["health_host"]})
                with opener.open(request, timeout=2) as response:
                    if response.status == 200 and json.loads(response.read(1024)) == {"status": "ready"}:
                        return True
            except Exception:
                pass
            time.sleep(1)
        return False


class Manager:
    def __init__(self, config, runtime=None):
        self.config = config
        self.base = Path(config["base"]).resolve(strict=True)
        self.shared = self.base/"shared"
        self.releases = self.base/"releases"
        self.incoming = self.base/"incoming"
        for directory in (self.shared, self.releases, self.incoming, self.shared/"backups", self.shared/"frontend-assets"):
            if directory.is_symlink() or not directory.is_dir():
                raise DeploymentError("SERVER_LAYOUT_NOT_READY")
        self.environment = self.shared/"hub.env"
        if self.environment.is_symlink() or not self.environment.is_file() or self.environment.stat().st_mode & 0o027:
            raise DeploymentError("SERVER_ENV_MUST_EXIST_AND_BE_PRIVATE")
        self.runtime = runtime or SystemRuntime(config)

    def archive(self, commit):
        if not SHA.fullmatch(commit):
            raise DeploymentError("INVALID_COMMIT")
        file = self.incoming/(commit+".tar.gz")
        if file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_ARCHIVE:
            raise DeploymentError("INVALID_RELEASE_ARCHIVE")
        return file

    def upload(self, commit, stream):
        if not SHA.fullmatch(commit):
            raise DeploymentError("INVALID_COMMIT")
        temporary = self.incoming/("."+commit+"."+uuid.uuid4().hex)
        target = self.incoming/(commit+".tar.gz")
        size = 0
        try:
            with temporary.open("xb") as output:
                os.chmod(temporary, 0o600)
                while chunk := stream.read(65536):
                    size += len(chunk)
                    if size > MAX_ARCHIVE:
                        raise DeploymentError("ARCHIVE_TOO_LARGE")
                    output.write(chunk)
                output.flush()
                os.fsync(output.fileno())
            if target.exists() or target.is_symlink():
                if target.is_symlink() or digest(target) != digest(temporary):
                    raise DeploymentError("A_DIFFERENT_ARCHIVE_ALREADY_EXISTS_FOR_COMMIT")
            else:
                os.link(temporary, target)  # no overwrite, including concurrent upload
        finally:
            temporary.unlink(missing_ok=True)
        return {"status": "uploaded", "commit": commit}

    def unpack(self, commit, checksum):
        file = self.archive(commit)
        if not DIGEST.fullmatch(checksum) or digest(file) != checksum:
            raise DeploymentError("ARCHIVE_CHECKSUM_MISMATCH")
        if shutil.disk_usage(self.base).free < 2*1024**3:
            raise DeploymentError("AT_LEAST_2_GIB_FREE_DISK_REQUIRED")
        with tempfile.TemporaryFile(dir=self.incoming) as expanded:
            size = 0
            with gzip.open(file, "rb") as compressed:
                while chunk := compressed.read(65536):
                    size += len(chunk)
                    if size > MAX_TAR_BYTES:
                        raise DeploymentError("EXPANDED_ARCHIVE_TOO_LARGE")
                    expanded.write(chunk)
            expanded.seek(0)
            payloads = self.read_tar(BoundedTarReader(expanded))
        return self.install_payloads(commit, payloads)

    def read_tar(self, file):
        payloads = {}
        total = 0
        with tarfile.open(fileobj=file, mode="r:") as archive:
            for member in archive:
                name = PurePosixPath(member.name)
                allowed = (member.name == "release.json" or member.name in {
                    "backend/pyproject.toml", "backend/uv.lock", "backend/alembic.ini", "deploy/aapanel/runtime.py"}
                    or member.name.startswith(("backend/app/", "frontend/dist/")))
                if (not member.isfile() or not allowed or str(name) != member.name or "\\" in member.name
                        or name.is_absolute() or any(part.startswith(".") for part in name.parts)
                        or name.suffix.lower() in {".env", ".key", ".pem", ".log", ".db", ".sqlite", ".sqlite3", ".pyc"}
                        or any(part in {"storage", "node_modules", "__pycache__"} for part in name.parts)
                        or member.name in payloads or member.size > 16*1024**2):
                    raise DeploymentError("UNSAFE_ARCHIVE_MEMBER")
                total += member.size
                if len(payloads) >= 10000 or total > MAX_EXPANDED:
                    raise DeploymentError("EXPANDED_ARCHIVE_TOO_LARGE")
                payloads[member.name] = archive.extractfile(member).read()
        return payloads

    def install_payloads(self, commit, payloads):
        manifest = json.loads(payloads.pop("release.json", b"{}"))
        expected = {name: hashlib.sha256(data).hexdigest() for name, data in payloads.items()}
        if manifest != {"format": 1, "commit": commit, "files": expected} or not {
            "backend/app/main.py", "backend/uv.lock", "frontend/dist/index.html", "deploy/aapanel/runtime.py"} <= payloads.keys():
            raise DeploymentError("RELEASE_MANIFEST_MISMATCH")
        release = self.releases/commit
        if release.is_symlink():
            raise DeploymentError("RELEASE_CANNOT_BE_A_SYMLINK")
        release.mkdir(mode=0o755, exist_ok=True)
        os.chmod(release, 0o755)
        for name, data in payloads.items():
            target = release/name
            parent = target.parent
            while parent != release:
                if parent.is_symlink():
                    raise DeploymentError("RELEASE_PATH_IS_A_SYMLINK")
                parent = parent.parent
            target.parent.mkdir(parents=True, exist_ok=True)
            if name.startswith("frontend/"):
                public = target.parent
                while public != release:
                    os.chmod(public, 0o755)
                    public = public.parent
            if target.is_symlink():
                raise DeploymentError("RELEASE_FILE_IS_A_SYMLINK")
            if target.exists():
                if digest(target) != expected[name]:
                    raise DeploymentError("RELEASE_FILES_HAVE_CHANGED")
            else:
                with target.open("xb") as output:
                    output.write(data)
                os.chmod(target, 0o644 if name.startswith("frontend/") else 0o640)
        metadata = release/"release.json"
        if metadata.is_symlink():
            raise DeploymentError("RELEASE_METADATA_IS_A_SYMLINK")
        if not metadata.exists():
            metadata.write_text(json.dumps(manifest, sort_keys=True))
            os.chmod(metadata, 0o644)
        elif json.loads(metadata.read_text()) != manifest:
            raise DeploymentError("RELEASE_METADATA_HAS_CHANGED")
        link = release/"backend/.env"
        if link.is_symlink():
            if link.resolve() != self.environment:
                raise DeploymentError("ENV_LINK_TARGET_CHANGED")
        elif link.exists():
            raise DeploymentError("RELEASE_HAS_ITS_OWN_ENV")
        else:
            link.symlink_to(self.environment)
        return release

    def current(self):
        pointer = self.base/"current"
        if not pointer.is_symlink():
            if pointer.exists():
                raise DeploymentError("CURRENT_MUST_BE_A_RELEASE_SYMLINK")
            return None
        target = pointer.resolve(strict=True)
        if target.parent != self.releases or not SHA.fullmatch(target.name) or not (target/"release.json").is_file():
            raise DeploymentError("INVALID_CURRENT_RELEASE")
        return target

    def activate(self, release):
        temporary = self.base/(".current-"+uuid.uuid4().hex)
        try:
            temporary.symlink_to(release, target_is_directory=True)
            os.replace(temporary, self.base/"current")
        finally:
            temporary.unlink(missing_ok=True)

    def publish_assets(self, release):
        for source in (release/"frontend/dist/assets").rglob("*"):
            if source.is_symlink():
                raise DeploymentError("ASSET_SOURCE_IS_A_SYMLINK")
            if source.is_file():
                target = self.shared/"frontend-assets"/source.relative_to(release/"frontend/dist/assets")
                parent = target.parent
                while parent != self.shared/"frontend-assets":
                    if parent.is_symlink():
                        raise DeploymentError("ASSET_DIRECTORY_IS_A_SYMLINK")
                    parent = parent.parent
                target.parent.mkdir(parents=True, exist_ok=True)
                parent = target.parent
                while parent != self.shared/"frontend-assets":
                    os.chmod(parent, 0o755)
                    parent = parent.parent
                if target.is_symlink():
                    raise DeploymentError("ASSET_IS_A_SYMLINK")
                if target.exists():
                    if digest(source) != digest(target):
                        raise DeploymentError("IMMUTABLE_ASSET_COLLISION")
                else:
                    with source.open("rb") as incoming, target.open("xb") as output:
                        shutil.copyfileobj(incoming, output)
                    os.chmod(target, 0o644)

    def deploy(self, commit, checksum, schema_cutover=False):
        with locked(self.shared/"deploy.lock"):
            before = digest(self.environment)
            previous = self.current()
            release = self.unpack(commit, checksum)
            self.runtime.prepare(release)
            schema = self.runtime.inspect(release)
            if schema.get("current") != [schema.get("target")] or not schema.get("target"):
                raise DeploymentError("SCHEMA_CHANGE_REQUIRES_REVIEW_NO_DATABASE_CHANGES_MADE")
            compatible = True
            if previous:
                activation = previous/"activation.json"
                compatible = not activation.is_symlink() and activation.is_file() and json.loads(activation.read_text()).get("schema") == schema["target"]
                if not compatible and not schema_cutover:
                    raise DeploymentError("SCHEMA_COMPATIBILITY_REVIEW_REQUIRED_PREVIOUS_RELEASE_UNCHANGED")
            # Preserve metadata, credentials and all application settings before switching.
            backup = self.shared/"backups"/(time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())+"-"+commit[:12]+".dump")
            if backup.exists():
                backup = backup.with_name(backup.stem+"-"+uuid.uuid4().hex[:8]+".dump")
            self.runtime.backup(release, backup)
            self.publish_assets(release)
            if digest(self.environment) != before:
                raise DeploymentError("SERVER_ENV_CHANGED_DEPLOYMENT_ABORTED")
            self.activate(release)
            try:
                self.runtime.restart()
                if not self.runtime.ready():
                    raise DeploymentError("READINESS_FAILED")
            except Exception:
                if previous and not compatible:
                    raise DeploymentError("MIGRATED_RELEASE_FAILED_OPERATOR_RECOVERY_REQUIRED_NO_DATABASE_DOWNGRADE") from None
                if previous:
                    self.activate(previous)
                    self.runtime.restart()
                    if not self.runtime.ready():
                        raise DeploymentError("ROLLBACK_READINESS_FAILED_MANUAL_RECOVERY_REQUIRED") from None
                raise DeploymentError("RELEASE_FAILED_PREVIOUS_RELEASE_RESTORED" if previous else "FIRST_RELEASE_FAILED") from None
            if digest(self.environment) != before:
                raise DeploymentError("SERVER_ENV_CHANGED_DURING_DEPLOYMENT")
            atomic_json(release/"activation.json", {"schema": schema["target"]})
            atomic_json(self.shared/"deploy-state.json", {"current": commit, "previous": previous.name if previous else None,
                        "schema": schema["target"], "environment_unchanged": True})
            return {"status": "deployed", "commit": commit, "environment_unchanged": True}


def main():
    if os.name != "posix" or sys.version_info < (3, 12):
        raise DeploymentError("LINUX_AND_PYTHON_3_12_REQUIRED")
    os.umask(0o027)
    if len(sys.argv) not in {2, 5}:
        raise DeploymentError("CONFIG_PATH_REQUIRED")
    manager = Manager(load_config(sys.argv[1]))
    if len(sys.argv) == 5:
        if sys.argv[2] != "--schema-cutover" or os.environ.get("SSH_ORIGINAL_COMMAND") or not sys.stdin.isatty():
            raise DeploymentError("SCHEMA_CUTOVER_REQUIRES_AN_OPERATOR_TERMINAL")
        return manager.deploy(sys.argv[3], sys.argv[4], schema_cutover=True)
    command = shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", "status"))
    if command == ["status"]:
        active = manager.current()
        return {"status": "configured", "current": active.name if active else None}
    if len(command) == 2 and command[0] == "upload":
        return manager.upload(command[1], sys.stdin.buffer)
    if len(command) == 3 and command[0] == "deploy":
        return manager.deploy(command[1], command[2])
    raise DeploymentError("COMMAND_NOT_ALLOWED")


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except DeploymentError as error:
        print(json.dumps({"status": "failed", "code": str(error)}))
        sys.exit(1)
    except Exception:
        print(json.dumps({"status": "failed", "code": "DEPLOYMENT_FAILED_CHECK_SERVER_STATE"}))
        sys.exit(1)
