"""Optional connection helper. Models and permissions are owned by the source application."""
import json
import os
from datetime import datetime, timezone

import httpx
from configure import STATE, configure


def endpoints(module):
    for route in module.get('read_endpoints', []):
        yield 'read', route
    for route in module.get('write_endpoints', []):
        yield route['operation'], route


state = json.loads(STATE.read_text())
hub = state['hub_url'].removesuffix('/mcp')
client = httpx.Client(base_url=hub, timeout=30, trust_env=False)


def request(method, path, body=None):
    response = client.request(method, '/api/admin/v1' + path, json=body)
    if response.status_code >= 400:
        raise RuntimeError(f'{method} {path}: HTTP {response.status_code}, '
                           f"{response.json().get('error', {}).get('code', 'REJECTED')}")
    return response.json()['data']


login = request('POST', '/auth/login', {'email': os.environ.get('HUB_ADMIN_EMAIL', 'admin@localhost'),
                                      'password': os.environ['HUB_ADMIN_PASSWORD']})
client.headers['X-CSRF-Token'] = login['csrf_token']
source = httpx.Client(base_url=state['source_url'], headers={'Authorization': 'Bearer ' + state['source_key']},
                     timeout=15, trust_env=False)
assert source.get('/api/ai/v1/health').status_code == 200, 'Source health check failed'
manifest_response = source.get('/api/ai/v1/capabilities')
assert manifest_response.status_code == 200, 'Source manifest request failed'
manifest = manifest_response.json()
assert manifest.get('managed_by') == 'application', 'The source must publish its saved grants'
app_key = manifest['application']
prefix = app_key + '__'
existing = request('GET', '/connectors')
connector = next((c for c in existing if c['app_key'] == app_key and c['environment'] == 'dev'), None)
if connector is None:
    connector = request('POST', '/connectors', {
        'name': state.get('app_name', 'Laravel application'), 'app_key': app_key, 'environment': 'dev', 'connector_type': 'source_managed',
        'base_url': state['source_url'], 'auth_type': 'bearer', 'secret': state['source_key'],
        'delegation_secret': state['delegation_secret'], 'timeout_ms': 5000,
    })
cid = connector['id']
assert connector['base_url'] == state['source_url'], 'Existing connector uses another source'
if connector['connector_type'] != 'source_managed':
    request('PATCH', f'/connectors/{cid}', {'connector_type': 'source_managed'})
assert request('POST', f'/connectors/{cid}/test')['status'] == 'ok', 'Connector health failed'
request('POST', f'/connectors/{cid}/discover')
request('POST', f'/connectors/{cid}/activate')
if not state.get('token'):
    identity = request('POST', '/service-identities', {'name': 'Application gateway', 'app_key': app_key,
                                                     'environment': 'dev', 'ttl_days': 90})
    state.update({'token': identity['token'], 'identity_id': identity['id'], 'expires_at': identity['expires_at']})
    STATE.write_text(json.dumps(state, indent=2))
configure()
listed = client.post('/mcp', headers={'Authorization': 'Bearer ' + state['token'], 'Origin': state['source_url'],
                                    'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28',
                                    'MCP-Method': 'tools/list'},
                     json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {'_meta': {
                         'io.modelcontextprotocol/protocolVersion': '2026-07-28',
                         'io.modelcontextprotocol/clientCapabilities': {}}}})
assert listed.status_code == 200, 'MCP discovery failed'
names = [t['name'] for t in listed.json()['result']['tools']]
custom = [name for name in names if name.startswith(prefix)]
expected = {endpoint['tool_key'].replace('.', '__')
            for module in manifest['modules'] for template, endpoint in endpoints(module) if template == 'read'}
assert expected <= set(custom) and all(name.startswith(prefix) or name in {'list_data_sources', 'run_report'} for name in names), 'MCP identity scope failed'
proof_path = STATE.parents[1] / 'docs' / 'evidence' / 'LARAVEL_INTEGRATION_EVIDENCE.json'
result = json.loads(proof_path.read_text()) if proof_path.exists() else {}
result.update({'source_health': 'ok', 'published_tool_count': len(custom), 'identity_scoped': True,
               'checked_at': datetime.now(timezone.utc).isoformat()})
result['permission_management'] = 'source_managed'
proof_path.write_text(json.dumps(result, indent=2))
print(f'MCP discovery verified: {len(expected)} registered source tools; secrets withheld.')
