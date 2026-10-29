"""Configure the installed Laravel adapter without replacing existing secrets."""
import json
import os
import secrets
from pathlib import Path
from integration_state import require_legacy_mode

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.verification' / 'laravel-connection.json'


def source_path():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    configured = os.environ.get('LARAVEL_APP_PATH') or state.get('source_path')
    if not configured:
        raise RuntimeError('Set LARAVEL_APP_PATH to the reviewed Laravel application directory.')
    source = Path(configured).expanduser().resolve()
    if not source.is_dir():
        raise RuntimeError('The configured Laravel application directory does not exist.')
    return source


def configure():
    target = source_path() / '.env'
    require_legacy_mode(target.parent)
    STATE.parent.mkdir(exist_ok=True)
    state = json.loads(STATE.read_text()) if STATE.exists() else {
        'source_url': os.environ.get('LARAVEL_SOURCE_URL', 'http://127.0.0.1:8081'),
        'hub_url': 'http://127.0.0.1:18000/mcp',
        'source_key': secrets.token_urlsafe(36),
        'delegation_secret': secrets.token_urlsafe(36),
    }
    state['source_path'] = str(target.parent)
    STATE.write_text(json.dumps(state, indent=2))
    original = target.read_bytes()
    backup = ROOT / '.verification' / 'laravel-backup' / '.env'
    if not backup.exists():
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
    values = {
        'MCP_HUB_ENABLED': 'true', 'MCP_HUB_URL': state['hub_url'],
        'MCP_HUB_TOKEN': state.get('token', ''), 'MCP_HUB_SOURCE_URL': state['source_url'],
        'MCP_HUB_SOURCE_KEY': state['source_key'], 'MCP_HUB_DELEGATION_SECRET': state['delegation_secret'],
    }
    lines = original.decode('utf-8-sig').splitlines()
    remaining = dict(values)
    result = []
    for line in lines:
        key = line.split('=', 1)[0].strip()
        if key in values:
            if key in remaining:
                result.append(key + '=' + remaining.pop(key))
        else:
            result.append(line)
    if remaining:
        result += ['', '# Private application data gateway; AI provider bridge remains separately configured.']
        result += [key + '=' + value for key, value in remaining.items()]
    target.write_bytes(('\n'.join(result) + '\n').encode())
    print('Laravel adapter configuration saved; secrets were not printed.')


if __name__ == '__main__':
    configure()
