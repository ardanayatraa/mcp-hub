"""Encrypt connector secrets at rest. Plaintext never goes into the database or logs."""

import hashlib
import hmac
import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet, InvalidToken

from app.errors import HubError


def _fernet(key: str) -> Fernet:
    try:
        return Fernet(key.encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise HubError("UNSAFE_CONFIGURATION", "SECRET_ENCRYPTION_KEY is not a valid Fernet key", 500) from exc


def encrypt_secret(key: str, plaintext: str) -> str:
    return _fernet(key).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(key: str, ciphertext: str) -> str:
    try:
        return _fernet(key).decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise HubError("SECRET_UNAVAILABLE", "Stored credential could not be decrypted", 500) from exc


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64(data: bytes) -> str:
    return urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return urlsafe_b64decode(value + padding)


def sign_payload(secret: str, payload: dict, ttl_seconds: int = 120) -> str:
    body = dict(payload)
    body["exp"] = int((datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).timestamp())
    raw = json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
    return f"{_b64(raw)}.{_b64(digest)}"


def verify_signed_payload(secret: str, token: str, *, audience: str | None = None) -> dict:
    try:
        raw_part, digest_part = token.split(".", 1)
        raw = _b64decode(raw_part)
        expected = hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64decode(digest_part)):
            raise HubError("PERMISSION_DENIED", "Delegated user context is not valid", 403)
        payload = json.loads(raw.decode("utf-8"))
    except HubError:
        raise
    except (ValueError, json.JSONDecodeError) as exc:
        raise HubError("PERMISSION_DENIED", "Delegated user context is not valid", 403) from exc
    if not isinstance(payload, dict):
        raise HubError("PERMISSION_DENIED", "Delegated user context is not valid", 403)
    exp = payload.get("exp")
    now = int(datetime.now(timezone.utc).timestamp())
    if type(exp) is not int or not now < exp <= now + 150:
        raise HubError("PERMISSION_DENIED", "Delegated user context has expired", 403)
    if audience is not None and payload.get("aud") != audience:
        raise HubError("PERMISSION_DENIED", "Delegated user context audience does not match", 403)
    return payload


def dataset_digest(dataset: list, meta: dict) -> str:
    try:
        body = json.dumps({"dataset": dataset, "meta": meta}, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise HubError("VALIDATION_FAILED", "Dataset is not valid finite JSON", 422) from exc
    return sha256_hex(body)
