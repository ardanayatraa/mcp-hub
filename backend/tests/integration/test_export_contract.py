"""The public Laravel package's generated export contract through actual Hub dispatch."""

import json
from pathlib import Path

import httpx
from tests import helpers
from tests.helpers import api, call, delegation, issue_key, listed, result


def test_source_owned_exports_are_read_only_actor_scoped_jobs_with_idempotency(admin, monkeypatch):
    manifest = json.loads((Path(__file__).parents[1] / "fixtures/laravel_export_contract.json").read_text())
    monkeypatch.setattr(helpers, "MANIFEST", manifest)
    helpers.dns(monkeypatch)
    reference = "exp_" + "a" * 48
    posted = []

    def handler(request):
        if "/orders/exports" not in request.url.path:
            return helpers.handler(request)
        assert request.headers["Authorization"] == f"Bearer {helpers.API_KEY}"
        assert helpers._assertion_tenant(request) == "demo_account_1"
        if request.method == "POST":
            posted.append(request)
            assert request.headers["Idempotency-Key"].startswith("tr_")
            assert json.loads(request.content) == {"format": "csv"}
        return httpx.Response(200, json={"success": True, "data": [{
            "export_ref": reference, "status": "ready", "format": "csv", "expires_at": "2026-10-29T06:00:00+00:00",
            "coverage": "complete", "row_count": 1, "download_url": f"http://projects.test/mcp-hub/exports/{reference}",
            "tenant_id": "demo_account_1"}], "meta": helpers.META})

    with helpers.source(handler):
        app = api(admin, "POST", "/connectors", {
            "name": "Source reports", "app_key": "your_app", "environment": "dev", "connector_type": "source_managed",
            "base_url": "http://projects.test", "auth_type": "bearer", "secret": helpers.API_KEY,
            "delegation_secret": helpers.DELEGATION_SECRET}, expect=201).json()["data"]
        for action in ["test", "discover", "activate"]:
            api(admin, "POST", f"/connectors/{app['id']}/{action}", expect=200)
        reader = issue_key(admin)
        names = listed(admin["client"], reader)
        assert "your_app__orders__export" in names and "your_app__orders__export_status" in names
        actor = delegation(tenant="demo_account_1", user="demo_user_1")
        receipt = result(call(admin["client"], reader, "your_app__orders__export", {"format": "csv"}, actor))
        assert receipt["data"][0]["export_ref"] == reference
        assert "tenant_id" not in receipt["data"][0]
        assert "file" not in receipt["data"][0] and len(posted) == 1
        status = result(call(admin["client"], reader, "your_app__orders__export_status", {"export_ref": reference}, actor))
        assert status["data"][0]["status"] == "ready"
