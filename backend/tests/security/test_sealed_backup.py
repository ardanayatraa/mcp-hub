"""Sealed backups: unreadable without the Hub's key, refused when changed, restorable after a key rotation."""

import copy
import json

import pytest
from app.config import get_settings
from app.errors import HubError
from app.ids import utcnow
from app.persistence.models import Application
from app.persistence.session import open_session
from app.services import backup
from cryptography.fernet import Fernet
from sqlalchemy import delete, select
from tests import helpers
from tests.helpers import api, connect_app

KEY = "WyzcJBTgZUDuBhqKXe8GWpoJSvp2nR5J9ag3X5fMf5g="
DOCUMENT = {"format": backup.PLAIN_FORMAT, "tables": {"applications": [{"key": "your_app", "name": "Your App"}]}}


def sealed(key: str = KEY, document: dict = DOCUMENT) -> dict:
    return backup.seal(document, key, version="test", created_at=utcnow())


def test_a_sealed_backup_shows_nothing_but_its_label():
    envelope = sealed()
    assert envelope["format"] == backup.SEALED_FORMAT and envelope["encryption"] == "fernet+gzip"
    assert envelope["key_fingerprint"] == backup.key_fingerprint(KEY) and KEY not in json.dumps(envelope)
    text = json.dumps(envelope)
    assert "your_app" not in text and "applications" not in text and "Your App" not in text
    assert backup.unseal(envelope, KEY) == DOCUMENT
    # The fingerprint tells keys apart and is stable; it is not the key.
    assert backup.key_fingerprint(KEY) == backup.key_fingerprint(KEY) != backup.key_fingerprint(Fernet.generate_key().decode())


def test_another_hubs_key_is_named_and_a_changed_file_is_refused():
    other = Fernet.generate_key().decode()
    with pytest.raises(HubError) as refused:
        backup.unseal(sealed(other), KEY)
    assert refused.value.code == "BACKUP_KEY_MISMATCH" and backup.key_fingerprint(other) in refused.value.message

    changed = sealed()
    changed["ciphertext"] = changed["ciphertext"][:-8] + ("A" * 8 if not changed["ciphertext"].endswith("A" * 8) else "B" * 8)
    with pytest.raises(HubError) as damaged:
        backup.unseal(changed, KEY)
    assert damaged.value.code == "BACKUP_DAMAGED"

    for bad in ({**sealed(), "extra": 1}, {**sealed(), "encryption": "none"}, {**sealed(), "ciphertext": 7}):
        with pytest.raises(HubError) as invalid:
            backup.unseal(bad, KEY)
        assert invalid.value.code == "VALIDATION_FAILED"


def test_a_backup_cannot_open_into_more_than_its_limit(monkeypatch):
    monkeypatch.setattr(backup, "MAX_OPENED_BYTES", 1024)
    big = {"format": backup.PLAIN_FORMAT, "tables": {"skills": [{"text": "x" * 5000}]}}
    with pytest.raises(HubError) as refused:
        backup.unseal(sealed(document=big), KEY)
    assert refused.value.code == "VALIDATION_FAILED"


def test_a_backup_from_before_a_key_rotation_opens_with_the_previous_key(monkeypatch):
    old, new = KEY, Fernet.generate_key().decode()
    envelope = sealed(old)
    with pytest.raises(HubError):
        backup.unseal(envelope, new)
    monkeypatch.setattr(get_settings(), "secret_encryption_key_previous", old)
    assert backup.unseal(envelope, new) == DOCUMENT


def test_export_is_sealed_and_restores_a_lost_app(admin, monkeypatch):
    helpers.dns(monkeypatch)
    with helpers.source():
        connect_app(admin)
    envelope = api(admin, "POST", "/operations/export", expect=200).json()["data"]
    system = api(admin, "GET", "/system", expect=200).json()["data"]
    assert envelope["format"] == backup.SEALED_FORMAT and envelope["key_fingerprint"] == system["backup_key_fingerprint"]
    assert "your_app" not in json.dumps(envelope) and "projects.test" not in json.dumps(envelope)

    with open_session() as db:  # the app is gone
        db.execute(delete(Application))
        db.commit()
    counts = api(admin, "POST", "/operations/import", envelope, expect=200).json()["data"]
    assert counts["applications"] == 1 and counts["connector_secrets"] == 1
    with open_session() as db:
        assert db.scalar(select(Application.key)) == "your_app"

    changed = copy.deepcopy(envelope)
    changed["ciphertext"] = changed["ciphertext"][:40] + changed["ciphertext"][41:]
    refused = api(admin, "POST", "/operations/import", changed)
    assert refused.status_code == 422 and refused.json()["error"]["code"] in {"BACKUP_DAMAGED", "VALIDATION_FAILED"}
    foreign = sealed(Fernet.generate_key().decode(), backup.open_backup(envelope, KEY))
    assert api(admin, "POST", "/operations/import", foreign).json()["error"]["code"] == "BACKUP_KEY_MISMATCH"
    with open_session() as db:  # refused restores change nothing
        assert db.scalar(select(Application.key)) == "your_app"
