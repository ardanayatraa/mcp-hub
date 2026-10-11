"""Reverify the fixes without touching the application's database.

Run from the repository root using backend/.venv/Scripts/python.exe.
The pre-fix probes and evidence remain archived separately.
"""

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
env = dict(os.environ)
env.pop("HUB_TEST_DATABASE_URL", None)
env["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
xml_path = ROOT / "docs" / "PRD_FIX_TESTS.xml"
commands = {
    "ruff": [sys.executable, "-m", "ruff", "check", "app", "tests"],
    "pytest": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={xml_path}"],
}
evidence = {"verified_at": datetime.now(timezone.utc).isoformat(), "database": "isolated SQLite", "checks": {}}
for name, command in commands.items():
    result = subprocess.run(command, cwd=BACKEND, env=env, capture_output=True, text=True, timeout=180)
    evidence["checks"][name] = {"exit_code": result.returncode, "passed": result.returncode == 0}
    print(result.stdout.strip())
    if result.returncode:
        print(result.stderr.strip())
if xml_path.exists():
    suites = ET.parse(xml_path).getroot()
    evidence["tests"] = [dict(row.attrib) for row in suites.iter("testsuite")]
    evidence["cases"] = [{"name": row.attrib["name"], "class": row.attrib["classname"], "passed": row.find("failure") is None and row.find("error") is None, "skipped": row.find("skipped") is not None} for row in suites.iter("testcase")]
evidence["limits"] = ["PostgreSQL and Docker jobs are configured in CI; no local Docker runtime is installed.", "Actual CI execution and production deployment are not claimed by this local verification."]
(ROOT / "docs" / "PRD_FIX_EVIDENCE.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
sys.exit(0 if all(row["passed"] for row in evidence["checks"].values()) else 1)
