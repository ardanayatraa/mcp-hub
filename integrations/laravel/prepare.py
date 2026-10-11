"""Validate reviewed source before installing the native Laravel classes."""
import hashlib
import json
from pathlib import Path

from configure import source_path

root = Path(__file__).resolve().parents[2]
source = source_path()
integration = Path(__file__).parent
overlay = integration / 'overlay'
verification = root / '.verification'
if (verification / 'laravel-installed-hashes.json').exists():
    raise RuntimeError('Integration is already installed; use guarded sync.py for reviewed follow-ups.')
baselines = json.loads((integration / 'source-baselines.json').read_text())
renames = json.loads((integration / 'class-renames.json').read_text())
consolidations = json.loads((integration / 'config-consolidations.json').read_text())
paths = {file.relative_to(overlay).as_posix() for file in overlay.rglob('*') if file.is_file()}
assert set(baselines) == paths | set(renames) | set(consolidations), 'Reviewed source manifest does not match the overlay'
for relative, expected in baselines.items():
    target = (source / relative).resolve()
    assert target.is_relative_to(source), 'Invalid source path'
    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    assert actual == expected, f'Source changed; review before installing: {relative}'
verification.mkdir(parents=True, exist_ok=True)
(verification / 'laravel-originals.json').write_text(json.dumps(baselines, indent=2), encoding='utf-8')
print(f'Validated {len(paths)} reviewed source files; class renames preserve existing logic.')
