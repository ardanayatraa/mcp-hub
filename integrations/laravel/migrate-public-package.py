"""Reviewed pilot migration from the private prototype to the public Composer package.

Dry-run by default. Never copies, generates or rewrites the application's .env.
The source application retains its routes, grants, models, chat and business handlers.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

OLD = 'mcp-hub/laravel-connector'
PUBLIC = 'ardanayatraa/laravel-mcp-hub'
ROOT = Path(__file__).resolve().parents[2]
FILES = ['app/Services/Mcp/McpActorIdentity.php', 'app/Http/Controllers/McpConnectorController.php', 'app/Services/Mcp/McpClient.php']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def target(app, relative):
    path = (app / relative).resolve()
    if not path.is_relative_to(app):
        raise ValueError('Migration target escapes the application directory.')
    return path


def patches(app):
    identity = target(app, FILES[0]).read_text(encoding='utf-8')
    old = """        // One use only: a captured assertion cannot be replayed while it is still valid (atomic add).
        if (! Cache::add('hireach.hub.assertion.'.hash('sha256', $payload['jti']), 1, $payload['exp'] - time() + 5)) {
            throw new RuntimeException('Hub assertion denied.');
        }"""
    new = """        // Durable, atomic replay protection shared by every application worker.
        app(\\McpHub\\Laravel\\Security\\NonceStore::class)->consume(
            hash('sha256', 'hireach|'.$payload['jti']), $payload['exp'] + 5);"""
    if old in identity:
        identity = identity.replace(old, new, 1).replace('use Illuminate\\Support\\Facades\\Cache;\n', '')
    elif new not in identity:
        raise ValueError('Actor verification changed; review it before migrating.')
    controller = target(app, FILES[1]).read_text(encoding='utf-8')
    old_health = "        return $this->authenticated($request) ? $this->json(['status' => 'ok']) : $this->denied(401);"
    new_health = """        if (! $this->authenticated($request)) { return $this->denied(401); }
        $checks = app(\\McpHub\\Laravel\\Support\\Metadata::class)->inspect();
        $ready = ! in_array(false, $checks, true);
        return $this->json(['status' => $ready ? 'ok' : 'not_ready', 'checks' => $checks], $ready ? 200 : 503);"""
    if old_health in controller:
        controller = controller.replace(old_health, new_health, 1)
    elif new_health not in controller:
        raise ValueError('Source health changed; review it before migrating.')
    client = target(app, FILES[2]).read_text(encoding='utf-8')
    old_client = """        if ($connection === 'hub') {
            return app(\\McpHub\\Laravel\\HubClient::class)->rpc($method, $params, $headers);
        }"""
    new_client = """        if ($connection === 'hub') {
            // The public SDK encodes empty argument arrays as JSON objects itself.
            if (($params['arguments'] ?? null) instanceof \\stdClass && get_object_vars($params['arguments']) === []) {
                $params['arguments'] = [];
            }
            try {
                return app(\\McpHub\\Laravel\\HubClient::class)->rpc($method, $params, $headers);
            } catch (\\Throwable $error) {
                throw new RuntimeException($error->getMessage() === 'MCP Hub connection is not configured.'
                    ? 'MCP connection is not configured.' : 'MCP request failed.');
            }
        }"""
    if old_client in client:
        client = client.replace(old_client, new_client, 1)
    elif new_client not in client:
        raise ValueError('Hub client bridge changed; review it before migrating.')
    return {FILES[0]: identity, FILES[1]: controller, FILES[2]: client}


def manifest_for(app, local_package=None):
    manifest = json.loads(target(app, 'composer.json').read_text(encoding='utf-8'))
    requirements = manifest.get('require', {})
    if OLD not in requirements and PUBLIC not in requirements:
        raise ValueError('This migration is only for the reviewed prototype pilot.')
    requirements.pop(OLD, None)
    requirements[PUBLIC] = 'dev-feature/stable-1.0' if local_package else '*'
    repositories = manifest.get('repositories', {})
    if isinstance(repositories, dict):
        repositories.pop('mcp-hub-local', None)
    else:
        repositories = [row for row in repositories if not (row.get('type') == 'path'
            and 'integrations/laravel/package' in str(row.get('url', '')).replace('\\', '/'))]
    if local_package:
        package = Path(local_package).resolve()
        document = json.loads((package / 'composer.json').read_text())
        if document.get('name') != PUBLIC or not (package / 'src/Security/NonceStore.php').is_file():
            raise ValueError('Local package is not the reviewed public implementation.')
        repository = {'type': 'path', 'url': os.path.relpath(package, app).replace('\\', '/'),
            'options': {'symlink': True, 'versions': {PUBLIC: 'dev-feature/stable-1.0'}}}
        if isinstance(repositories, dict): repositories['mcp-hub-local'] = repository
        else: repositories.insert(0, repository)
    manifest['repositories'] = repositories
    return manifest


def restore_written(app, backup, written):
    """Restore our exact writes only; retain concurrent operator edits."""
    conflict = False
    for relative, expected in written.items():
        saved = backup / relative
        if digest(target(app, relative)) != expected:
            conflict = True
            continue
        if saved.is_file():
            shutil.copy2(saved, target(app, relative))
    return conflict


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--local-package', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--force-metadata', action='store_true', help='Explicitly allow reviewed production package migrations')
    args = parser.parse_args()
    app = args.app.resolve()
    changes = patches(app)
    if not target(app, 'config/mcp-hub.php').is_file():
        raise ValueError('The reviewed prototype configuration must already exist.')
    manifest = manifest_for(app, args.local_package)
    if manifest['require'].get('laravel/framework', '').startswith('^9') is False:
        raise ValueError('This application adapter is reviewed for Laravel 9; use the generic package guide elsewhere.')
    files = FILES + ['composer.json', 'composer.lock', 'config/mcp-hub.php']
    before = {relative: digest(target(app, relative)) for relative in files}
    environment_before = digest(target(app, '.env'))
    print('Plan: replace the prototype dependency, install package-only metadata, and enable durable replay/readiness.')
    print('Existing application models, grants, source routes, chat, proposals, reports and config files are retained.')
    if not args.apply:
        print('Dry-run passed; no application files or database changed.')
        return
    backup = ROOT / '.verification/public-package-migrations' / uuid4().hex
    backup.mkdir(parents=True, mode=0o700)
    if not backup.resolve().is_relative_to(ROOT / '.verification'):
        raise ValueError('Backup directory escaped the verification workspace.')
    for relative in files:
        original = target(app, relative)
        if original.is_file():
            saved = backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, saved)
    php = shutil.which('php')
    composer = Path('C:/ProgramData/ComposerSetup/bin/composer.phar') if os.name == 'nt' else None
    command = [php, '-d', 'extension=sockets', str(composer)] if composer and composer.is_file() else [shutil.which('composer')]
    if not php or not command[0]: raise ValueError('PHP and Composer are required.')

    def run(arguments, name, executable=None):
        with (backup / (name + '.log')).open('wb') as output:
            result = subprocess.run((executable or command) + arguments, cwd=app, stdout=output, stderr=output)
        if digest(target(app, '.env')) != environment_before:
            raise RuntimeError('Application environment changed; stop and inspect the private migration log.')
        if result.returncode:
            raise RuntimeError(name + ' failed; inspect the private migration log.')

    written = {}
    try:
        target(app, 'composer.json').write_text(json.dumps(manifest, indent=4) + '\n', encoding='utf-8')
        written['composer.json'] = digest(target(app, 'composer.json'))
        try:
            run(['update', OLD, PUBLIC, 'guzzlehttp/guzzle', '--with-dependencies', '--no-scripts', '--no-plugins',
                 '--no-interaction', '--no-progress'], 'dependencies')
        finally:
            written['composer.lock'] = digest(target(app, 'composer.lock'))
        arguments = ['artisan', 'mcp-hub:install', '--migrate', '--no-interaction']
        if args.force_metadata: arguments.append('--force')
        run(arguments, 'package-metadata', [php, '-d', 'extension=sockets'] if os.name == 'nt' else [php])
        # Refuse concurrent edits. .env and existing package configuration are never written.
        for relative in FILES + ['config/mcp-hub.php']:
            if digest(target(app, relative)) != before[relative]:
                raise RuntimeError('Application changed during migration; source patches were not applied.')
        for relative, content in changes.items():
            target(app, relative).write_text(content, encoding='utf-8')
            written[relative] = digest(target(app, relative))
        run(['artisan', 'package:discover', '--no-interaction'], 'discovery', [php])
    except Exception:
        conflict = restore_written(app, backup, written)
        # Config and .env are read-only, including during recovery. Concurrent user
        # edits are retained; never reinstall dependencies over a changed manifest.
        try:
            if conflict: raise RuntimeError('Concurrent edits require review.')
            run(['install', '--no-scripts', '--no-plugins', '--no-interaction', '--no-progress'], 'restore-dependencies')
        except Exception:
            print('Dependency restoration needs operator review. Existing credentials were not rewritten.')
        raise
    evidence = {'status': 'applied', 'environment_unchanged': digest(target(app, '.env')) == environment_before,
        'configuration_unchanged': digest(target(app, 'config/mcp-hub.php')) == before['config/mcp-hub.php'],
        'files': {relative: digest(target(app, relative)) for relative in files}, 'backup': str(backup)}
    (backup / 'result.json').write_text(json.dumps(evidence, indent=2))
    print('Public package migration applied; credentials/config preserved. Backups and logs remain private in .verification.')


if __name__ == '__main__':
    main()
