"""Check the running dummy source against the actual Hub validator and authorization boundary."""
import base64
import hashlib
import hmac
import json
import re
from pathlib import Path
import sys
import time
import uuid

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root / "backend"))
import httpx
from app.connectors.contracts import validate_manifest

base = "http://127.0.0.1:18120"
source_token = "dummy-source-token-at-least-32-characters"
secret = b"dummy-delegation-secret-at-least-32-characters"
client = httpx.Client(base_url=base, headers={"Authorization": "Bearer " + source_token}, trust_env=False)
manifest = client.get("/api/ai/v1/capabilities")
manifest.raise_for_status()
validated = validate_manifest(manifest.json(), expected_app_key="your_app", source_managed=True)
assert len(validated["modules"]) == 1


def assertion(actor):
    body = json.dumps({"app_key": "your_app", "user_ref": f"demo_user_{actor}", "tenant_id": f"demo_account_{actor}",
                       "aud": base, "exp": int(time.time()) + 60, "jti": uuid.uuid4().hex}, separators=(",", ":")).encode()
    encode = lambda value: base64.urlsafe_b64encode(value).rstrip(b"=").decode()
    return encode(body) + "." + encode(hmac.new(secret, body, hashlib.sha256).digest())


for actor in (1, 2):
    token = assertion(actor)
    response = client.get("/api/ai/v1/orders/list", headers={"X-Hub-Assertion": token})
    response.raise_for_status()
    rows = response.json()["data"]
    assert len(rows) == 2 and all(row["tenant_id"] == f"demo_account_{actor}" for row in rows)
    assert all("private_note" not in row for row in rows)
    assert client.get("/api/ai/v1/orders/list", headers={"X-Hub-Assertion": token}).status_code == 403
assert httpx.get(base + "/api/ai/v1/health", trust_env=False).status_code == 401
assert client.get("/api/ai/v1/orders/list").status_code == 403
web = httpx.Client(base_url=base, follow_redirects=True, trust_env=False)
for actor, own, other in ((1, "Ari", "Bima"), (2, "Bima", "Ari")):
    page = web.get("/")
    csrf = re.search(r'name="_token" value="([^"]+)"', page.text).group(1)
    page = web.post("/demo/login", data={"_token": csrf, "user": actor})
    csrf = re.search(r'name="_token" value="([^"]+)"', page.text).group(1)
    page = web.post("/demo/read", data={"_token": csrf})
    assert page.status_code == 200 and "Order " + own + " 1" in page.text
    assert "Order " + other + " 1" not in page.text
print("PASS: HTTP source, Hub validator, account scopes, field allowlist, replay denial and web demo for both users.")
