"""The console assistant: admins ask how this Hub works, answered from its own repository."""

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api.chat import read_body, stream_turn
from app.api.v1.common import ok
from app.chat import assistant, registry
from app.config import get_settings
from app.persistence.models import AdminUser
from app.persistence.session import get_db, open_session
from app.security.auth import require_csrf

router = APIRouter(prefix="/assistant", tags=["assistant"])


@router.get("")
def options(db: Session = Depends(get_db), user: AdminUser = Depends(require_csrf)):
    del user
    return ok(assistant.options(db, registry.claude_settings(db, get_settings())))


@router.post("")
async def ask(request: Request, user: AdminUser = Depends(require_csrf)):
    """Stream an answer: text, the files the assistant read (tool events), notices and done."""

    body = await read_body(request)
    db = open_session()
    try:
        turn = await assistant.AssistantTurn(db, user, body).prepare()
    except BaseException:
        db.close()
        raise
    return stream_turn(db, turn)
