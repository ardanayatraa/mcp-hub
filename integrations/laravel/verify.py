"""Verify source permissions and the read-only MCP catalog without reading records."""
import json
from datetime import datetime, timezone

import httpx
from configure import ROOT, STATE

state = json.loads(STATE.read_text())
with httpx.Client(timeout=30, trust_env=False) as client:
    source_headers = {'Authorization': 'Bearer ' + state['source_key']}
    health_url = state['source_url'] + '/api/ai/v1/health'
    health = client.get(health_url, headers=source_headers)
    health.raise_for_status()
    assert client.get(health_url).status_code == 401, 'Missing source credentials accepted'
    source = client.get(state['source_url'] + '/api/ai/v1/capabilities', headers=source_headers)
    source.raise_for_status()
    manifest = source.json()
    assert manifest.get('managed_by') == 'application', 'Source permissions are not application-managed'
    prefix = manifest['application'] + '__'
    headers = {'Authorization': 'Bearer ' + state['token'], 'Origin': state['source_url'],
               'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2026-07-28',
               'MCP-Method': 'tools/list'}
    meta = {'io.modelcontextprotocol/protocolVersion': '2026-07-28',
            'io.modelcontextprotocol/clientCapabilities': {}}
    response = client.post(state['hub_url'], headers=headers,
                           json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/list', 'params': {'_meta': meta}})
    response.raise_for_status()
    result = response.json()
    assert 'error' not in result, 'MCP discovery rejected'
    names = [tool['name'] for tool in result['result']['tools']]
    current = sorted(name for name in names if name.startswith(prefix))
    expected = sorted(route['tool_key'].replace('.', '__') for module in manifest['modules']
                      for route in module.get('read_endpoints', []))
    # Verify the existing read-only gateway key without widening its scope.
    assert current == expected, 'Read-only gateway catalog differs from current source permissions'
    report = {'checked_at': datetime.now(timezone.utc).isoformat(), 'source_health': 'ok',
              'source_models': [module['key'] for module in manifest['modules']],
              'published_tool_count': len(current), 'source_and_mcp_match': True,
              'source_missing_key_rejected': True, 'business_rows_read': False,
              'business_mutations': False}
    path = ROOT / 'docs/evidence/LARAVEL_INTEGRATION_EVIDENCE.json'
    evidence = json.loads(path.read_text()) if path.exists() else {}
    evidence.update({'source_health': report['source_health'], 'published_tool_count': len(current),
                     'live_catalog': report})
    path.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f"Source catalog verified: {len(report['source_models'])} models, {len(current)} read tools; no business rows read.")
