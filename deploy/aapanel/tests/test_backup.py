"""Exercise backup atomicity and secret handling with a local fake pg_dump."""

import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import runtime  # noqa: E402


@unittest.skipUnless(os.name == "posix", "The server backup helper runs on Linux")
class BackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        engine = types.ModuleType("sqlalchemy.engine")
        engine.make_url = lambda value: types.SimpleNamespace(drivername="postgresql+psycopg", host="db.example.test",
            port=5432, username="hub", password="dummy:private\\value", database="hub_test", query={"sslmode": "verify-full"})
        config = types.ModuleType("app.config")
        config.get_settings = lambda: types.SimpleNamespace(database_url="fixture-only")
        self.modules = patch.dict(sys.modules, {"sqlalchemy.engine": engine, "app.config": config})
        self.modules.start()
        self.binary = self.root/"pg_dump_fixture"
        self.binary.write_text("#!"+sys.executable+"\n"+'''
import os, pathlib, sys
assert 'PGPASSWORD' not in os.environ
assert not any('private' in arg for arg in sys.argv)
assert os.environ['PGSSLMODE'] == 'verify-full'
password_file = pathlib.Path(os.environ['PGPASSFILE'])
assert password_file.stat().st_mode & 0o777 == 0o600
assert 'dummy\\\\:private' in password_file.read_text()
sys.stdout.buffer.write(b'isolated-pg-dump-fixture')
''')
        self.binary.chmod(0o700)

    def tearDown(self):
        self.modules.stop()
        self.temp.cleanup()

    def test_backup_uses_a_private_temporary_password_file_and_never_overwrites(self):
        target = self.root/"metadata.dump"
        result = runtime.backup(str(self.binary), str(target))
        self.assertEqual({"backup": "created"}, result)
        self.assertEqual(b"isolated-pg-dump-fixture", target.read_bytes())
        self.assertEqual(0o600, target.stat().st_mode & 0o777)
        self.assertEqual([], list(self.root.glob(".pgpass-*")))
        with self.assertRaisesRegex(RuntimeError, "already exists"):
            runtime.backup(str(self.binary), str(target))
        self.assertEqual(b"isolated-pg-dump-fixture", target.read_bytes())

    def test_failed_dump_leaves_no_final_backup_or_password_file(self):
        self.binary.write_text("#!"+sys.executable+"\nimport sys\nsys.stderr.write('dummy-private-error')\nsys.exit(1)\n")
        target = self.root/"failed.dump"
        with self.assertRaisesRegex(RuntimeError, "Database backup failed"):
            runtime.backup(str(self.binary), str(target))
        self.assertFalse(target.exists())
        self.assertEqual([], list(self.root.glob(".pgpass-*")))
        self.assertEqual([], list(self.root.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
