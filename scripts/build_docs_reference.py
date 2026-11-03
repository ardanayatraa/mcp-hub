"""Render only selected public contracts; never publish internal evidence or environments."""
from pathlib import Path
import re
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "API.md": "admin-api.md",
    "CONNECTOR_CONTRACT.md": "connector-contract.md",
    "TOOLS.md": "tools.md",
    "CLIENT_PROFILES.md": "profiles.md",
}
for source, target in SOURCES.items():
    text = (ROOT / "docs" / source).read_text(encoding="utf-8")
    # Relative repository links must remain valid after moving into the portal.
    def rewrite(match):
        label, href = match.groups()
        if href.startswith(("https://", "http://", "#", "mailto:")):
            return match.group(0)
        resolved = urljoin("https://github.com/ardanayatraa/mcp-hub/blob/main/docs/", href)
        return f"[{label}]({resolved})"
    text = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", rewrite, text)
    heading, _, body = text.partition("\n")
    notice = ("\n\n!!! info \"Referensi teknis dalam bahasa Inggris\"\n"
              f"    Halaman ini disinkronkan otomatis dari [docs/{source}]"
              f"(https://github.com/ardanayatraa/mcp-hub/blob/main/docs/{source}) pada commit build. "
              "Panduan penggunaan berbahasa Indonesia tersedia melalui navigasi portal.\n\n")
    destination = ROOT / "documentation" / "reference" / target
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(heading + notice + body, encoding="utf-8", newline="\n")
    print(f"Synced {source} -> {target}")
