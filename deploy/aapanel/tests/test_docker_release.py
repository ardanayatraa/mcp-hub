"""Docker deployment boundary tests; never connect to a real Docker daemon."""

import copy
import json
import sys
import tempfile
import unittest
import io
import hashlib
import tarfile
import gzip
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import docker_deploy as docker
from image_archive import inspect_archive


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
CONTAINER = {"Config": {"Env": ["CANARY=existing"]}, "HostConfig": {"PortBindings": None, "RestartPolicy": {"Name":"unless-stopped","MaximumRetryCount":0}},
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

    def preflight(self):
        pass

    def public_ready(self, commit=None):
        return True

    def load_images(self, *args):
        self.built = True
        return NEW_IMAGES

    def backup(self, file):
        file.write_bytes(b"verified backup")
        self.backups.append(file)

    def activate(self, file):
        self.activations.append(file)
        self.containers["backend"] = "new-backend"
        self.containers["edge"] = "new-edge"

    def ready(self, commit=None):
        return self.probes.pop(0)

    def restore_networks(self, containers):
        pass

    def remove_old_images(self, keep):
        self.kept = keep
        return 4

    def ci_image_ids(self):
        return {"sha256:"+"9"*64, "sha256:"+"8"*64}

    def remove_orphan_images(self, candidates, active):
        self.orphan_candidates, self.orphan_active = set(candidates), set(active)
        return 0


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
        self.manager.incoming = self.root/"incoming"
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
        return self.manager.deploy("a"*40, "b"*64, "c"*64)

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

    def test_success_removes_uploaded_archives_and_keeps_current_and_replaced_images(self):
        incoming = self.root/"incoming"
        for name in ("a"*40+".tar.gz", "a"*40+".images.tar.gz", "e"*40+".tar.gz", "f"*40+".images.tar.gz"):
            (incoming/name).write_bytes(b"archive")
        (self.root/"shared/docker-state.json").write_text(json.dumps({"current": "f"*40}))
        with patch.object(docker, "private_file", side_effect=lambda path: path):
            result = self.deploy()
        self.assertEqual({"archives_removed": 4, "images_removed": 4}, result["cleanup"])
        self.assertEqual([], list(incoming.iterdir()))
        self.assertEqual({"a"*40, "f"*40}, self.runtime.kept)

    def test_cleanup_hands_the_tagged_images_seen_before_the_load_to_the_orphan_pass(self):
        result = self.deploy()
        self.assertEqual({"sha256:"+"9"*64, "sha256:"+"8"*64}, self.runtime.orphan_candidates)
        self.assertEqual(set(NEW_IMAGES.values()), self.runtime.orphan_active)
        self.assertEqual(4, result["cleanup"]["images_removed"])

    def test_failed_orphan_cleanup_never_fails_a_verified_release(self):
        def fail(candidates, active):
            raise RuntimeError("docker unavailable")
        self.runtime.remove_orphan_images = fail
        self.assertEqual("deployed", self.deploy()["status"])

    def test_cleanup_touches_only_named_archives(self):
        incoming = self.root/"incoming"
        keep = [".images-"+"0"*32, "notes.txt", "A"*40+".tar.gz", "a"*39+".tar.gz", "a"*40+".tar.gz.part", "a"*40+".zip"]
        for name in keep:
            (incoming/name).write_bytes(b"other")
        (incoming/"directory.tar.gz").mkdir()
        (incoming/("b"*40+".tar.gz")).mkdir()
        outside = self.root/"outside"
        outside.write_bytes(b"outside")
        try:
            (incoming/("c"*40+".tar.gz")).symlink_to(outside)
        except (OSError, NotImplementedError):
            pass
        self.deploy()
        self.assertEqual(sorted(keep + ["directory.tar.gz", "b"*40+".tar.gz"]
                                + (["c"*40+".tar.gz"] if (incoming/("c"*40+".tar.gz")).is_symlink() else [])),
                         sorted(path.name for path in incoming.iterdir()))
        self.assertEqual(b"outside", outside.read_bytes())

    def test_failed_cleanup_never_fails_a_verified_release(self):
        def fail(keep):
            raise RuntimeError("docker unavailable")
        self.runtime.remove_old_images = fail
        (self.root/"incoming"/("a"*40+".tar.gz")).write_bytes(b"archive")
        result = self.deploy()
        self.assertEqual("deployed", result["status"])
        self.assertEqual({"archives_removed": 1, "images_removed": 0}, result["cleanup"])

    def test_failed_release_keeps_its_archives_for_a_retry(self):
        self.runtime.probes = [False, True]
        archive = self.root/"incoming"/("a"*40+".images.tar.gz")
        archive.write_bytes(b"archive")
        with self.assertRaises(docker.DeploymentError):
            self.deploy()
        self.assertTrue(archive.exists())
        self.assertFalse(hasattr(self.runtime, "kept"))

    def test_secret_change_or_unrelated_restart_during_build_aborts_before_activation(self):
        def mutate(*args):
            self.runtime.containers["unrelated"] = "unexpected-replacement"
            return IMAGES
        self.runtime.load_images = mutate
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

    def test_public_outage_aborts_before_import_or_backup(self):
        self.runtime.public_ready = lambda commit=None: False
        with self.assertRaisesRegex(docker.DeploymentError, 'PUBLIC_SITE_UNHEALTHY'):
            self.deploy()
        self.assertFalse(self.runtime.built)
        self.assertEqual([],self.runtime.backups)
        self.assertEqual([],self.runtime.activations)

    def test_restart_policy_drift_after_activation_triggers_rollback(self):
        def changed(container):
            value=copy.deepcopy(CONTAINER)
            value['HostConfig']['RestartPolicy']['Name']='no'
            return value
        self.runtime.inspect=changed
        self.runtime.probes=[True,True]
        with self.assertRaisesRegex(docker.DeploymentError,'PREVIOUS_IMAGES_RESTORED'):
            self.deploy()
        self.assertEqual(2,len(self.runtime.activations))

    def test_public_probe_failure_cannot_be_hidden_by_healthy_containers(self):
        runtime=docker.DockerRuntime({'base':str(self.root),'backend':'backend','edge':'edge'})
        with patch.object(runtime,'inspect',return_value={'State':{'Status':'running','Health':{'Status':'healthy'}}}), patch.object(runtime,'public_ready',return_value=False), patch.object(docker.time,'monotonic',side_effect=[0,0,100]), patch.object(docker.time,'sleep'):
            self.assertFalse(runtime.ready('a'*40))

    def test_public_https_probe_identifies_itself_and_rejects_stale_commit(self):
        runtime=docker.DockerRuntime({'base':str(self.root),'public_url':'https://hub.example'})
        served_commit='a'*40
        requests=[]
        def respond(request,timeout):
            requests.append(request)
            response=MagicMock()
            response.__enter__.return_value=response
            response.status=200
            response.geturl.return_value=request.full_url
            body=(b'{"status":"ready"}' if request.full_url.endswith('/ready') else b'<title>MCP Hub</title>' if request.full_url.endswith('/login') else json.dumps({'commit':served_commit}).encode())
            response.read.return_value=body
            return response
        opener=MagicMock()
        opener.open.side_effect=respond
        with patch.object(docker.urllib.request,'build_opener',return_value=opener):
            self.assertTrue(runtime.public_ready('a'*40))
            served_commit='b'*40
            self.assertFalse(runtime.public_ready('a'*40))
        self.assertTrue(all(q.get_header('User-agent')=='MCP-Hub-Deploy/1.0' for q in requests))

    def test_low_resources_abort_before_preparation(self):
        def fail():
            raise docker.DeploymentError('AT_LEAST_1_GIB_AVAILABLE_MEMORY_REQUIRED')
        self.runtime.preflight=fail
        with self.assertRaisesRegex(docker.DeploymentError,'AVAILABLE_MEMORY_REQUIRED'):
            self.deploy()
        self.assertFalse(self.runtime.built)
        self.assertEqual([],self.runtime.activations)

    def test_interrupted_image_upload_leaves_no_final_archive_and_can_be_retried(self):
        self.manager.incoming=self.root/'incoming'
        raw=b'complete image stream'
        checksum=hashlib.sha256(raw).hexdigest()
        with self.assertRaisesRegex(docker.DeploymentError,'INCOMPLETE_OR_CHANGED'):
            self.manager.upload_images('a'*40,checksum,io.BytesIO(raw[:4]))
        self.assertEqual([],list(self.manager.incoming.iterdir()))
        with patch.object(docker.os,'link',side_effect=lambda a,b: Path(b).write_bytes(Path(a).read_bytes())):
            self.manager.upload_images('a'*40,checksum,io.BytesIO(raw))
        self.assertEqual(raw,(self.manager.incoming/('a'*40+'.images.tar.gz')).read_bytes())


class ImageCleanupTest(unittest.TestCase):
    def runtime(self, listing, refuse=()):
        runtime = docker.DockerRuntime.__new__(docker.DockerRuntime)
        self.commands = []

        def run(command, *, input=None, timeout=900):
            self.commands.append(command)
            if command[:3] == ["docker", "image", "ls"]:
                return "\n".join(listing).encode()
            if command[-1] in refuse:
                raise docker.DeploymentError("DOCKER_OPERATION_FAILED_CHECK_SERVER")
            return b""
        runtime.run = run
        return runtime

    def test_removes_only_older_deployment_images(self):
        old, current, replaced = "1"*40, "2"*40, "3"*40
        listing = [f"mcp-hub-ci-backend:{old}", f"mcp-hub-ci-edge:{old}", f"mcp-hub-ci-backend:{current}",
                   f"mcp-hub-ci-edge:{replaced}", "postgres:16-alpine", "mcp-hub-ci-backend:latest",
                   f"mcp-hub-ci-worker:{old}", f"other-mcp-hub-ci-backend:{old}", "<none>:<none>"]
        runtime = self.runtime(listing)
        self.assertEqual(2, runtime.remove_old_images({current, replaced}))
        self.assertEqual([["docker", "image", "rm", f"mcp-hub-ci-backend:{old}"],
                          ["docker", "image", "rm", f"mcp-hub-ci-edge:{old}"]], self.commands[1:])

    def test_an_image_docker_refuses_to_remove_is_not_an_error(self):
        old = "1"*40
        runtime = self.runtime([f"mcp-hub-ci-backend:{old}", f"mcp-hub-ci-edge:{old}"], refuse={f"mcp-hub-ci-backend:{old}"})
        self.assertEqual(1, runtime.remove_old_images(set()))


class OrphanImageTest(unittest.TestCase):
    def runtime(self, tags, refuse=()):
        runtime = docker.DockerRuntime.__new__(docker.DockerRuntime)
        self.commands = []

        def run(command, *, input=None, timeout=900):
            self.commands.append(command)
            if command[:3] == ["docker", "image", "ls"]:
                return (f"sha256:{'1'*64} mcp-hub-ci-backend\nsha256:{'2'*64} mcp-hub-ci-edge\n"
                        f"sha256:{'3'*64} postgres\nsha256:{'4'*64} <none>\nbroken line\n"
                        f"sha256:{'5'*64} other-mcp-hub-ci-backend\n").encode()
            if command[:3] == ["docker", "image", "inspect"]:
                return json.dumps(tags[command[-1]]).encode()
            if command[-1] in refuse:
                raise docker.DeploymentError("DOCKER_OPERATION_FAILED_CHECK_SERVER")
            return b""
        runtime.run = run
        return runtime

    def test_lists_only_deployment_image_ids(self):
        self.assertEqual({"sha256:"+"1"*64, "sha256:"+"2"*64}, self.runtime({}).ci_image_ids())

    def test_removes_only_untagged_images_that_were_deployment_images(self):
        untagged, retagged, active, unknown = ("sha256:"+c*64 for c in "1234")
        runtime = self.runtime({untagged: None, retagged: ["mcp-hub-ci-edge:"+"b"*40], active: None})
        self.assertEqual(1, runtime.remove_orphan_images({untagged, retagged, active}, {active}))
        self.assertEqual([["docker", "image", "rm", untagged]], [c for c in self.commands if c[:3] == ["docker", "image", "rm"]])
        self.assertNotIn(unknown, [c[-1] for c in self.commands])

    def test_an_orphan_docker_refuses_to_remove_is_not_an_error(self):
        first, second = "sha256:"+"1"*64, "sha256:"+"2"*64
        runtime = self.runtime({first: [], second: []}, refuse={first})
        self.assertEqual(1, runtime.remove_orphan_images({first, second}, set()))

    def test_unreadable_tag_data_leaves_the_image(self):
        image = "sha256:"+"1"*64
        runtime = self.runtime({image: []})
        runtime.run = lambda command, **kw: b"not json"
        self.assertEqual(0, runtime.remove_orphan_images({image}, set()))


class ImageArchiveTest(unittest.TestCase):
    def archive(self, path, commit='a'*40, schema='d3e5a7c9f204', tag=None, link=False):
        files, manifest, expected = {},[],{}
        for service in ('backend','edge'):
            raw=json.dumps({'os':'linux','architecture':'amd64','config':{'Labels':{'org.opencontainers.image.revision':commit,'biz.texcel.mcp-hub.schema':schema}},'rootfs':{'diff_ids':['sha256:'+'f'*64]},'service':service}).encode()
            name=hashlib.sha256(raw).hexdigest()+'.json'
            files[name]=raw
            layer=service+'/layer.tar'
            files[layer]=b'fixture layer'
            manifest.append({'Config':name,'RepoTags':[tag or 'mcp-hub-ci-'+service+':'+commit],'Layers':[layer]})
            expected[service]='sha256:'+hashlib.sha256(raw).hexdigest()
        files['manifest.json']=json.dumps(manifest).encode()
        with tarfile.open(path,'w:gz') as archive:
            for name,raw in files.items():
                member=tarfile.TarInfo(name)
                member.size=len(raw)
                archive.addfile(member,io.BytesIO(raw))
            if link:
                member=tarfile.TarInfo('unexpected-link')
                member.type=tarfile.SYMTYPE
                member.linkname='/etc/shadow'
                archive.addfile(member)
        return expected

    def test_only_expected_commit_schema_platform_and_two_image_tags_are_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'images.tar.gz'
            expected=self.archive(file)
            self.assertEqual(expected,inspect_archive(file,'a'*40,'d3e5a7c9f204')[0])
            for options in ({'commit':'b'*40},{'schema':'000000000000'},{'tag':'unrelated:latest'},{'link':True}):
                self.archive(file,**options)
                with self.subTest(options=options),self.assertRaises(docker.DeploymentError):
                    inspect_archive(file,'a'*40,'d3e5a7c9f204')

    def test_import_verifies_content_in_classic_and_containerd_stores_without_building(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'incoming').mkdir()
            file=root/'incoming'/('a'*40+'.images.tar.gz')
            expected=self.archive(file)
            runtime=docker.DockerRuntime({'base':tmp})
            configs=inspect_archive(file,'a'*40,'d3e5a7c9f204')[2]
            actual_ids=expected.copy()
            wrong_layers=False
            def run(command,**kwargs):
                if command[:3]==['docker','image','inspect']:
                    service=command[-1].split('mcp-hub-ci-')[1].split(':')[0]
                    config=configs[service]
                    return json.dumps([{'Id':actual_ids[service],'Config':config['config'],'RootFS':{'Layers':['sha256:'+'0'*64] if wrong_layers else config['rootfs']['diff_ids']},'Os':'linux','Architecture':'amd64'}]).encode()
                return b''
            with patch.object(runtime,'preflight'),patch.object(runtime,'run',side_effect=run) as calls,patch.object(docker.shutil,'disk_usage',return_value=type('Disk',(),{'free':20*1024**3})()):
                self.assertEqual(expected,runtime.load_images('a'*40,docker.digest(file),'d3e5a7c9f204'))
                actual_ids={'backend':'sha256:'+'e'*64,'edge':'sha256:'+'d'*64}
                self.assertEqual(actual_ids,runtime.load_images('a'*40,docker.digest(file),'d3e5a7c9f204'))
                wrong_layers=True
                with self.assertRaisesRegex(docker.DeploymentError,'IMPORTED_IMAGE_CONTENT_MISMATCH'):
                    runtime.load_images('a'*40,docker.digest(file),'d3e5a7c9f204')
            self.assertEqual(['docker','load','--input',str(file)],calls.call_args_list[0].args[0])
            self.assertFalse(any('build' in c.args[0] for c in calls.call_args_list))

    def test_expanded_gzip_padding_is_bounded_before_tar_parsing(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'images.tar.gz'
            with gzip.open(file,'wb') as output:
                output.write(b'\0'*65536)
            with patch('image_archive.MAX_EXPANDED',1024),self.assertRaisesRegex(docker.DeploymentError,'EXPANDED_TOO_LARGE'):
                inspect_archive(file,'a'*40,'d3e5a7c9f204')


if __name__ == "__main__":
    unittest.main()
