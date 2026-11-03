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
from prepare_prebuilt import prepare


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
    commit = os.environ['DEPLOY_COMMIT']
    artifacts = Path(os.environ['RELEASE_INPUT'])
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
            document = json.loads(run([*compose, "config", "--format", "json"], env=environment))
            for key in ('backend','edge','postgres'):
                document['services'][key]['restart']='unless-stopped'
            run(['docker','update','--restart','unless-stopped',*containers.values()])
            baseline.write_text(json.dumps(docker.compose_literals(document)))
            baseline.chmod(0o600)
            config = {"base": str(base), "project": project, "compose": str(baseline), **containers,
                      "database": "hub", "database_user": "hub", "protected_files": [str(marker), str(protected), str(baseline)]}
            config_file=base/'controller.json'
            config_file.write_text(json.dumps(config))
            config_file.chmod(0o600)
            ca=base/'probe-ca.crt'
            run(['docker','cp',containers['edge']+':/etc/nginx/certs/hub.crt',str(ca)])
            ca.chmod(0o600)
            # Exercise the same one-time preparation used on an existing aaPanel stack.
            prepare(config_file,'https://localhost:18443',ca)
            config=docker.load_config(config_file)
            runtime = docker.DockerRuntime(config)
            before = runtime.inventory()
            volume_ids = run(["docker", "volume", "inspect", project+"_hub-pg", project+"_hub-secrets"])
            admins = runtime.run(["docker", "exec", containers["postgres"], "psql", "-U", "hub", "-d", "hub", "-Atc",
                                  "select row_to_json(t)::text from admin_users t order by id"])
            manager = docker.DockerManager(config, runtime)
            with (artifacts/'source.tar.gz').open('rb') as incoming:
                manager.upload(commit,incoming)
            with (artifacts/'images.tar.gz').open('rb') as incoming:
                manager.upload_images(commit,docker.digest(artifacts/'images.tar.gz'),incoming)
            checksum=docker.digest(artifacts/'source.tar.gz')
            image_checksum=docker.digest(artifacts/'images.tar.gz')
            assert manager.deploy(commit,checksum,image_checksum)['status']=='deployed'
            assert runtime.public_ready(commit)
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
            assert all(runtime.inspect(name)['HostConfig']['RestartPolicy']['Name']=='unless-stopped' for name in containers.values())
            run(['docker','restart',containers['backend']])
            assert runtime.ready(commit)
            # A startup failure must restore the images just verified above.
            good_images = {key: runtime.inspect(containers[key])["Image"] for key in ("backend", "edge")}
            good_commit=commit
            source=base/'releases'/commit
            source=Path(shutil.copytree(source,base/'broken-source',ignore=shutil.ignore_patterns('.env')))
            (source/"backend/app/main.py").write_text('raise RuntimeError("disposable rollback fixture")\n')
            commit = "b"*40
            (source/'frontend/dist/release-version.json').write_text(json.dumps({'commit':commit}))
            # Failure fixtures are also built only on this disposable GitHub runner.
            for key in ('backend','edge'):
                recipe=base/('broken-'+key+'.Dockerfile')
                copy=('COPY backend/app/main.py /app/app/main.py' if key=='backend' else 'COPY frontend/dist/release-version.json /usr/share/nginx/html/release-version.json')
                recipe.write_text('FROM '+good_images[key]+'\nLABEL org.opencontainers.image.revision='+commit+'\n'+copy+'\n')
                run(['docker','build','--file',str(recipe),'--tag','mcp-hub-ci-'+key+':'+commit,str(source)])
            import gzip
            saved=base/'broken-images.tar'
            run(['docker','save','--output',str(saved),'mcp-hub-ci-backend:'+commit,'mcp-hub-ci-edge:'+commit])
            images=base/'incoming'/(commit+'.images.tar.gz')
            with saved.open('rb') as incoming,gzip.open(images,'wb',compresslevel=1) as output:
                shutil.copyfileobj(incoming,output)
            checksum = build_release.build(source, commit, base/"incoming"/(commit+".tar.gz"))
            try:
                manager.deploy(commit, checksum,docker.digest(images))
            except docker.DeploymentError as error:
                assert str(error) == "RELEASE_FAILED_PREVIOUS_IMAGES_RESTORED", str(error)
            else:
                raise AssertionError("Broken release unexpectedly activated")
            assert good_images == {key: runtime.inspect(containers[key])["Image"] for key in ("backend", "edge")}
            assert 'bridge' in runtime.inspect(containers['edge'])['NetworkSettings']['Networks']
            assert json.loads((base/"shared/docker-state.json").read_text())["current"] == good_commit
            assert runtime.public_ready(good_commit)
            assert protected.read_text() == "existing-key-and-settings-canary"
            print("Docker deploy, verified backup, container/volume preservation and failed-release rollback passed.")
        finally:
            # Only the uniquely named project created above is disposable.
            run([*compose, "down", "--volumes"], env=environment)


if __name__ == "__main__":
    main()
