import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

DIRECTORY = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('public_migration', DIRECTORY / 'migrate-public-package.py')
migration = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(migration)
GUARD_SPEC = importlib.util.spec_from_file_location('integration_state', DIRECTORY / 'integration_state.py')
guard = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(guard)


class PublicMigrationTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='mcp-public-migration-')
        self.app = Path(self.temporary.name).resolve()
        for relative in migration.FILES:
            target = self.app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(DIRECTORY / 'overlay' / relative, target)
        (self.app / '.env').write_bytes(b'APP_KEY=private-environment-canary\n')
        (self.app / 'composer.json').write_text(json.dumps({'require': {'laravel/framework': '^9.2',
            migration.OLD: 'dev-main'}, 'repositories': {'mcp-hub-local': {'type': 'path', 'url': 'old-prototype'}}}))

    def tearDown(self):
        self.temporary.cleanup()

    def test_plan_patches_only_reviewed_sections_and_is_repeatable(self):
        before = (self.app / '.env').read_bytes()
        changes = migration.patches(self.app)
        self.assertEqual(set(migration.FILES), set(changes))
        self.assertIn('NonceStore::class', changes[migration.FILES[0]])
        self.assertNotIn('Cache::add', changes[migration.FILES[0]])
        self.assertIn("$ready ? 200 : 503", changes[migration.FILES[1]])
        self.assertIn("$params['arguments'] = []", changes[migration.FILES[2]])
        for relative, content in changes.items(): (self.app / relative).write_text(content)
        self.assertEqual(changes, migration.patches(self.app))
        self.assertEqual(before, (self.app / '.env').read_bytes())

    def test_unreviewed_application_changes_are_refused_without_overwriting_them(self):
        target = self.app / migration.FILES[0]
        changed = target.read_text().replace('Cache::add(', 'MyNewReplayService::consume(')
        target.write_text(changed)
        with self.assertRaises(ValueError): migration.patches(self.app)
        self.assertEqual(changed, target.read_text())

    def test_dependency_plan_removes_only_the_prototype_and_preserves_other_requirements(self):
        before = (self.app / 'composer.json').read_bytes()
        manifest = migration.manifest_for(self.app)
        self.assertNotIn(migration.OLD, manifest['require'])
        self.assertEqual('*', manifest['require'][migration.PUBLIC])
        self.assertEqual('^9.2', manifest['require']['laravel/framework'])
        self.assertEqual(before, (self.app / 'composer.json').read_bytes())

    def test_path_escape_is_refused(self):
        with self.assertRaises(ValueError): migration.target(self.app, '../outside.env')

    def test_legacy_writers_refuse_a_public_package_application(self):
        guard.require_legacy_mode(self.app)
        path = self.app / 'composer.json'
        path.write_text(json.dumps({'require': {migration.PUBLIC: '*'}}))
        before = (self.app / '.env').read_bytes()
        with self.assertRaises(RuntimeError): guard.require_legacy_mode(self.app)
        self.assertEqual(before, (self.app / '.env').read_bytes())

    def test_recovery_restores_only_our_writes_and_preserves_concurrent_edits_and_environment(self):
        backup = self.app / 'private-backup'
        backup.mkdir()
        written = {}
        for relative in ['composer.json', migration.FILES[0]]:
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.app / relative, saved)
            (self.app / relative).write_text('our reviewed write')
            written[relative] = migration.digest(self.app / relative)
        (self.app / migration.FILES[0]).write_text('concurrent operator edit')
        environment = (self.app / '.env').read_bytes()
        self.assertTrue(migration.restore_written(self.app, backup, written))
        self.assertEqual((backup / 'composer.json').read_bytes(), (self.app / 'composer.json').read_bytes())
        self.assertEqual('concurrent operator edit', (self.app / migration.FILES[0]).read_text())
        self.assertEqual(environment, (self.app / '.env').read_bytes())


if __name__ == '__main__': unittest.main()
