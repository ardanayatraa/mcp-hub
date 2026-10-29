"""Refuse prototype maintenance after the reviewed public-package cutover."""
import json


def require_legacy_mode(source):
    manifest = json.loads((source / 'composer.json').read_text(encoding='utf-8'))
    if 'ardanayatraa/laravel-mcp-hub' in manifest.get('require', {}):
        raise RuntimeError('Public package is installed. Legacy overlay/configuration writes are refused; use the public migration guide.')
