"""Real row-lock races use only the disposable PostgreSQL test database."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier

import pytest
from app.config import get_settings
from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import (
    AdminUser,
    ConnectorEnrollment,
    ConnectorSecret,
    ServiceIdentity,
    ToolDefinition,
)
from app.persistence.session import open_session
from app.services import enrollments, openapi_import
from sqlalchemy import func, select, text
from tests import helpers
from tests.helpers import api, connect_app
from tests.integration.test_enrollments import create
from tests.integration.test_openapi_import import document


def postgres_only():
    with open_session() as db:
        if db.get_bind().dialect.name != 'postgresql':
            pytest.skip('Real independent-session races require the disposable PostgreSQL database')


def test_two_replacements_produce_one_new_identity_and_one_active_source_secret(admin, monkeypatch):
    postgres_only()
    helpers.dns(monkeypatch)
    old = create(admin)
    barrier = Barrier(2)

    def replace():
        with open_session() as db:
            db.execute(text("SET LOCAL lock_timeout = '3s'"))
            row = db.get(ConnectorEnrollment, old['id'])
            user = db.scalar(select(AdminUser))
            barrier.wait(timeout=5)
            try:
                created = enrollments.replace(db, user, row, get_settings())
                db.commit()
                return 201, created['id']  # Never retain or return the one-use code.
            except HubError as error:
                db.rollback()
                return error.status_code, None

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(replace) for _ in range(2)]
        results = [future.result(timeout=8) for future in futures]
    assert sorted(status for status, _identifier in results) == [201, 409]
    with open_session() as db:
        assert db.scalar(select(func.count()).select_from(ConnectorEnrollment)) == 2
        assert db.scalar(select(func.count()).select_from(ServiceIdentity)) == 2
        assert db.scalar(select(func.count()).select_from(ConnectorSecret).where(ConnectorSecret.revoked_at.is_(None))) == 1
        assert db.get(ConnectorEnrollment, old['id']).replacement_id == next(identifier for status, identifier in results if status == 201)


def test_two_imports_create_one_draft_without_partial_mappings(admin, monkeypatch):
    postgres_only()
    helpers.dns(monkeypatch)
    with helpers.source():
        app = connect_app(admin)
    doc = document()
    checked = api(admin, 'POST', '/tools/openapi/preview', {'connector_id': app['connector_id'], 'document': json.dumps(doc)}, expect=200).json()['data']
    selected = [checked['candidates'][0]['id']]
    barrier = Barrier(2)

    def import_one():
        with open_session() as db:
            db.execute(text("SET LOCAL lock_timeout = '3s'"))
            user = db.scalar(select(AdminUser))
            barrier.wait(timeout=5)
            try:
                openapi_import.import_drafts(db, user, app['connector_id'], doc, checked['fingerprint'], selected)
                db.commit()
                return 201
            except HubError as error:
                db.rollback()
                return error.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(import_one) for _ in range(2)]
        assert sorted(future.result(timeout=8) for future in futures) == [201, 409]
    with open_session() as db:
        assert db.scalar(select(func.count()).select_from(ToolDefinition)) == 1


def test_stale_expiry_observation_does_not_revoke_an_already_extended_pairing(admin, monkeypatch):
    helpers.dns(monkeypatch)
    issued = create(admin)
    with open_session() as db:
        row = db.get(ConnectorEnrollment, issued['id'])
        row.status = 'active'
        row.management_expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    with open_session() as observer:
        stale = observer.get(ConnectorEnrollment, issued['id'])
        with open_session() as operator:
            row = operator.get(ConnectorEnrollment, issued['id'])
            row.management_expires_at = utcnow() + timedelta(days=90)
            operator.get(ServiceIdentity, row.identity_id).expires_at = row.management_expires_at
            operator.commit()
        enrollments._expiry(observer, stale)
        observer.commit()
        assert stale.status == 'active'
        assert observer.get(ServiceIdentity, stale.identity_id).revoked_at is None
