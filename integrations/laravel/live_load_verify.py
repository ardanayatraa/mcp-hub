"""Exercise the local HiReach load fixture through the live MCP endpoint."""

import argparse
import hashlib
import hmac
import json
import secrets
from base64 import urlsafe_b64encode
from datetime import datetime, timedelta, timezone

import httpx
from configure import ROOT, STATE


def signed(secret: str, payload: dict) -> str:
    def encode(value: bytes) -> str:
        return urlsafe_b64encode(value).decode().rstrip("=")

    body = {**payload, "exp": int((datetime.now(timezone.utc) + timedelta(seconds=90)).timestamp())}
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return f"{encode(raw)}.{encode(digest)}"


def main(phase: str) -> None:
    state = json.loads(STATE.read_text())
    seed = json.loads((ROOT / ".verification/hireach-load-seed.json").read_text())
    actor_ids = {label: account["user_id"] for label, account in seed["accounts"].items()}
    meta = {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {}}
    calls = 0

    with httpx.Client(timeout=45, trust_env=False) as client:
        source_headers = {"Authorization": "Bearer " + state["source_key"]}
        health = client.get(state["source_url"] + "/api/ai/v1/health", headers=source_headers)
        assert health.status_code == 200, "HiReach source health failed"
        assert client.get(state["source_url"] + "/api/ai/v1/health").status_code == 401

        def rpc(method: str, params: dict, actor: str | None = None) -> dict:
            nonlocal calls
            calls += 1
            headers = {"Authorization": "Bearer " + state["token"],
                       "Origin": state["source_url"], "Accept": "application/json, text/event-stream",
                       "MCP-Protocol-Version": "2026-07-28", "MCP-Method": method}
            if method == "tools/call":
                headers["MCP-Name"] = params["name"]
            if actor is not None:
                user_id = actor_ids[actor]
                headers["X-Hub-Delegation"] = signed(state["delegation_secret"], {
                    "app_key": "hireach", "aud": "mcp-hub",
                    "tenant_id": f"hireach_account_{user_id}", "user_ref": f"hireach_user_{user_id}"})
            response = client.post(state["hub_url"], headers=headers, json={
                "jsonrpc": "2.0", "id": calls, "method": method,
                "params": {**params, "_meta": meta},
            })
            if response.status_code != 200:
                raise RuntimeError(f"{method} returned HTTP {response.status_code}: {response.text[:300]}")
            response.raise_for_status()
            payload = response.json()
            assert "error" not in payload, f"MCP RPC failed: {payload.get('error')}"
            return payload["result"]

        def tool(name: str, arguments: dict, actor: str | None, error: bool = False) -> dict:
            response = rpc("tools/call", {"name": name, "arguments": arguments}, actor)
            assert response.get("isError") is error, f"Unexpected MCP result for {name}: {response}"
            if error:
                return {"message": response["content"][0]["text"]}
            return response.get("structuredContent") or json.loads(response["content"][0]["text"])

        listed = rpc("tools/list", {})["tools"]
        names = {item["name"] for item in listed}
        expected = {"hireach__billing_users__list", "hireach__billing_users__count",
                    "hireach__blast_messages__list", "hireach__blast_messages__count",
                    "list_data_sources", "run_report"}
        assert expected <= names, f"Missing MCP tools: {expected - names}"

        report_path = ROOT / ".verification/hireach-load-verify.json"
        report = json.loads(report_path.read_text()) if report_path.exists() else {
            "message_prefix": seed["message_prefix"], "business_mutations": False, "phases": {}}
        report.setdefault("phases", {})
        phase_result = {"checked_at": datetime.now(timezone.utc).isoformat(), "source_health": "ok"}
        if phase == "smoke":
            sources = tool("list_data_sources", {}, "a")
            source_names = {row.get("source") for row in sources.get("data", [])}
            assert {"billing_users", "blast_messages", "templates"} <= source_names
            counts = {}
            for actor, expected_count in (("a", 1200), ("b", 300)):
                body = tool("hireach__blast_messages__count", {}, actor)
                counts[actor] = body["data"][0]["count"]
                assert counts[actor] == expected_count
                billing = tool("hireach__billing_users__count", {}, actor)
                assert billing["data"][0]["count"] == 1
                page = tool("hireach__blast_messages__list", {"limit": 50}, actor)
                assert len(page["data"]) == 50 and page["meta"]["total_count"] == expected_count
                for row in page["data"]:
                    assert row["title"].startswith("MCP Load " + actor.upper() + " ")
                    assert not {"tenant_id", "otp", "msisdn", "message_content"} & row.keys()

            assert "PERMISSION_DENIED" in tool("hireach__blast_messages__count", {}, None, error=True)["message"]
            assert tool("hireach__blast_messages__list", {"limit": 51}, "a", error=True)
            assert tool("hireach__billing_users__prepare_update", {"ref": "bogus"}, "a", error=True)
            templates = tool("hireach__templates__list", {}, "a")
            assert templates["meta"]["total_count"] == len(templates["data"]) == 20
            assert all({"ref", "name"} <= row.keys() for row in templates["data"])
            assert tool("hireach__templates__count", {}, "a")["data"][0]["count"] == 20
            first_template = templates["data"][0]
            detail = tool("hireach__templates__get", {"name": first_template["name"]}, "a")
            assert detail["data"][0]["name"] == first_template["name"]
            assert "PERMISSION_DENIED" in tool("hireach__templates__count", {}, None, error=True)["message"]
            for actor in ("a", "b"):
                billing_page = tool("hireach__billing_users__list", {}, actor)
                assert billing_page["meta"]["total_count"] == 1
                assert len(billing_page["data"]) == 1
            phase_result["visible_messages"] = counts
            print("Live MCP smoke: two account scopes, 1,500 visible messages, billing profiles, denied calls OK.", flush=True)

        if phase == "pages":
            refs = set()
            cursor = None
            page_count = 0
            while True:
                args = {"limit": 50}
                if cursor:
                    args["cursor"] = cursor
                page = tool("hireach__blast_messages__list", args, "a")
                page_count += 1
                assert page["meta"]["total_count"] == 1200
                for row in page["data"]:
                    assert row["title"].startswith("MCP Load A ")
                    assert row["ref"] not in refs
                    assert not {"tenant_id", "otp", "msisdn", "message_content"} & row.keys()
                    refs.add(row["ref"])
                cursor = page["meta"].get("next_cursor")
                assert page["meta"]["coverage"] == ("partial" if cursor else "complete")
                assert page["meta"]["has_more"] is bool(cursor)
                if cursor is None:
                    break
            assert len(refs) == 1200 and page_count == 24
            phase_result["pages_checked"] = page_count
            phase_result["unique_records"] = len(refs)
            print("Live MCP pagination: 24 pages, 1,200 unique own records OK.", flush=True)

        if phase == "reports":
            capped = tool("run_report", {"source": "blast_messages", "metrics": [{"fn": "count"}]}, "a")
            assert capped["data"]["totals"]["count"] == 1000
            assert capped["meta"]["coverage"] == "partial" and capped["meta"]["truncated"] is True
            complete = tool("run_report", {"source": "blast_messages", "metrics": [{"fn": "count"}]}, "b")
            assert complete["data"]["totals"]["count"] == 300
            assert complete["meta"]["coverage"] == "complete"
            for source, expected_count in (("templates", 20), ("billing_users", 1)):
                result = tool("run_report", {"source": source, "metrics": [{"fn": "count"}]}, "a")
                assert result["data"]["totals"]["count"] == expected_count
                assert result["meta"]["coverage"] == "complete"
            phase_result["report_cap"] = 1000
            phase_result["report_complete_count"] = 300
            print("Live MCP reports: 1,000-record cap and 300-record complete scan OK.", flush=True)

        if phase == "proposal":
            profile = tool("hireach__billing_users__list", {}, "a")["data"][0]
            assert profile["city"] == "Test City"
            ref = profile["ref"]

            def source_actor_headers(actor: str) -> dict:
                user_id = actor_ids[actor]
                return {**source_headers, "X-Hub-Assertion": signed(state["delegation_secret"], {
                    "app_key": "hireach", "aud": state["source_url"],
                    "tenant_id": f"hireach_account_{user_id}", "user_ref": f"hireach_user_{user_id}",
                    "jti": secrets.token_urlsafe(18)})}

            url = state["source_url"] + "/api/ai/v1/billing_users/prepare_update"
            change = {"ref": ref, "city": "Test City Proposed"}
            key = "mcp-load-profile-20261013"
            prepared = client.post(url, headers={**source_actor_headers("a"), "Idempotency-Key": key}, json=change)
            assert prepared.status_code == 200, f"Own proposal returned HTTP {prepared.status_code}"
            proposal = prepared.json()["data"][0]
            assert proposal["requires_confirmation"] is True and proposal["proposal_ref"].startswith("change_")
            repeat = client.post(url, headers={**source_actor_headers("a"), "Idempotency-Key": key}, json=change)
            assert repeat.status_code == 200 and repeat.json()["data"][0]["proposal_ref"] == proposal["proposal_ref"]
            conflict = client.post(url, headers={**source_actor_headers("a"), "Idempotency-Key": key},
                                   json={**change, "city": "Another City"})
            assert conflict.status_code == 409
            cross_owner = client.post(url, headers=source_actor_headers("b"), json=change)
            assert cross_owner.status_code == 403
            invalid = client.post(url, headers=source_actor_headers("a"), json={"ref": ref, "tax_id": "FORGED"})
            assert invalid.status_code in {403, 422}
            unchanged = tool("hireach__billing_users__list", {}, "a")["data"][0]
            assert unchanged["city"] == "Test City"
            phase_result["own_proposal_created"] = True
            phase_result["business_mutations"] = False
            print("Live HiReach proposal: own update, idempotency, conflict, owner denial, no commit OK.", flush=True)

        phase_result["mcp_calls"] = calls
        report["phases"][phase] = phase_result
        report_path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["smoke", "pages", "reports", "proposal"], default="smoke")
    main(parser.parse_args().phase)
