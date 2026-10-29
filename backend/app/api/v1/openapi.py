from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.config import get_settings
from app.errors import HubError
from app.persistence.models import AdminUser
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.services import openapi_import

router = APIRouter(prefix="/tools/openapi", tags=["OpenAPI draft import"])


class Description(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    connector_id: str = Field(min_length=36, max_length=36)
    document: str | None = Field(default=None, max_length=524288)
    source_url: str | None = Field(default=None, max_length=2048)
    format: Literal["json", "yaml"] = "json"


class Selection(Description):
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    selected: list[Annotated[str, Field(pattern=r"^[a-f0-9]{24}$")]] = Field(min_length=1, max_length=20)


@router.post("/preview")
async def preview(body: Description, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    openapi_import.authorize(db, user, body.connector_id)
    document = await openapi_import.document_for(body.model_dump(), get_settings())
    db.expire_all()  # Recheck role, scope and source configuration after remote I/O.
    result = openapi_import.preview(db, user, body.connector_id, document)
    record_audit(db, action="openapi.preview", actor_ref=f"admin:{user.id}", result="success")
    db.commit()
    return ok(result)


@router.post("/import")
async def import_drafts(body: Selection, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    openapi_import.authorize(db, user, body.connector_id)
    document = await openapi_import.document_for(body.model_dump(), get_settings())
    db.expire_all()
    try:
        result = openapi_import.import_drafts(db, user, body.connector_id, document, body.fingerprint, body.selected)
        record_audit(db, action="openapi.import", actor_ref=f"admin:{user.id}", result="success")
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HubError("CONFLICT", "A selected tool already exists; refresh the tool list", 409) from None
    return ok(result, 201)
