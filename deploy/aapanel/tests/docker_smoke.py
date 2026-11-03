"""Real Docker deployment and rollback on a uniquely named, disposable CI stack."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build_release
import docker_deploy as docker


def run(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=600, **kwargs)
    if result.returncode:
        # All credentials belong to disposable CI, but keep the same output discipline.
        raise RuntimeError("Disposable Docker verification command failed")
    return result.stdout


def main():
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.geteuid() != 0:
        raise RuntimeError("This disposable integration test is restricted to GitHub CI")
    root = HERE.parents[1]
    project = "mcp-hub-deploy-ci-"+uuid.uuid4().hex[:10]
    environment = os.environ.copy()
    environment["HUB_PROJECT"] = project
    compose = ["docker", "compose", "--project-name", project, "--file", str(root/"compose.yaml")]
    with tempfile.TemporaryDirectory(prefix=project+"-") as tmp:
        base = Path(tmp)
        try:
            run([*compose, "up", "--detach", "--build", "--wait", "--wait-timeout", "180", "backend", "edge", "your-app"], env=environment)
            containers = {}
            for service in ("backend", "edge", "postgres"):
                identifier = run([*compose, "ps", "--quiet", service], env=environment).decode().strip()
                containers[service] = json.loads(run(["docker", "inspect", identifier]))[0]["Name"].lstrip("/")
            # Model an existing aaPanel edge attached manually to Docker's bridge.
            run(['docker', 'network', 'connect', 'bridge', containers['edge']])
            for folder in ("shared/backups", "releases", "incoming", "source"):
                (base/folder).mkdir(parents=True)
            marker = base/"shared/hub.env"
            marker.touch(mode=0o600)
            protected = base/"existing-settings.env"
            protected.write_text("existing-key-and-settings-canary")
            protected.chmod(0o600)
            baseline = base/"shared/baseline.json"
            baseline.write_bytes(run([*compose, "config", "--format", "json"], env=environment))
            baseline.chmod(0o600)
            config = {"base": str(base), "project": project, "compose": str(baseline), **containers,
                      "database": "hub", "database_user": "hub", "protected_files": [str(marker), str(protected), str(baseline)]}
            runtime = docker.DockerRuntime(config)
            before = runtime.inventory()
            volume_ids = run(["docker", "volume", "inspect", project+"_hub-pg", project+"_hub-secrets"])
            admins = runtime.run(["docker", "exec", containers["postgres"], "psql", "-U", "hub", "-d", "hub", "-Atc",
                                  "select row_to_json(t)::text from admin_users t order by id"])
            source = base/"source"
            for name in build_release.SINGLE:
                target = source/name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(root/name, target)
            shutil.copytree(root/"backend/app", source/"backend/app", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (source/"frontend").mkdir()
            run(["docker", "cp", containers["edge"]+":/usr/share/nginx/html", str(source/"frontend/dist")])
            manager = docker.DockerManager(config, runtime)
            commit = "a"*40
            checksum = build_release.build(source, commit, base/"incoming"/(commit+".tar.gz"))
            assert manager.deploy(commit, checksum)["status"] == "deployed"
            # Alembic reads pyproject.toml as the application's non-root user.
            # Release extraction uses private source-file permissions, so merely
            # starting Uvicorn does not verify migration tooling remains usable.
            runtime.run(['docker', 'exec', containers['backend'], 'sh', '-c',
                         '. /secrets/env && export DATABASE_URL="postgresql+psycopg://hub:$POSTGRES_PASSWORD@postgres:5432/hub" && alembic current'])
            after = runtime.inventory()
            allowed = {containers["backend"], containers["edge"]}
            assert {k: v for k, v in before.items() if k not in allowed} == {k: v for k, v in after.items() if k not in allowed}
            assert volume_ids == run(["docker", "volume", "inspect", project+"_hub-pg", project+"_hub-secrets"])
            assert admins == runtime.run(["docker", "exec", containers["postgres"], "psql", "-U", "hub", "-d", "hub", "-Atc",
                                         "select row_to_json(t)::text from admin_users t order by id"])
            # A startup failure must restore the images just verified above.
            good_images = {key: runtime.inspect(containers[key])["Image"] for key in ("backend", "edge")}
            (source/"backend/app/main.py").write_text('raise RuntimeError("disposable rollback fixture")\n')
            commit = "b"*40
            checksum = build_release.build(source, commit, base/"incoming"/(commit+".tar.gz"))
            try:
                manager.deploy(commit, checksum)
            except docker.DeploymentError as error:
                assert str(error) == "RELEASE_FAILED_PREVIOUS_IMAGES_RESTORED", str(error)
            else:
                raise AssertionError("Broken release unexpectedly activated")
            assert good_images == {key: runtime.inspect(containers[key])["Image"] for key in ("backend", "edge")}
            assert 'bridge' in runtime.inspect(containers['edge'])['NetworkSettings']['Networks']
            assert json.loads((base/"shared/docker-state.json").read_text())["current"] == "a"*40
            assert protected.read_text() == "existing-key-and-settings-canary"
            print("Docker deploy, verified backup, container/volume preservation and failed-release rollback passed.")
        finally:
            # Only the uniquely named project created above is disposable.
            run([*compose, "down", "--volumes"], env=environment)


if __name__ == "__main__":
    main()
