"""Install the local package in the reviewed local application; dry-run by default."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from integration_state import require_legacy_mode

parser = argparse.ArgumentParser()
parser.add_argument("--app", type=Path, required=True)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
source = args.app.resolve()
require_legacy_mode(source)
overlay = Path(__file__).parent / "overlay"
paths = [
    "app/Providers/AppServiceProvider.php",
    "app/Services/Mcp/McpClient.php",
    "app/Services/Mcp/HubPackageRegistry.php",
    "config/mcp-hub.php",
]
state_path = root / ".verification/laravel-installed-hashes.json"
hashes = json.loads(state_path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


for relative in paths:
    target = (source / relative).resolve()
    assert target.is_relative_to(source), "Target escaped application directory"
    expected = hashes.get(relative)
    assert digest(target) in (expected, digest(overlay / relative)), f"Application file changed: {relative}"
composer_path = source / "composer.json"
composer = json.loads(composer_path.read_text())
assert composer["require"]["laravel/framework"].startswith("^9"), "This pilot is reviewed for Laravel 9"
print("Plan: add Composer path dependency, package configuration, transport binding and registry adapter.")
print("Business models, saved grants, source routes, chat UI and environment credentials are preserved.")
if not args.apply:
    print("Dry-run passed; no application files changed.")
    raise SystemExit(0)

backup = root / ".verification/hireach-package-backup"
backup.mkdir(parents=True, exist_ok=True)
for relative in paths + ["composer.json", "composer.lock"]:
    original = source / relative
    saved = backup / relative
    if original.is_file() and not saved.exists():
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(original, saved)

repository = {"type": "path", "url": os.path.relpath(root / "integrations/laravel/package", source).replace("\\", "/"),
              "options": {"symlink": True}}
repositories = composer.setdefault("repositories", {})
if isinstance(repositories, list):
    if repository not in repositories:
        repositories.insert(0, repository)
else:
    repositories["mcp-hub-local"] = repository
composer["require"]["mcp-hub/laravel-connector"] = "dev-main"
composer_path.write_text(json.dumps(composer, indent=4) + "\n", encoding="utf-8")
# Disable package source routes before Composer discovery; the installed application owns these.
config_target = source / "config/mcp-hub.php"
shutil.copy2(overlay / "config/mcp-hub.php", config_target)
command = shutil.which("composer.bat") or shutil.which("composer")
assert command, "Composer is required"
composer_command = [command]
composer_phar = Path(command).parent / "composer.phar"
if os.name == "nt" and composer_phar.is_file():
    # Enable an installed extension for this process only; do not modify the host php.ini.
    composer_command = [shutil.which("php"), "-d", "extension=sockets", str(composer_phar)]
result = subprocess.run(composer_command + ["update", "mcp-hub/laravel-connector", "--no-scripts", "--no-interaction", "--prefer-dist", "--no-progress"],
                        cwd=source)
if result.returncode:
    shutil.copy2(backup / "composer.json", composer_path)
    shutil.copy2(backup / "composer.lock", source / "composer.lock")
    if (backup / "config/mcp-hub.php").exists():
        shutil.copy2(backup / "config/mcp-hub.php", config_target)
    else:
        config_target.unlink()
    raise SystemExit("Dependency installation failed; application configuration was restored.")

for relative in paths:
    assert digest(source / relative) in (hashes.get(relative), digest(overlay / relative)), f"Application changed during installation: {relative}"
for relative in paths:
    shutil.copy2(overlay / relative, source / relative)
    hashes[relative] = digest(source / relative)
shutil.copy2(composer_path, overlay / "composer.json")
hashes["composer.json"] = digest(composer_path)
state_path.write_text(json.dumps(hashes, indent=2) + "\n")
originals_path = root / ".verification/laravel-originals.json"
originals = json.loads(originals_path.read_text())
for relative in paths:
    originals.setdefault(relative, None)
originals_path.write_text(json.dumps(originals, indent=2) + "\n")
result = subprocess.run(composer_command + ["dump-autoload", "--no-interaction"], cwd=source)
if result.returncode:
    raise SystemExit("Package files installed, but autoload/discovery failed; inspect before using the app.")
print("Package installed locally. No business data, grants or credentials were changed.")
