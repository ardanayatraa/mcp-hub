"""One-use enrollment API, separate from admin sessions and runtime client keys."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.v1.common import client_host, ok
from app.config import get_settings
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.crypto import sha256_hex
from app.security.rate_limit import hit
from app.services import enrollments

router = APIRouter(prefix="/api/connect/v1/enrollments", tags=["connector pairing"])


class Proof(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    installation_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    attempt_id: str = Field(min_length=16, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    proof: str = Field(min_length=43, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class Claim(Proof):
    code: str = Field(min_length=40, max_length=96, pattern=r"^enr_[A-Za-z0-9_-]+$")


def throttle(request: Request):
    hit("pairing:" + client_host(request), 15, 600)


@router.post("/claim")
def claim(body: Claim, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    result = enrollments.claim(db, body.model_dump(), get_settings())
    db.commit()
    return ok(result)


@router.post("/{enrollment_id}/status")
def status(enrollment_id: str, body: Proof, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    row, _connector, _application, _creator = enrollments.authenticated(db, enrollment_id, body.model_dump())
    return ok(enrollments.metadata(row))


@router.post("/{enrollment_id}/complete")
async def complete(enrollment_id: str, body: Proof, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    result = await enrollments.complete(db, enrollment_id, body.model_dump(), get_settings())
    db.commit()
    return ok(result)


@router.post("/{enrollment_id}/sync")
async def sync(enrollment_id: str, body: Proof, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    result = await enrollments.sync(db, enrollment_id, body.model_dump(), get_settings())
    db.commit()
    return ok(result)


@router.post("/{enrollment_id}/disconnect")
def disconnect(enrollment_id: str, body: Proof, request: Request, db: Session = Depends(get_db)):
    throttle(request)
    row, _connector, application, _creator = enrollments.authenticated(db, enrollment_id, body.model_dump())
    enrollments.revoke(db, row)
    record_audit(db, action="enrollment.disconnect", actor_ref="installation:" + sha256_hex(row.installation_id)[:24],
                 app_key=application.key, environment=application.environment, result="success")
    db.commit()
    return ok(enrollments.metadata(row))
