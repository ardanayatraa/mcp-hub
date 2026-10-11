"""Lookup helpers for connector configuration. No per-application Python modules."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import HubError
from app.persistence.models import Application, Connector


def get_connector_bundle(db: Session, connector_id: str) -> tuple[Connector, Application]:
    connector = db.get(Connector, connector_id)
    if connector is None:
        raise HubError("NOT_FOUND", "Connector was not found", 404)
    application = db.get(Application, connector.app_id)
    if application is None:
        raise HubError("NOT_FOUND", "Application was not found", 404)
    return connector, application


def list_connectors(db: Session, environment: str | None = None) -> list[tuple[Connector, Application]]:
    query = select(Connector, Application).join(Application, Application.id == Connector.app_id)
    if environment:
        query = query.where(Application.environment == environment)
    return list(db.execute(query.order_by(Connector.created_at.desc())))
