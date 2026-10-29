import json
from datetime import timedelta

import httpx
import pytest
from app.ids import utcnow
from app.persistence.models import (
    AdminApplicationScope,
    AdminUser,
    Connector,
    ConnectorEnrollment,
    ConnectorSecret,
    ServiceIdentity,
)
from app.persistence.session import open_session
from sqlalchemy import select
from tests import helpers
from tests.helpers import api

PROOF = {"installation_id": "installation_dummy_123456", "attempt_id": "attempt_dummy_123456",
         "proof": "dummy_management_proof_" + "a" * 43}


def create(admin):
    return api(admin, "POST", "/connector-enrollments", {
        "name": "Your App", "app_key": "your_app", "environment": "dev", "base_url": "https://app.example.com",
    }, expect=201).json()["data"]


def test_key_rotation_keeps_unclaimed_pairing_bundle_usable_without_previous_key(admin, monkeypatch):
    from app.config import get_settings
    from app.rotate_keys import rotate
    from cryptography.fernet import Fernet

    helpers.dns(monkeypatch)
    enrollment = create(admin)
    old = get_settings().secret_encryption_key
    monkeypatch.setattr(get_settings(), "secret_encryption_key", Fernet.generate_key().decode())
    monkeypatch.setattr(get_settings(), "secret_encryption_key_previous", old)
    with open_session() as db:
        assert rotate(db) >= 3
        db.commit()
    monkeypatch.setattr(get_settings(), "secret_encryption_key_previous", "")
    assert claim(admin, enrollment).status_code == 200


def claim(admin, enrollment, **extra):
    return admin["client"].post("/api/connect/v1/enrollments/claim",
                               json={**PROOF, "code": enrollment["code"], **extra})


def controlled_source(request):
    if request.url.path.endswith("/health"):
        return httpx.Response(200, json={"status": "ok"})
    if request.url.path.endswith("/capabilities"):
        return httpx.Response(200, json={"contract_version": "1.0", "application": "your_app",
                                         "managed_by": "application", "modules": []})
    return httpx.Response(501)


def test_one_use_claim_and_status_never_return_secrets_again(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    first = claim(admin, enrollment)
    assert first.status_code == 200, first.text
    bundle = first.json()["data"]["connection"]
    assert len(bundle["app_token"]) >= 32 and len(bundle["delegation_secret"]) >= 32
    assert bundle["source_url"] == "https://app.example.com"
    assert bundle["url"] == "http://testserver/mcp"
    assert claim(admin, enrollment).status_code == 409
    assert claim(admin, enrollment, installation_id="other_installation_123456").status_code == 409
    status = admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/status", json=PROOF)
    assert status.status_code == 200
    assert status.json()["data"]["status"] == "claimed"
    assert bundle["client_key"] not in status.text
    assert "connection" not in status.json()["data"]
    assert bundle["app_token"] not in api(admin, "GET", f"/connector-enrollments/{enrollment['id']}").text
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment["id"])
        assert row.bundle_ciphertext is None and row.code_hash != enrollment["code"]
        identity = db.get(ServiceIdentity, row.identity_id)
        assert identity.scopes == ["mcp:tools"] and identity.token_hash != bundle["client_key"]
        from app.security.clients import resolve_caller
        assert resolve_caller(db, bundle['client_key']) is None


def test_pairing_requires_current_source_checks_and_is_repeatable_after_activation(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    assert claim(admin, enrollment).status_code == 200
    endpoint = f"/api/connect/v1/enrollments/{enrollment['id']}"
    with helpers.source(controlled_source):
        completed = admin["client"].post(endpoint + "/complete", json=PROOF)
        assert completed.status_code == 200, completed.text
        assert completed.json()["data"]["status"] == "active"
        again = admin["client"].post(endpoint + "/complete", json=PROOF)
        assert again.status_code == 200 and again.json()["data"] == completed.json()["data"]
        synced = admin["client"].post(endpoint + "/sync", json=PROOF)
        assert synced.status_code == 200, synced.text
    with open_session() as db:
        assert len(list(db.scalars(select(ServiceIdentity)))) == 1
        assert db.get(Connector, enrollment["connector_id"]).status == "active"


def test_wrong_proof_binding_or_runtime_client_key_cannot_manage_connection(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    bundle = claim(admin, enrollment).json()["data"]["connection"]
    for change in [{"proof": "b" * 43}, {"installation_id": "other_installation_123"},
                   {"attempt_id": "other_attempt_123456"}]:
        response = admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/status", json={**PROOF, **change})
        assert response.status_code == 401
    response = admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/complete",
                                    headers={"Authorization": "Bearer " + bundle["client_key"]}, json={})
    assert response.status_code == 422
    changed_source = claim(admin, enrollment, source_url="https://other.example.com")
    assert changed_source.status_code == 422


def test_expired_claim_revokes_the_pending_key_and_clears_the_bundle(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment["id"])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    assert claim(admin, enrollment).status_code == 410
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment["id"])
        assert row.status == "expired" and row.bundle_ciphertext is None
        assert db.get(ServiceIdentity, row.identity_id).revoked_at is not None


def test_failure_does_not_activate_and_can_resume_after_source_is_fixed(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    endpoint = f"/api/connect/v1/enrollments/{enrollment['id']}/complete"
    with helpers.source(lambda _request: httpx.Response(401)):
        assert admin["client"].post(endpoint, json=PROOF).status_code == 422
    with open_session() as db:
        assert db.get(ConnectorEnrollment, enrollment["id"]).status == "failed"
        assert db.get(Connector, enrollment["connector_id"]).status == "draft"
    with helpers.source(controlled_source):
        assert admin["client"].post(endpoint, json=PROOF).json()["data"]["status"] == "active"


def test_revoke_is_idempotent_and_prevents_further_status_or_completion(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    for _ in range(2):
        assert api(admin, "POST", f"/connector-enrollments/{enrollment['id']}/revoke").status_code == 200
    assert admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/status", json=PROOF).status_code == 410


def test_enrollment_creation_requires_admin_csrf_and_does_not_accept_write_grants(admin, monkeypatch):
    helpers.dns(monkeypatch)
    body = {"name": "Your App", "app_key": "your_app", "environment": "dev", "base_url": "https://app.example.com"}
    assert admin["client"].post("/api/admin/v1/connector-enrollments", json=body).status_code == 403
    assert api(admin, "POST", "/connector-enrollments", {**body, "write": True}).status_code == 422
    assert api(admin, "POST", "/connector-enrollments", {**body, "base_url": "http://169.254.169.254"}).status_code == 422


def test_claim_responses_do_not_contain_a_management_or_admin_session_credential(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    result = claim(admin, enrollment).json()["data"]
    assert "proof" not in result and "csrf" not in json.dumps(result)
    assert result["connection"]["connector_id"] == enrollment["connector_id"]


def test_changed_source_binding_cannot_complete(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    with open_session() as db:
        db.get(Connector, enrollment["connector_id"]).base_url = "https://other.example.com"
        db.commit()
    assert admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/complete", json=PROOF).status_code == 403


def test_disabled_creator_cannot_finish_a_previously_issued_enrollment(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment["id"])
        db.get(AdminUser, row.created_by).is_active = False
        db.commit()
    assert admin["client"].post(f"/api/connect/v1/enrollments/{enrollment['id']}/complete", json=PROOF).status_code == 403


def test_lost_claim_can_be_replaced_without_recovering_or_expanding_old_credentials(admin, monkeypatch):
    helpers.dns(monkeypatch)
    old = create(admin)
    old_bundle = claim(admin, old).json()["data"]["connection"]
    replacement = api(admin, "POST", f"/connector-enrollments/{old['id']}/replace", expect=201).json()["data"]
    assert replacement['connector_id'] == old['connector_id']
    assert api(admin, "POST", f"/connector-enrollments/{old['id']}/replace", expect=409).status_code == 409
    bundle = claim(admin, replacement).json()["data"]["connection"]
    assert bundle['app_token'] != old_bundle['app_token'] and bundle['client_key'] != old_bundle['client_key']
    # Repeating revocation of the old enrollment must not pause/revoke the replacement.
    api(admin, "POST", f"/connector-enrollments/{old['id']}/revoke")
    with helpers.source(controlled_source):
        response = admin['client'].post(f"/api/connect/v1/enrollments/{replacement['id']}/complete", json=PROOF)
        assert response.status_code == 200, response.text
    with open_session() as db:
        row = db.get(ConnectorEnrollment, replacement['id'])
        identity = db.get(ServiceIdentity, row.identity_id)
        assert identity.scopes == ['mcp:tools'] and identity.expires_at is not None
        assert db.get(Connector, row.connector_id).status == 'active'
        assert db.get(ServiceIdentity, db.get(ConnectorEnrollment, old['id']).identity_id).revoked_at is not None


@pytest.mark.parametrize("enabled", [True, False])
def test_replacement_preserves_profile_and_tool_restrictions_including_disabled_profiles(admin, monkeypatch, enabled):
    helpers.dns(monkeypatch)
    old = create(admin)
    with open_session() as db:
        identity = db.get(ServiceIdentity, db.get(ConnectorEnrollment, old['id']).identity_id)
        app_id, identity_id = identity.app_id, identity.id
    profile = api(admin, "POST", "/mcp-profiles", {"app_id": app_id, "name": "Reporting", "enabled": enabled,
        "modules": [], "tools": ["list_data_sources"]}, expect=201).json()["data"]
    api(admin, "PATCH", f"/service-identities/{identity_id}",
        {"profile_id": profile["id"], "allowed_tools": ["list_data_sources"]}, expect=200)
    replacement = api(admin, "POST", f"/connector-enrollments/{old['id']}/replace", expect=201).json()["data"]
    claim(admin, replacement)
    with helpers.source(controlled_source):
        assert admin['client'].post(f"/api/connect/v1/enrollments/{replacement['id']}/complete", json=PROOF).status_code == 200
    with open_session() as db:
        identity = db.get(ServiceIdentity, db.get(ConnectorEnrollment, replacement['id']).identity_id)
        assert identity.profile_id == profile["id"] and identity.allowed_tools == ["list_data_sources"]
        assert identity.scopes == ['mcp:tools']


def test_only_admin_can_renew_active_credentials_before_expiry(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    api(admin, 'POST', f"/connector-enrollments/{enrollment['id']}/renew", expect=409)
    with helpers.source(controlled_source):
        assert admin['client'].post(f"/api/connect/v1/enrollments/{enrollment['id']}/complete", json=PROOF).status_code == 200
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment['id'])
        row.management_expires_at = utcnow() + timedelta(days=1)
        db.commit()
    assert admin['client'].post(f"/api/admin/v1/connector-enrollments/{enrollment['id']}/renew").status_code == 403
    response = api(admin, 'POST', f"/connector-enrollments/{enrollment['id']}/renew")
    assert 'connection' not in response.json()['data']
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment['id'])
        assert row.management_expires_at == db.get(ServiceIdentity, row.identity_id).expires_at


def test_scoped_disconnect_revokes_runtime_credentials(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    claim(admin, enrollment)
    endpoint = f"/api/connect/v1/enrollments/{enrollment['id']}/disconnect"
    assert admin['client'].post(endpoint, json={**PROOF, 'proof': 'x'*43}).status_code == 401
    assert admin['client'].post(endpoint, json=PROOF).json()['data']['status'] == 'revoked'
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment['id'])
        assert db.get(ServiceIdentity, row.identity_id).revoked_at is not None


def test_pairing_history_survives_reload_and_never_recovers_one_use_secrets(admin, monkeypatch):
    helpers.dns(monkeypatch)
    first = create(admin)
    replacement = api(admin, "POST", f"/connector-enrollments/{first['id']}/replace", expect=201).json()["data"]
    rows = api(admin, "GET", f"/connector-enrollments?connector_id={first['connector_id']}", expect=200).json()["data"]
    assert [row['id'] for row in rows] == [replacement['id'], first['id']]
    assert rows[0]['replacement_id'] is None and rows[1]['replacement_id'] == replacement['id']
    assert rows[0]['created_at'] and rows[0]['status'] == 'pending'
    assert replacement['code'] not in json.dumps(rows)
    assert not any(field in rows[0] for field in ['code', 'proof', 'connection', 'bundle_ciphertext', 'client_key'])
    # Expiry metadata is accurate without mutating credentials during a GET.
    with open_session() as db:
        row = db.get(ConnectorEnrollment, replacement['id'])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    latest = api(admin, 'GET', f"/connector-enrollments/{replacement['id']}", expect=200).json()['data']
    assert latest['status'] == 'expired'
    with open_session() as db:
        row = db.get(ConnectorEnrollment, replacement['id'])
        assert row.status == 'pending'
        assert db.get(ServiceIdentity, row.identity_id).revoked_at is None


def test_auditor_can_read_only_assigned_pairing_metadata(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    with open_session() as db:
        user = db.scalar(select(AdminUser))
        user.role = 'auditor'
        app_id = db.get(Connector, enrollment['connector_id']).app_id
        db.add(AdminApplicationScope(user_id=user.id, app_id=app_id))
        db.commit()
    api(admin, 'GET', f"/connector-enrollments?connector_id={enrollment['connector_id']}", expect=200)
    api(admin, 'GET', f"/connector-enrollments/{enrollment['id']}", expect=200)
    for action in ['renew', 'replace', 'revoke']:
        api(admin, 'POST', f"/connector-enrollments/{enrollment['id']}/{action}", expect=403)


def test_foreign_expired_pairing_cannot_be_revoked_through_unauthorized_renewal(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment['id'])
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.scalar(select(AdminUser)).role = 'app_admin'  # No assignment to this app.
        db.commit()
    api(admin, 'GET', f"/connector-enrollments?connector_id={enrollment['connector_id']}", expect=403)
    api(admin, 'GET', f"/connector-enrollments/{enrollment['id']}", expect=403)
    for action in ['renew', 'replace', 'revoke']:
        api(admin, 'POST', f"/connector-enrollments/{enrollment['id']}/{action}", expect=403)
    with open_session() as db:
        row = db.get(ConnectorEnrollment, enrollment['id'])
        assert row.status == 'pending' and row.bundle_ciphertext is not None
        assert db.get(ServiceIdentity, row.identity_id).revoked_at is None
        assert db.get(ConnectorSecret, row.secret_id).revoked_at is None


def test_recovery_actions_require_csrf_and_history_requires_a_specific_connector(admin, monkeypatch):
    helpers.dns(monkeypatch)
    enrollment = create(admin)
    api(admin, 'GET', '/connector-enrollments', expect=422)
    api(admin, 'GET', '/connector-enrollments?connector_id=bad', expect=422)
    for action in ['renew', 'replace', 'revoke']:
        assert admin['client'].post(f"/api/admin/v1/connector-enrollments/{enrollment['id']}/{action}").status_code == 403
