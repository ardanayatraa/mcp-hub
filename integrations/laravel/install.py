"""Install a reviewed overlay and archive approved class rename sources."""
import argparse
import hashlib
import json
from pathlib import Path

from configure import source_path
from integration_state import require_legacy_mode

parser = argparse.ArgumentParser()
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
source = source_path()
require_legacy_mode(source)
integration = Path(__file__).parent
overlay = integration / 'overlay'
verification = root / '.verification'
if (verification / 'laravel-installed-hashes.json').exists():
    raise RuntimeError('Integration is already installed; use guarded sync.py for reviewed follow-ups.')
originals = json.loads((verification / 'laravel-originals.json').read_text())
renames = json.loads((integration / 'class-renames.json').read_text())
consolidations = json.loads((integration / 'config-consolidations.json').read_text())
paths = {file.relative_to(overlay).as_posix() for file in overlay.rglob('*') if file.is_file()}
assert set(originals) == paths | set(renames) | set(consolidations), 'Unreviewed installation targets'
assert set(renames.values()) <= paths and not set(renames) & paths, 'Invalid class rename manifest'
assert set(consolidations.values()) <= paths and not set(consolidations) & (paths | set(renames)), 'Invalid config consolidation manifest'
assert all(old.startswith('config/') and old.endswith('.php') and new == 'config/ai.php' for old, new in consolidations.items()), 'Invalid config consolidation target'
for relative, expected in originals.items():
    target = (source / relative).resolve()
    assert target.is_relative_to(source), 'Invalid target path'
    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.is_file() else None
    assert actual == expected, f'Source changed; no files replaced: {relative}'
    if expected is not None:
        saved = verification / 'laravel-backup' / relative
        assert not saved.exists(), f'Backup already exists: {relative}'
if args.apply:
    for relative, expected in originals.items():
        if expected is not None:
            saved = verification / 'laravel-backup' / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            saved.write_bytes((source / relative).read_bytes())
    for relative in sorted(paths):
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((overlay / relative).read_bytes())
    for old in set(renames) | set(consolidations):
        target = (source / old).resolve()
        if target.exists():
            saved = verification / 'laravel-backup' / old
            assert saved.read_bytes() == target.read_bytes(), 'Rename backup differs'
            target.unlink()
    installed = {relative: hashlib.sha256((source / relative).read_bytes()).hexdigest() for relative in paths}
    (verification / 'laravel-installed-hashes.json').write_text(json.dumps(installed, indent=2), encoding='utf-8')
print(f"{'Installed' if args.apply else 'Validated'} {len(paths)} files; {len(renames)} reviewed class renames.")
