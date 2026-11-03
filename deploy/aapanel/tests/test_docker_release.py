"""Docker deployment boundary tests; never connect to a real Docker daemon."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docker_deploy as docker


COMMAND = ["sh", "-c", '. /secrets/env && export DATABASE_URL="existing" && alembic upgrade head && python -m app.bootstrap && exec uvicorn app.main:app --host 0.0.0.0 --port 8000']
BASE = {"name": "mcp-hub-local", "services": {
    "backend": {"image": "old-backend", "build": {"context": "/existing"}, "command": COMMAND,
                "environment": {"PRIVATE_VALUE": "server-canary"}, "volumes": [{"source": "hub-secrets", "target": "/secrets"}]},
    "edge": {"image": "old-edge", "ports": [{"host_ip": "127.0.0.1", "published": "18443", "target": 443}]},
    "postgres": {"image": "postgres:16-alpine", "volumes": [{"source": "hub-pg", "target": "/var/lib/postgresql/data"}]},
    "your-app": {"image": "existing-app"}},
    "volumes": {"hub-pg": {"name": "mcp-hub-local_hub-pg"}, "hub-secrets": {"name": "mcp-hub-local_hub-secrets"}}}
IMAGES = {"backend": "sha256:"+"a"*64, "edge": "sha256:"+"b"*64}
NEW_IMAGES = {"backend": "sha256:"+"c"*64, "edge": "sha256:"+"d"*64}
CONTAINER = {"Config": {"Env": ["CANARY=existing"]}, "HostConfig": {"PortBindings": None},
             "Mounts": [{"Type": "volume", "Name": "existing", "Source": "/existing", "Destination": "/secrets", "RW": False}],
             "NetworkSettings": {"Networks": {"existing": {"NetworkID": "same-network"}}}}


class ComposeTest(unittest.TestCase):
    def test_frozen_compose_escapes_shell_and_secret_dollars(self):
        value = {"command": ["sh", "-c", 'export URL="scheme://$PASSWORD@host"'], "environment": {"KEY": "a${b}$c"}}
        escaped = docker.compose_literals(value)
        self.assertEqual('export URL="scheme://$$PASSWORD@host"', escaped["command"][2])
        self.assertEqual("a$${b}$$c", escaped["environment"]["KEY"])
        self.assertEqual("a${b}$c", value["environment"]["KEY"])

    def test_update_preserves_secrets_volumes_ports_and_other_services(self):
        before = copy.deepcopy(BASE)
        candidate = docker.release_compose(BASE, "mcp-hub-local", IMAGES)
        self.assertEqual(before, BASE)
        for key in ("postgres", "your-app"):
            self.assertEqual(before["services"][key], candidate["services"][key])
        self.assertEqual(before["volumes"], candidate["volumes"])
        for key in ("environment", "volumes"):
            self.assertEqual(before["services"]["backend"][key], candidate["services"]["backend"][key])
        self.assertEqual(before["services"]["edge"]["ports"], candidate["services"]["edge"]["ports"])
        self.assertNotIn("alembic", candidate["services"]["backend"]["command"][2])
        self.assertNotIn("bootstrap", candidate["services"]["backend"]["command"][2])
        self.assertNotIn("build", candidate["services"]["backend"])
        self.assertEqual(candidate, docker.release_compose(candidate, "mcp-hub-local", IMAGES))

    def test_rejects_other_project_service_mutable_image_and_unknown_startup(self):
        for project, images in (("another-project", IMAGES), ("mcp-hub-local", {"postgres": IMAGES["backend"]}),
                                ("mcp-hub-local", {"backend": "latest"})):
            with self.subTest(project=project, images=images), self.assertRaises(docker.DeploymentError):
                docker.release_compose(BASE, project, images)
        for command in (["python", "main.py"], ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --port 8000"],
                        ["sh", "-c", COMMAND[2].replace("python -m app.bootstrap &&", "")]):
            with self.subTest(command=command), self.assertRaises(docker.DeploymentError):
                docker.start_command(command)

    def test_schema_is_parsed_without_executing_release_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            release = Path(tmp)
            file = release/"backend/app/persistence/__init__.py"
            file.parent.mkdir(parents=True)
            file.write_text('raise RuntimeError("must never execute")\nSCHEMA_REVISION = "d3e5a7c9f204"\n')
            self.assertEqual("d3e5a7c9f204", docker.target_schema(release))
            file.write_text('SCHEMA_REVISION = __import__("os").getcwd()')
            with self.assertRaises(ValueError):
                docker.target_schema(release)


class FakeRuntime:
    def __init__(self):
        self.schema_value = "d3e5a7c9f204"
        self.containers = {"backend": "old-backend", "edge": "old-edge", "postgres": "same-postgres", "unrelated": "same-other"}
        self.activations = []
        self.backups = []
        self.built = False
        self.probes = [True]

    def inventory(self):
        return self.containers.copy()

    def snapshot(self):
        return docker.release_compose(BASE, "mcp-hub-local", IMAGES), {"backend": CONTAINER, "edge": CONTAINER}

    def inspect(self, container):
        return copy.deepcopy(CONTAINER)

    def schema(self):
        return self.schema_value

    def run(self, command):
        return b"d3e5a7c9f204\n"

    def build(self, *args):
        self.built = True
        return NEW_IMAGES

    def backup(self, file):
        file.write_bytes(b"verified backup")
        self.backups.append(file)

    def activate(self, file):
        self.activations.append(file)
        self.containers["backend"] = "new-backend"
        self.containers["edge"] = "new-edge"

    def ready(self):
        return self.probes.pop(0)

    def restore_networks(self, containers):
        pass


class ActivationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("shared/backups", "releases", "incoming"):
            (self.root/name).mkdir(parents=True)
        self.protected = self.root/"original.env"
        self.protected.write_text("PRIVATE_CANARY=keep-existing-value")
        self.release = self.root/"releases"/("a"*40)
        file = self.release/"backend/app/persistence/__init__.py"
        file.parent.mkdir(parents=True)
        file.write_text('SCHEMA_REVISION = "d3e5a7c9f204"')
        self.runtime = FakeRuntime()
        # Bypass POSIX root ownership only; exercise the actual activation transaction.
        self.manager = docker.DockerManager.__new__(docker.DockerManager)
        self.manager.base = self.root
        self.manager.shared = self.root/"shared"
        self.manager.config = {"project": "mcp-hub-local", "backend": "backend", "edge": "edge", "protected_files": [str(self.protected)]}
        self.manager.runtime = self.runtime
        self.unpack = patch.object(self.manager, "unpack", return_value=self.release)
        self.unpack.start()
        self.lock = patch.object(docker, "locked")
        self.lock.start()

    def tearDown(self):
        self.lock.stop()
        self.unpack.stop()
        self.temp.cleanup()

    def deploy(self):
        return self.manager.deploy("a"*40, "b"*64)

    def test_schema_change_cannot_build_backup_or_touch_live_containers(self):
        self.runtime.schema_value = "a2d4f6c8e010"
        with self.assertRaisesRegex(docker.DeploymentError, "SCHEMA_CHANGE"):
            self.deploy()
        self.assertFalse(self.runtime.built)
        self.assertEqual([], self.runtime.backups)
        self.assertEqual([], self.runtime.activations)

    def test_failed_health_restores_previous_immutable_images(self):
        self.runtime.probes = [False, True]
        with self.assertRaisesRegex(docker.DeploymentError, "PREVIOUS_IMAGES_RESTORED"):
            self.deploy()
        self.assertEqual(2, len(self.runtime.activations))
        previous = json.loads(self.runtime.activations[1].read_text())
        self.assertEqual(IMAGES["backend"], previous["services"]["backend"]["image"])
        candidate = json.loads(self.runtime.activations[0].read_text())
        self.assertEqual(NEW_IMAGES["backend"], candidate["services"]["backend"]["image"])
        self.assertFalse((self.root/"shared/docker-state.json").exists())
        self.assertEqual("PRIVATE_CANARY=keep-existing-value", self.protected.read_text())

    def test_success_records_release_and_preserves_other_containers(self):
        result = self.deploy()
        self.assertEqual("deployed", result["status"])
        self.assertEqual(1, len(self.runtime.activations))
        self.assertEqual("same-postgres", self.runtime.containers["postgres"])
        self.assertEqual("same-other", self.runtime.containers["unrelated"])
        self.assertEqual("PRIVATE_CANARY=keep-existing-value", self.protected.read_text())

    def test_secret_change_or_unrelated_restart_during_build_aborts_before_activation(self):
        def mutate(*args):
            self.runtime.containers["unrelated"] = "unexpected-replacement"
            return IMAGES
        self.runtime.build = mutate
        with self.assertRaisesRegex(docker.DeploymentError, "UNRELATED_CONTAINER"):
            self.deploy()
        self.assertEqual([], self.runtime.activations)

    def test_failed_backup_cannot_activate(self):
        def fail(path):
            raise docker.DeploymentError("DATABASE_BACKUP_FAILED")
        self.runtime.backup = fail
        with self.assertRaisesRegex(docker.DeploymentError, "BACKUP_FAILED"):
            self.deploy()
        self.assertEqual([], self.runtime.activations)

    def test_changed_storage_after_recreation_triggers_rollback(self):
        def changed(container):
            value = copy.deepcopy(CONTAINER)
            value["Mounts"][0]["Name"] = "wrong-volume"
            return value
        self.runtime.inspect = changed
        self.runtime.probes = [True, True]
        with self.assertRaisesRegex(docker.DeploymentError, "PREVIOUS_IMAGES_RESTORED"):
            self.deploy()
        self.assertEqual(2, len(self.runtime.activations))

    def test_compose_only_recreates_two_application_services(self):
        runtime = docker.DockerRuntime({"base": str(self.root), "project": "mcp-hub-local"})
        with patch.object(runtime, "run") as run:
            runtime.activate(self.root/"candidate.json")
        command = run.call_args.args[0]
        self.assertEqual(["backend", "edge"], command[-2:])
        self.assertIn("--no-deps", command)
        self.assertIn("--no-build", command)
        self.assertNotIn("--volumes", command)
        self.assertNotIn("down", command)

    def test_manual_network_membership_is_restored_without_creating_networks(self):
        runtime = docker.DockerRuntime({"base": str(self.root), "backend": "backend", "edge": "edge"})
        original = {key: copy.deepcopy(CONTAINER) for key in ("backend", "edge")}
        original["edge"]["NetworkSettings"]["Networks"]["bridge"] = {"NetworkID": "old-bridge-id"}
        with patch.object(runtime, "inspect", return_value=copy.deepcopy(CONTAINER)), patch.object(runtime, "run") as run:
            runtime.restore_networks(original)
        run.assert_called_once_with(["docker", "network", "connect", "old-bridge-id", "edge"])

    def test_network_restoration_rejects_unexpected_membership(self):
        runtime = docker.DockerRuntime({"base": str(self.root), "backend": "backend", "edge": "edge"})
        unexpected = copy.deepcopy(CONTAINER)
        unexpected["NetworkSettings"]["Networks"]["new-network"] = {"NetworkID": "unexpected"}
        with patch.object(runtime, "inspect", return_value=unexpected), patch.object(runtime, "run") as run:
            with self.assertRaisesRegex(docker.DeploymentError, "UNEXPECTED_CONTAINER_NETWORK"):
                runtime.restore_networks({"backend": CONTAINER, "edge": CONTAINER})
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
