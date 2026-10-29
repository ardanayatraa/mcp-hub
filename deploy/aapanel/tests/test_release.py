"""Filesystem/rollback tests with a simulated service; no production SSH or database."""

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import build_release  # noqa: E402 - tests exercise the server's standalone scripts.
import deploy  # noqa: E402


class Runtime:
    def __init__(self):
        self.schema = {"current": ["reviewed_head"], "target": "reviewed_head"}
        self.restarts = 0
        self.probes = [True]
        self.backups = []

    def prepare(self, release):
        pass

    def inspect(self, release):
        return self.schema

    def backup(self, release, path):
        path.write_bytes(b"disposable-metadata-backup")
        path.chmod(0o600)
        self.backups.append(path)

    def restart(self):
        self.restarts += 1

    def ready(self):
        return self.probes.pop(0) if self.probes else True


@unittest.skipUnless(os.name == "posix", "Release activation requires Linux; run these tests in Linux or Docker")
class ReleaseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.base = self.root/"server"
        for folder in ("shared/backups", "shared/frontend-assets", "releases", "incoming"):
            (self.base/folder).mkdir(parents=True, exist_ok=True)
        self.env = self.base/"shared/hub.env"
        self.env.write_text('SECRET_ENCRYPTION_KEY="private-server-canary"\nDATABASE_URL="existing-database"\n')
        self.env.chmod(0o640)
        self.settings = self.base/"shared/existing-settings.json"
        self.settings.write_text('{"existing_client_key":"private-setting-canary","app_enabled":false}')
        self.config = {"base": str(self.base), "service": "mcp-hub.service", "python": "/usr/bin/python3.12",
                       "uv": "/usr/local/bin/uv", "pg_dump": "/usr/bin/pg_dump",
                       "health_url": "http://127.0.0.1:18321/ready", "health_host": "hub.example.com"}
        self.runtime = Runtime()
        self.manager = deploy.Manager(self.config, self.runtime)
        self.first = "a"*40
        self.second = "b"*40

    def tearDown(self):
        self.temp.cleanup()

    def bundle(self, commit, asset="index-first.js", content="console.log('fixture')"):
        source = self.root/("source-"+commit)
        files = {"backend/app/main.py": "# isolated application", "backend/pyproject.toml": "[project]",
                 "backend/uv.lock": "version = 1", "backend/alembic.ini": "[alembic]",
                 "deploy/aapanel/runtime.py": "# isolated runtime fixture",
                 "frontend/dist/index.html": "<html>fixture</html>", "frontend/dist/assets/"+asset: content,
                 "backend/.env": "never-package-this-secret", "backend/local.db": "private database",
                 "frontend/node_modules/local.txt": "unneeded dependency"}
        for name, value in files.items():
            path = source/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(value)
        target = self.base/"incoming"/(commit+".tar.gz")
        checksum = build_release.build(source, commit, target)
        return target, checksum

    def test_deploy_preserves_credentials_settings_and_old_assets(self):
        environment, settings = self.env.read_bytes(), self.settings.read_bytes()
        _, checksum = self.bundle(self.first)
        with tarfile.open(self.manager.archive(self.first)) as archive:
            names = archive.getnames()
        self.assertFalse(any(".env" in name or "node_modules" in name or name.endswith(".db") for name in names))
        result = self.manager.deploy(self.first, checksum)
        self.assertEqual("deployed", result["status"])
        self.assertEqual(self.first, self.manager.current().name)
        self.assertEqual(self.env, (self.manager.current()/"backend/.env").resolve())
        _, checksum = self.bundle(self.second, "index-second.js", "console.log('second')")
        self.manager.deploy(self.second, checksum)
        self.assertEqual(environment, self.env.read_bytes())
        self.assertEqual(settings, self.settings.read_bytes())
        self.assertTrue((self.base/"shared/frontend-assets/index-first.js").is_file())
        self.assertTrue((self.base/"shared/frontend-assets/index-second.js").is_file())
        self.assertEqual(self.first, json.loads((self.base/"shared/deploy-state.json").read_text())["previous"])
        self.assertEqual(2, len(self.runtime.backups))
        self.assertEqual(0o600, self.runtime.backups[0].stat().st_mode & 0o777)
        self.assertEqual(0o755, self.manager.current().stat().st_mode & 0o777)

    def test_failed_probe_restores_previous_release_without_changing_environment(self):
        _, first = self.bundle(self.first)
        self.manager.deploy(self.first, first)
        before = self.env.read_bytes()
        _, second = self.bundle(self.second, "second.js", "second")
        self.runtime.probes = [False, True]
        with self.assertRaisesRegex(deploy.DeploymentError, "PREVIOUS_RELEASE_RESTORED"):
            self.manager.deploy(self.second, second)
        self.assertEqual(self.first, self.manager.current().name)
        self.assertEqual(before, self.env.read_bytes())
        self.assertEqual(3, self.runtime.restarts)
        self.assertEqual(self.first, json.loads((self.base/"shared/deploy-state.json").read_text())["current"])

    def test_pending_migrations_never_change_the_database_or_active_release(self):
        _, checksum = self.bundle(self.first)
        self.runtime.schema = {"current": ["previous_revision"], "target": "new_revision"}
        before = self.settings.read_bytes()
        with self.assertRaisesRegex(deploy.DeploymentError, "SCHEMA_CHANGE_REQUIRES_REVIEW"):
            self.manager.deploy(self.first, checksum)
        self.assertIsNone(self.manager.current())
        self.assertEqual(0, self.runtime.restarts)
        self.assertEqual([], self.runtime.backups)
        self.assertEqual(before, self.settings.read_bytes())

    def test_database_drift_cannot_trigger_an_unsafe_code_rollback(self):
        _, checksum = self.bundle(self.first)
        self.manager.deploy(self.first, checksum)
        _, checksum = self.bundle(self.second, "second.js", "second")
        self.runtime.schema = {"current": ["different_head"], "target": "different_head"}
        with self.assertRaisesRegex(deploy.DeploymentError, "SCHEMA_COMPATIBILITY_REVIEW_REQUIRED"):
            self.manager.deploy(self.second, checksum)
        self.assertEqual(self.first, self.manager.current().name)
        self.assertEqual(1, self.runtime.restarts)

    def test_operator_schema_cutover_never_downgrades_or_restarts_incompatible_code(self):
        _, checksum = self.bundle(self.first)
        self.manager.deploy(self.first, checksum)
        _, checksum = self.bundle(self.second, "second.js", "second")
        self.runtime.schema = {"current": ["new_head"], "target": "new_head"}
        self.runtime.probes = [False]
        with self.assertRaisesRegex(deploy.DeploymentError, "NO_DATABASE_DOWNGRADE"):
            self.manager.deploy(self.second, checksum, schema_cutover=True)
        self.assertEqual(self.second, self.manager.current().name)
        self.assertEqual(2, self.runtime.restarts)
        self.assertIn("private-server-canary", self.env.read_text())

    def test_asset_collision_never_overwrites_previous_content(self):
        _, checksum = self.bundle(self.first)
        self.manager.deploy(self.first, checksum)
        original = (self.base/"shared/frontend-assets/index-first.js").read_bytes()
        _, checksum = self.bundle(self.second, content="changed content with same filename")
        with self.assertRaisesRegex(deploy.DeploymentError, "ASSET_COLLISION"):
            self.manager.deploy(self.second, checksum)
        self.assertEqual(original, (self.base/"shared/frontend-assets/index-first.js").read_bytes())
        self.assertEqual(self.first, self.manager.current().name)

    def test_environment_rotation_during_preparation_aborts_without_overwriting_it(self):
        _, checksum = self.bundle(self.first)
        def rotate(release):
            self.env.write_text("operator-rotated-value")
        self.runtime.prepare = rotate
        with self.assertRaisesRegex(deploy.DeploymentError, "SERVER_ENV_CHANGED"):
            self.manager.deploy(self.first, checksum)
        self.assertEqual("operator-rotated-value", self.env.read_text())
        self.assertEqual(0, self.runtime.restarts)

    def test_concurrent_deployment_is_rejected(self):
        _, checksum = self.bundle(self.first)
        with deploy.locked(self.base/"shared/deploy.lock"):
            with self.assertRaisesRegex(deploy.DeploymentError, "DEPLOYMENT_BUSY"):
                self.manager.deploy(self.first, checksum)

    def test_dirty_release_and_wrong_checksums_fail_before_activation(self):
        _, checksum = self.bundle(self.first)
        with self.assertRaisesRegex(deploy.DeploymentError, "CHECKSUM"):
            self.manager.deploy(self.first, "f"*64)
        release = self.manager.unpack(self.first, checksum)
        (release/"backend/app/main.py").write_text("changed")
        with self.assertRaisesRegex(deploy.DeploymentError, "FILES_HAVE_CHANGED"):
            self.manager.deploy(self.first, checksum)
        self.assertIsNone(self.manager.current())

    def test_upload_is_idempotent_and_rejects_overwrite(self):
        self.assertEqual("uploaded", self.manager.upload(self.first, io.BytesIO(b"archive"))["status"])
        self.manager.upload(self.first, io.BytesIO(b"archive"))
        with self.assertRaisesRegex(deploy.DeploymentError, "DIFFERENT_ARCHIVE"):
            self.manager.upload(self.first, io.BytesIO(b"different"))
        self.assertEqual(b"archive", self.manager.archive(self.first).read_bytes())

    def test_compressed_archive_and_large_tar_headers_are_bounded(self):
        file, checksum = self.bundle(self.first)
        with patch.object(deploy, "MAX_TAR_BYTES", 100):
            with self.assertRaisesRegex(deploy.DeploymentError, "EXPANDED_ARCHIVE_TOO_LARGE"):
                self.manager.unpack(self.first, checksum)
        with file.open("rb") as handle:
            bounded = deploy.BoundedTarReader(handle)
            with self.assertRaisesRegex(deploy.DeploymentError, "TAR_METADATA_TOO_LARGE"):
                bounded.read(1024**3)

    def test_runtime_secret_files_cannot_enter_the_release_bundle(self):
        self.bundle(self.first)
        source = self.root/("source-"+self.first)
        (source/"backend/app/developer.env").write_text("local-secret-canary")
        with self.assertRaisesRegex(ValueError, "Unexpected release input"):
            build_release.build(source, self.second, self.root/"should-not-exist.tar.gz")
        self.assertFalse((self.root/"should-not-exist.tar.gz").exists())

    def test_path_traversal_secret_files_and_tar_links_are_rejected(self):
        for name, kind in [("backend/app/../../shared/hub.env", tarfile.REGTYPE),
                           ("backend/app/.env", tarfile.REGTYPE), ("/etc/passwd", tarfile.REGTYPE),
                           ("backend/app/linked.py", tarfile.SYMTYPE), ("backend/app/hard.py", tarfile.LNKTYPE)]:
            with self.subTest(name=name):
                archive = self.base/"incoming"/(self.first+".tar.gz")
                with tarfile.open(archive, "w:gz") as handle:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = str(self.env) if kind != tarfile.REGTYPE else ""
                    member.size = 3 if kind == tarfile.REGTYPE else 0
                    handle.addfile(member, io.BytesIO(b"bad") if member.size else None)
                with self.assertRaisesRegex(deploy.DeploymentError, "UNSAFE_ARCHIVE_MEMBER"):
                    self.manager.unpack(self.first, deploy.digest(archive))
                self.assertIn("private-server-canary", self.env.read_text())

    def test_symlinked_release_cannot_escape_the_configured_root(self):
        _, checksum = self.bundle(self.first)
        outside = self.root/"unrelated-site"
        outside.mkdir()
        (self.base/"releases"/self.first).symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(deploy.DeploymentError, "SYMLINK"):
            self.manager.unpack(self.first, checksum)
        self.assertEqual([], list(outside.iterdir()))

    def test_existing_server_directory_is_never_replaced_as_current(self):
        (self.base/"current").mkdir()
        (self.base/"current/existing.txt").write_text("keep existing site")
        _, checksum = self.bundle(self.first)
        with self.assertRaisesRegex(deploy.DeploymentError, "CURRENT_MUST_BE"):
            self.manager.deploy(self.first, checksum)
        self.assertEqual("keep existing site", (self.base/"current/existing.txt").read_text())

    def test_bundle_output_is_reproducible(self):
        first, checksum = self.bundle(self.first)
        second = self.root/"same-release.tar.gz"
        again = build_release.build(self.root/("source-"+self.first), self.first, second)
        self.assertEqual(checksum, again)
        self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_secret_content_is_not_returned_by_failed_deployments(self):
        _, checksum = self.bundle(self.first)
        self.runtime.schema = {"current": [], "target": "head"}
        try:
            self.manager.deploy(self.first, checksum)
        except deploy.DeploymentError as error:
            self.assertNotIn("private-server-canary", str(error))
            self.assertNotIn("private-setting-canary", str(error))


if __name__ == "__main__":
    unittest.main()
