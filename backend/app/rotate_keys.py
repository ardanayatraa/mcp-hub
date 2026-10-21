"""Re-encrypt every stored secret with SECRET_ENCRYPTION_KEY.

Rotation: set the new key as SECRET_ENCRYPTION_KEY and the old one in SECRET_ENCRYPTION_KEY_PREVIOUS,
restart, run `python -m app.rotate_keys`, then remove SECRET_ENCRYPTION_KEY_PREVIOUS and restart again.
Nothing is decrypted to disk or printed; a value no key can read stops the run before anything is saved.
"""

from cryptography.fernet import InvalidToken
from sqlalchemy import select

from app.config import get_settings
from app.persistence.models import AdminUser, ConnectorSecret, ModelProvider, UserMemory
from app.persistence.session import init_engine, open_session
from app.security.audit import record_audit
from app.security.crypto import keyring

ENCRYPTED = [
    (ConnectorSecret, ("secret_ciphertext", "delegation_ciphertext")),
    (ModelProvider, ("api_key_ciphertext",)),
    (AdminUser, ("totp_secret_encrypted",)),
    (UserMemory, ("content_ciphertext",)),
]


def rotate(db) -> int:
    ring = keyring(get_settings().secret_encryption_key)
    rotated = 0
    for model, columns in ENCRYPTED:
        for row in db.scalars(select(model)):
            for column in columns:
                value = getattr(row, column)
                if not value:
                    continue
                try:
                    setattr(row, column, ring.rotate(value.encode("utf-8")).decode("utf-8"))
                except InvalidToken as exc:
                    raise SystemExit(f"a value in {model.__tablename__}.{column} matches none of the keys; "
                                     "nothing was changed") from exc
                rotated += 1
    record_audit(db, action="secrets.rotate", actor_ref="system:cli", result="success")
    return rotated


def main() -> None:
    settings = get_settings()
    init_engine(settings.database_url)
    db = open_session()
    try:
        count = rotate(db)
        db.commit()
        print(f"re-encrypted {count} values with the current key")
    finally:
        db.close()


if __name__ == "__main__":
    main()
