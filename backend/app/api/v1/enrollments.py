from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.api.v1.configuration import Environment
from app.config import get_settings
from app.errors import HubError
from app.persistence.models import AdminUser, Application, Connector, ConnectorEnrollment
from app.persistence.session import get_db
from app.security.audit import record_audit
from app.security.auth import require_csrf
from app.security.authorization import READ_ROLES, WRITE_ROLES, require_app_access, require_role
from app.services import enrollments

router = APIRouter(prefix="/connector-enrollments", tags=["connector enrollments"])


class EnrollmentCreate(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    app_key: str = Field(min_length=1, max_length=64)
    environment: Environment = "dev"
    base_url: str = Field(min_length=1, max_length=500)


@router.post("")
def create(body: EnrollmentCreate, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    result = enrollments.create(db, user, body.model_dump(), get_settings())
    db.commit()
    return ok(result, 201)


@router.get("/{enrollment_id}")
def detail(enrollment_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    row = db.get(ConnectorEnrollment, enrollment_id)
    if row is None:
        raise HubError("NOT_FOUND", "Enrollment was not found", 404)
    connector = db.get(Connector, row.connector_id)
    application = db.get(Application, connector.app_id)
    require_app_access(db, user, application.id)
    return ok(enrollments.metadata(row))


@router.get("")
def index(connector_id: str = Query(min_length=36, max_length=36), db: Session = Depends(get_db),
          user: AdminUser = Depends(require_csrf)):
    require_role(user.role, READ_ROLES)
    connector = db.get(Connector, connector_id)
    if connector is None:
        raise HubError("NOT_FOUND", "Connection was not found", 404)
    require_app_access(db, user, connector.app_id)
    rows = db.scalars(select(ConnectorEnrollment).where(ConnectorEnrollment.connector_id == connector_id)
                      .order_by(ConnectorEnrollment.created_at.desc(), ConnectorEnrollment.id.desc()).limit(20))
    return ok([enrollments.metadata(row) for row in rows])


@router.post("/{enrollment_id}/revoke")
def revoke(enrollment_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    row = db.get(ConnectorEnrollment, enrollment_id)
    if row is None:
        raise HubError("NOT_FOUND", "Enrollment was not found", 404)
    connector = db.get(Connector, row.connector_id)
    application = db.get(Application, connector.app_id)
    require_app_access(db, user, application.id)
    enrollments.revoke(db, row)
    record_audit(db, action="enrollment.revoke", actor_ref=f"admin:{user.id}", app_key=application.key,
                 environment=application.environment, result="success")
    db.commit()
    return ok(enrollments.metadata(row))


@router.post("/{enrollment_id}/replace")
def replace(enrollment_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    row = db.get(ConnectorEnrollment, enrollment_id)
    if row is None:
        raise HubError("NOT_FOUND", "Enrollment was not found", 404)
    result = enrollments.replace(db, user, row, get_settings())
    db.commit()
    return ok(result, 201)


@router.post("/{enrollment_id}/renew")
def renew(enrollment_id: str, db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    require_role(user.role, WRITE_ROLES)
    row = db.get(ConnectorEnrollment, enrollment_id)
    if row is None:
        raise HubError("NOT_FOUND", "Enrollment was not found", 404)
    result = enrollments.renew(db, user, row)
    db.commit()
    return ok(result)
