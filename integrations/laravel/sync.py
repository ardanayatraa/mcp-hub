"""Apply follow-up overlay fixes only to unchanged previously installed files."""
import argparse
import hashlib
import json
from pathlib import Path

from configure import source_path
from integration_state import require_legacy_mode

parser = argparse.ArgumentParser()
parser.add_argument('--check', action='store_true', help='Verify source hashes without changing files.')
args = parser.parse_args()

root = Path(__file__).resolve().parents[2]
state = root / '.verification' / 'laravel-installed-hashes.json'
hashes = json.loads(state.read_text())
source = source_path()
require_legacy_mode(source)
overlay = Path(__file__).parent / 'overlay'
originals = json.loads((root / '.verification/laravel-originals.json').read_text())
reviewed = json.loads((Path(__file__).parent / 'source-baselines.json').read_text())
paths = {file.relative_to(overlay).as_posix() for file in overlay.rglob('*') if file.is_file()}
removal_manifest = root / '.verification/laravel-package-removals.json'
removals = json.loads(removal_manifest.read_text()) if removal_manifest.exists() else []
rename_manifest = Path(__file__).parent / 'class-renames.json'
renames = json.loads(rename_manifest.read_text()) if rename_manifest.exists() else {}
consolidation_manifest = Path(__file__).parent / 'config-consolidations.json'
consolidations = json.loads(consolidation_manifest.read_text()) if consolidation_manifest.exists() else {}
assert set(renames.values()) <= paths and not set(renames) & paths, 'Invalid class rename manifest'
assert len(set(renames.values())) == len(renames), 'Duplicate rename targets'
assert set(consolidations.values()) <= paths and not set(consolidations) & (paths | set(renames)), 'Invalid config consolidation manifest'
assert all(old.startswith('config/') and old.endswith('.php') and new == 'config/ai.php' for old, new in consolidations.items()), 'Invalid config consolidation target'
archives = {}
assert not set(hashes) - paths - set(removals) - set(renames) - set(consolidations), 'Previously installed overlay file is missing'
rename_sources = {}
for old, new in {**renames, **consolidations}.items():
    target = (source / old).resolve()
    assert target.is_relative_to(source) and old in originals and new in originals, 'Unreviewed rename'
    assert old in consolidations or originals[new] is None, 'Rename destination was not originally absent'
    if target.exists():
        expected = hashes.get(old, originals[old])
        assert expected is not None and hashlib.sha256(target.read_bytes()).hexdigest() == expected, f'Source changed: {old}'
        backup = root / '.verification/laravel-backup' / old
        if originals[old] is not None:
            if old in hashes:
                assert backup.is_file() and hashlib.sha256(backup.read_bytes()).hexdigest() == originals[old], f'Original backup differs: {old}'
            else:
                assert not backup.exists(), f'Backup already exists: {old}'
        archive_folder = 'laravel-consolidated-configs' if old in consolidations else 'laravel-renamed-classes'
        archive = root / '.verification' / archive_folder / expected / old
        assert not archive.exists() or archive.read_bytes() == target.read_bytes(), f'Rename archive differs: {old}'
        rename_sources[old] = (target, backup, archive)
    else:
        assert old not in hashes and new in hashes, f'Rename source disappeared: {old}'
for path in removals:
    target = (source / path).resolve()
    assert target.is_relative_to(source) and originals.get(path, 'unreviewed') is None, 'Invalid generated-file move'
    if path in hashes:
        assert target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == hashes[path], f'Source changed: {path}'
        archive = root / '.verification/laravel-moved-adapter' / path
        if archive.exists() and archive.read_bytes() != target.read_bytes():
            archive = root / '.verification/laravel-moved-adapter' / hashes[path] / path
        assert not archive.exists() or archive.read_bytes() == target.read_bytes(), f'Move archive differs: {path}'
        archives[path] = archive
    else:
        assert not target.exists(), f'Moved file was recreated: {path}'
for path in paths:
    target = (source / path).resolve()
    assert target.is_relative_to(source), 'Invalid target path'
    assert path in originals or path in reviewed, f'Unreviewed new target: {path}'
    expected = hashes.get(path, originals.get(path, reviewed.get(path)))
    actual = hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
    installed = hashlib.sha256((overlay / path).read_bytes()).hexdigest()
    assert actual in (expected, installed), f'Source changed: {path}'
if args.check:
    print(f'Verified {len(paths)} installed adapter files; no source files changed.')
    raise SystemExit(0)
changed = 0
for path in sorted(paths):
    payload = (overlay / path).read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != hashes.get(path):
        target = source / path
        if not target.exists() or target.read_bytes() != payload:
            if path not in hashes and target.exists():
                backup = root / '.verification/laravel-backup' / path
                assert not backup.exists(), f'Backup already exists: {path}'
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(target.read_bytes())
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            changed += 1
        hashes[path] = digest
for old, (target, backup, archive) in rename_sources.items():
    if originals[old] is not None and old not in hashes:
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(target.read_bytes())
    if not archive.exists():
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(target.read_bytes())
    assert archive.read_bytes() == target.read_bytes(), 'Rename archive verification failed'
    target.unlink()
    hashes.pop(old, None)
for path in removals:
    if path in hashes:
        target = (source / path).resolve()
        archive = archives[path]
        if not archive.exists():
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(target.read_bytes())
        target.unlink()
        del hashes[path]
state.write_text(json.dumps(hashes, indent=2))
print(f'Updated {changed} adapter files; archived {len(rename_sources)} retired source files; source hashes verified.')
