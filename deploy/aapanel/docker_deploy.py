#!/usr/bin/env python3
"""Restricted Docker release controller, installed outside the application checkout.

The existing Compose document, environment, database and volumes stay server-owned.
Database migrations are an operator task; automated releases require an unchanged schema.
"""

import ast
import copy
import hashlib
import json
import os
import re
import shlex
import shutil
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from image_archive import MAX_COMPRESSED, inspect_archive

from deploy import DIGEST, SHA, DeploymentError, Manager, atomic_json, digest, locked


def fingerprint(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            result.update(block)
    return result.hexdigest()


def private_file(path):
    file = Path(path)
    info = file.stat()
    if file.is_symlink() or not file.is_file() or info.st_uid != 0 or info.st_mode & 0o077:
        raise DeploymentError("ROOT_OWNED_PRIVATE_FILE_REQUIRED")
    return file


def load_config(path):
    data = json.loads(private_file(path).read_text())
    required = {"base", "project", "compose", "backend", "edge", "postgres", "database", "database_user", "protected_files", "public_url"}
    if not required <= data.keys() or set(data) - required - {"probe_ca"} or not isinstance(data["protected_files"], list) or not data["protected_files"]:
        raise DeploymentError("INVALID_DOCKER_CONFIG")
    url = urllib.parse.urlsplit(data['public_url'])
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.path not in {'', '/'} or url.query or url.fragment:
        raise DeploymentError('PUBLIC_HTTPS_ORIGIN_REQUIRED')
    if data.get('probe_ca'):
        private_file(data['probe_ca'])
    for key in ("project", "backend", "edge", "postgres", "database", "database_user"):
        if not isinstance(data[key], str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,100}", data[key]):
            raise DeploymentError("INVALID_DOCKER_IDENTIFIER")
    for value in [data["base"], data["compose"], *data["protected_files"]]:
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise DeploymentError("ABSOLUTE_SERVER_PATH_REQUIRED")
    for file in (data["compose"], *data["protected_files"]):
        path = Path(file)
        if path.is_symlink() or not path.is_file():
            raise DeploymentError("SERVER_FILE_MISSING_OR_SYMLINK")
    return data


def target_schema(release):
    tree = ast.parse((release/"backend/app/persistence/__init__.py").read_text())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SCHEMA_REVISION" for t in node.targets):
            value = ast.literal_eval(node.value)
            if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{12}", value):
                return value
    raise DeploymentError("INVALID_RELEASE_SCHEMA")


def start_command(command):
    """Retain server-owned secret loading, while removing automatic migration/bootstrap."""
    if (not isinstance(command, list) or len(command) != 3 or command[:2] != ["sh", "-c"]
            or not command[2].lstrip().startswith(". /secrets/env &&")
            or "exec uvicorn app.main:app " not in command[2]
            or (command[2].count("alembic upgrade head &&"), command[2].count("python -m app.bootstrap &&")) not in {(0, 0), (1, 1)}):
        raise DeploymentError("REVIEW_SERVER_START_COMMAND")
    return ["sh", "-c", command[2].replace("alembic upgrade head &&", "").replace("python -m app.bootstrap &&", "")]


def release_compose(baseline, project, images):
    document = copy.deepcopy(baseline)
    if document.get("name") != project or not {"backend", "edge"} <= document.get("services", {}).keys():
        raise DeploymentError("COMPOSE_PROJECT_MISMATCH")
    for service, image in images.items():
        if service not in {"backend", "edge"} or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise DeploymentError("INVALID_IMAGE_ID")
        document["services"][service]["image"] = image
        document["services"][service].pop("build", None)
    document["services"]["backend"]["command"] = start_command(document["services"]["backend"]["command"])
    return document


def runtime_boundary(container):
    """Addresses may change on recreation; storage, exposure and settings may not."""
    return {
        "mounts": sorted((m["Type"], m.get("Name", ""), m["Source"], m["Destination"], m["RW"]) for m in container.get("Mounts", [])),
        "ports": container["HostConfig"].get("PortBindings"),
        "networks": {name: network["NetworkID"] for name, network in container["NetworkSettings"]["Networks"].items()},
        "environment": sorted(container["Config"].get("Env", [])),
        "restart": container["HostConfig"].get("RestartPolicy", {"Name": "no", "MaximumRetryCount": 0}),
    }


def compose_literals(value):
    """Compose interpolates all scalar values, including frozen shell commands."""
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, list):
        return [compose_literals(item) for item in value]
    if isinstance(value, dict):
        return {key: compose_literals(item) for key, item in value.items()}
    return value


class DockerRuntime:
    def __init__(self, config):
        self.config = config
        self.base = Path(config["base"])

    def run(self, command, *, input=None, timeout=900):
        result = subprocess.run(command, input=input, capture_output=True, timeout=timeout)
        if result.returncode:
            # Docker/Compose output can contain environment values. Never forward it to CI.
            raise DeploymentError("DOCKER_OPERATION_FAILED_CHECK_SERVER")
        return result.stdout

    def inspect(self, container):
        return json.loads(self.run(["docker", "inspect", container]))[0]

    def inventory(self):
        ids = self.run(["docker", "ps", "-aq"]).decode().split()
        if not ids:
            raise DeploymentError("EXISTING_CONTAINERS_REQUIRED")
        containers = json.loads(self.run(["docker", "inspect", *ids]))
        return {item["Name"].lstrip("/"): item["Id"] for item in containers}

    def schema(self):
        return self.run(["docker", "exec", self.config["postgres"], "psql", "-U", self.config["database_user"],
                         "-d", self.config["database"], "-Atc", "select version_num from alembic_version"]).decode().strip()

    def snapshot(self):
        state = self.base/"shared/docker-state.json"
        compose = self.config["compose"]
        if state.exists():
            compose = str(private_file(json.loads(private_file(state).read_text())["compose"]))
        document = json.loads(self.run(["docker", "compose", "--project-name", self.config["project"],
                                       "--file", compose, "config", "--format", "json"]))
        containers = {key: self.inspect(self.config[key]) for key in ("backend", "edge", "postgres")}
        for key, item in containers.items():
            labels = item["Config"].get("Labels", {})
            if labels.get("com.docker.compose.project") != self.config["project"] or labels.get("com.docker.compose.service") != key:
                raise DeploymentError("CONTAINER_PROJECT_MISMATCH")
            if item["State"].get("Health", {}).get("Status") != "healthy":
                raise DeploymentError("EXISTING_STACK_NOT_HEALTHY")
            if item['HostConfig']['RestartPolicy']['Name'] != 'unless-stopped' or document['services'][key].get('restart') != 'unless-stopped':
                raise DeploymentError('RESTART_RECOVERY_NOT_CONFIGURED')
        # These mounts preserve server-only TLS/configuration across clean CI images.
        expected_mounts = {
            '/etc/nginx/nginx.conf': self.base/'shared/edge-config/nginx.conf',
            '/etc/nginx/certs': self.base/'shared/edge-config/certs',
            '/usr/share/nginx/html/assets': self.base/'shared/frontend-assets',
        }
        for target, source in expected_mounts.items():
            matches = [m for m in containers['edge']['Mounts'] if m['Destination'] == target]
            if len(matches) != 1 or matches[0]['Type'] != 'bind' or matches[0]['Source'] != str(source) or matches[0]['RW']:
                raise DeploymentError('SERVER_EDGE_MOUNTS_NOT_PREPARED')
        # Prevent an edited checkout from silently changing the live runtime configuration.
        for key in ("backend", "edge"):
            service = document["services"][key]
            if service.get("environment", {}) != dict(x.split("=", 1) for x in containers[key]["Config"].get("Env", []) if x.split("=", 1)[0] in service.get("environment", {})):
                raise DeploymentError("COMPOSE_ENVIRONMENT_DIFFERS_FROM_RUNNING_CONTAINER")
            configured = service.get("networks", {"default": {}})
            attached = containers[key]["NetworkSettings"]["Networks"]
            for name in configured:
                actual_name = document["networks"][name]["name"]
                if actual_name not in attached:
                    raise DeploymentError("COMPOSE_NETWORK_DIFFERS_FROM_RUNNING_CONTAINER")
            service["command"] = containers[key]["Config"]["Cmd"]
        previous = release_compose(document, self.config["project"], {k: containers[k]["Image"] for k in ("backend", "edge")})
        return previous, containers

    def backup(self, destination):
        with destination.open("xb") as output:
            os.chmod(destination, 0o600)
            result = subprocess.run(["docker", "exec", self.config["postgres"], "pg_dump", "-U", self.config["database_user"],
                                     "-d", self.config["database"], "--format=custom"], stdout=output, stderr=subprocess.PIPE, timeout=300)
            output.flush()
            os.fsync(output.fileno())
        if result.returncode or destination.stat().st_size < 5:
            raise DeploymentError("DATABASE_BACKUP_FAILED")
        with destination.open("rb") as incoming:
            result = subprocess.run(["docker", "exec", "-i", self.config["postgres"], "pg_restore", "--list"],
                                    stdin=incoming, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=60)
        if result.returncode:
            raise DeploymentError("DATABASE_BACKUP_VERIFICATION_FAILED")

    def preflight(self):
        # Fail before import/recreation when the shared host has little headroom.
        if shutil.disk_usage(self.base).free < 4*1024**3:
            raise DeploymentError('AT_LEAST_4_GIB_FREE_DISK_REQUIRED')
        available = next(int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith('MemAvailable:'))
        if available < 1024**3:
            raise DeploymentError('AT_LEAST_1_GIB_AVAILABLE_MEMORY_REQUIRED')

    def load_images(self, commit, checksum, schema):
        file = self.base/'incoming'/(commit+'.images.tar.gz')
        if not SHA.fullmatch(commit) or not DIGEST.fullmatch(checksum) or file.is_symlink() or not file.is_file() or file.stat().st_size > MAX_COMPRESSED or digest(file) != checksum:
            raise DeploymentError('INVALID_IMAGE_ARCHIVE_OR_CHECKSUM')
        images, expanded, configs = inspect_archive(file, commit, schema)
        self.preflight()
        if shutil.disk_usage(self.base).free < 2*expanded+2*1024**3:
            raise DeploymentError('INSUFFICIENT_IMAGE_IMPORT_DISK_HEADROOM')
        self.run(['docker', 'load', '--input', str(file)], timeout=600)
        for key, expected in images.items():
            actual = json.loads(self.run(['docker', 'image', 'inspect', 'mcp-hub-ci-'+key+':'+commit]))[0]
            # Classic storage identifies an image by config digest; containerd
            # may identify the same image by its manifest/index digest instead.
            # Verify runtime configuration and ordered content-addressed layers
            # in either store, then use the daemon's immutable local image ID.
            def normalized(config):
                return {k:v for k,v in config.items() if v not in (None,False,'',[],{})}
            config = configs[key]
            if (not re.fullmatch(r'sha256:[a-f0-9]{64}', actual['Id'])
                    or normalized(actual['Config']) != normalized(config['config'])
                    or actual['RootFS']['Layers'] != config['rootfs']['diff_ids']
                    or actual['Os'] != config['os'] or actual['Architecture'] != config['architecture']):
                raise DeploymentError('IMPORTED_IMAGE_CONTENT_MISMATCH')
            images[key] = actual['Id']
        return images

    def public_ready(self, commit=None):
        context = ssl.create_default_context(cafile=self.config.get('probe_ca'))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), urllib.request.HTTPSHandler(context=context))
        origin = self.config['public_url'].rstrip('/')
        def get(path):
            request = urllib.request.Request(origin+path, headers={'Cache-Control': 'no-cache', 'User-Agent': 'MCP-Hub-Deploy/1.0'})
            with opener.open(request, timeout=4) as response:
                if response.status != 200 or response.geturl().split('?', 1)[0] != (origin+path).split('?', 1)[0]:
                    raise ValueError('PUBLIC_PROBE_STATUS_OR_REDIRECT')
                return response.read(1024**2)
        try:
            if json.loads(get('/ready')) != {'status': 'ready'} or b'<title>MCP Hub</title>' not in get('/login'):
                return False
            return not commit or json.loads(get('/release-version.json?deployment='+commit)) == {'commit': commit}
        except (OSError, ValueError):
            return False

    def activate(self, file):
        self.run(["docker", "compose", "--project-name", self.config["project"], "--file", str(file),
                  "up", "--detach", "--no-deps", "--no-build", "backend", "edge"], timeout=180)

    def restore_networks(self, containers):
        # Docker's default bridge cannot be declared as a normal Compose network
        # with service aliases. Preserve memberships attached manually to the
        # existing Hub containers, without creating networks or granting new ones.
        for key in ("backend", "edge"):
            expected = containers[key]["NetworkSettings"]["Networks"]
            attached = self.inspect(self.config[key])["NetworkSettings"]["Networks"]
            if any(name not in expected or expected[name]["NetworkID"] != value["NetworkID"] for name, value in attached.items()):
                raise DeploymentError("UNEXPECTED_CONTAINER_NETWORK")
            for name, network in expected.items():
                if name not in attached:
                    self.run(["docker", "network", "connect", network["NetworkID"], self.config[key]])

    def ready(self, commit=None):
        deadline = time.monotonic()+90
        while time.monotonic() < deadline:
            try:
                states = [self.inspect(self.config[key])["State"] for key in ("backend", "edge")]
                if any(state.get("Status") in {"exited", "dead"} for state in states):
                    return False
                if all(state.get("Health", {}).get("Status") == "healthy" for state in states) and self.public_ready(commit):
                    return True
            except DeploymentError:
                pass
            time.sleep(2)
        return False


class DockerManager(Manager):
    def __init__(self, config, runtime=None):
        self.config = config
        self.base = Path(config["base"]).resolve(strict=True)
        self.shared, self.releases, self.incoming = (self.base/name for name in ("shared", "releases", "incoming"))
        for directory in (self.base, self.shared, self.releases, self.incoming, self.shared/"backups"):
            if (directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o022
                    or directory.stat().st_uid != 0):
                raise DeploymentError("PRIVATE_SERVER_LAYOUT_REQUIRED")
        # Only a private empty marker is linked into extracted releases; real secrets stay in Docker.
        self.environment = private_file(self.shared/"hub.env")
        if self.environment.stat().st_size:
            raise DeploymentError("DOCKER_ENV_MARKER_MUST_BE_EMPTY")
        self.runtime = runtime or DockerRuntime(config)

    def upload_images(self, commit, checksum, stream):
        if not SHA.fullmatch(commit) or not DIGEST.fullmatch(checksum):
            raise DeploymentError('INVALID_COMMIT_OR_IMAGE_CHECKSUM')
        with locked(self.shared/'deploy.lock'):
            self.runtime.preflight()
            temporary = self.incoming/('.images-'+uuid.uuid4().hex)
            target = self.incoming/(commit+'.images.tar.gz')
            try:
                size = 0
                with temporary.open('xb') as output:
                    os.chmod(temporary, 0o600)
                    while chunk := stream.read(65536):
                        size += len(chunk)
                        if size > MAX_COMPRESSED:
                            raise DeploymentError('COMPRESSED_IMAGE_ARCHIVE_TOO_LARGE')
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if digest(temporary) != checksum:
                    raise DeploymentError('INCOMPLETE_OR_CHANGED_IMAGE_UPLOAD')
                if target.exists() or target.is_symlink():
                    if target.is_symlink() or digest(target) != digest(temporary):
                        raise DeploymentError('DIFFERENT_IMAGE_ARCHIVE_ALREADY_UPLOADED')
                else:
                    os.link(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        return {'status': 'images_uploaded', 'commit': commit}

    def deploy(self, commit, checksum, image_checksum):
        with locked(self.shared/"deploy.lock"):
            self.runtime.preflight()
            protected = {file: fingerprint(file) for file in self.config["protected_files"]}
            before = self.runtime.inventory()
            previous, containers = self.runtime.snapshot()
            release = self.unpack(commit, checksum)
            schema = target_schema(release)
            if self.runtime.schema() != schema:
                raise DeploymentError("SCHEMA_CHANGE_REQUIRES_OPERATOR_REVIEW_NO_LIVE_CHANGES_MADE")
            live_schema = self.runtime.run(["docker", "exec", self.config["backend"], "python", "-c",
                                            "from app.persistence import SCHEMA_REVISION; print(SCHEMA_REVISION)"]).decode().strip()
            if live_schema != schema:
                raise DeploymentError("BASELINE_SCHEMA_DIFFERS_OPERATOR_CUTOVER_REQUIRED")
            if not self.runtime.public_ready():
                raise DeploymentError('PUBLIC_SITE_UNHEALTHY_NO_LIVE_CHANGES_MADE')
            images = self.runtime.load_images(commit, image_checksum, schema)
            self.publish_assets(release)
            candidate = release_compose(previous, self.config["project"], images)
            # previous is already normalized, so no migration/bootstrap commands remain.
            backup = self.shared/"backups"/(commit+"-"+uuid.uuid4().hex+".dump")
            self.runtime.backup(backup)
            transaction = commit+'-'+uuid.uuid4().hex
            previous_file, candidate_file = (self.shared/(transaction+suffix) for suffix in ("-previous.json", "-candidate.json"))
            atomic_json(previous_file, compose_literals(previous))
            atomic_json(candidate_file, compose_literals(candidate))
            self.assert_preserved(protected, before)
            if self.runtime.schema() != schema:
                raise DeploymentError("SCHEMA_CHANGED_DURING_BUILD")
            try:
                self.runtime.activate(candidate_file)
                self.runtime.restore_networks(containers)
                if not self.runtime.ready(commit):
                    raise DeploymentError("RELEASE_HEALTH_CHECK_FAILED")
                self.assert_preserved(protected, before, updating=True)
                for key in ("backend", "edge"):
                    if runtime_boundary(containers[key]) != runtime_boundary(self.runtime.inspect(self.config[key])):
                        raise DeploymentError("LIVE_RUNTIME_BOUNDARY_CHANGED")
            except Exception:
                self.runtime.activate(previous_file)
                self.runtime.restore_networks(containers)
                if not self.runtime.ready():
                    raise DeploymentError("ROLLBACK_FAILED_OPERATOR_RECOVERY_REQUIRED") from None
                raise DeploymentError("RELEASE_FAILED_PREVIOUS_IMAGES_RESTORED") from None
            atomic_json(self.shared/"docker-state.json", {"current": commit, "schema": schema,
                        "compose": str(candidate_file), "backup": str(backup), "images": images})
            return {"status": "deployed", "commit": commit, "protected_files_unchanged": True}

    def assert_preserved(self, protected, before, updating=False):
        if any(fingerprint(path) != expected for path, expected in protected.items()):
            raise DeploymentError("PROTECTED_SERVER_FILE_CHANGED")
        after = self.runtime.inventory()
        allowed = {self.config["backend"], self.config["edge"]} if updating else set()
        if {k: v for k, v in before.items() if k not in allowed} != {k: v for k, v in after.items() if k not in allowed}:
            raise DeploymentError("UNRELATED_CONTAINER_CHANGED")


def main():
    if os.name != "posix" or os.geteuid() != 0 or len(sys.argv) != 2:
        raise DeploymentError("ROOT_CONTROLLER_AND_CONFIG_REQUIRED")
    os.umask(0o077)
    manager = DockerManager(load_config(sys.argv[1]))
    command = shlex.split(os.environ.get("SSH_ORIGINAL_COMMAND", "status"))
    if command == ["status"]:
        state = manager.shared/"docker-state.json"
        return {"status": "configured", "protocol": "prebuilt-v1", "current": json.loads(private_file(state).read_text())["current"] if state.exists() else None}
    if len(command) == 2 and command[0] == "upload":
        return manager.upload(command[1], sys.stdin.buffer)
    if len(command) == 3 and command[0] == 'upload-images':
        return manager.upload_images(command[1], command[2], sys.stdin.buffer)
    if len(command) == 4 and command[0] == 'deploy-images':
        return manager.deploy(command[1], command[2], command[3])
    raise DeploymentError("COMMAND_NOT_ALLOWED")


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except DeploymentError as error:
        print(json.dumps({"status": "failed", "code": str(error)}))
        sys.exit(1)
    except Exception:
        print(json.dumps({"status": "failed", "code": "DOCKER_DEPLOYMENT_FAILED_CHECK_SERVER"}))
        sys.exit(1)
