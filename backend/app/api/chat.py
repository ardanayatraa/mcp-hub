"""Chat endpoints apps call from their server (never from the browser: the client key is secret).

POST /chat/v1/turn streams Server-Sent Events by default:
  start {trace_id} · text {delta} · tool {id, name, title, status, ...} · proposal {...}
  · notice {code, message} · error {code, message, trace_id} · done {trace_id, steps, ...}
Send "stream": false for one JSON answer instead.
"""

import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.v1.common import ok
from app.chat import engine
from app.errors import HubError
from app.persistence.session import get_db, open_session
from app.security.clients import Caller, require_caller

logger = logging.getLogger("hub.chat")
router = APIRouter(prefix="/chat/v1", tags=["chat"])
HEARTBEAT_SECONDS = 15


def bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


async def read_body(request: Request):
    try:
        return await request.json()
    except ValueError as exc:
        raise HubError("VALIDATION_FAILED", "Request body must be JSON", 422) from exc


def stream_turn(db: Session, turn: engine.Turn) -> StreamingResponse:
    """Run a prepared turn and stream its events. Owns `db` from here on and closes it."""

    async def events():
        queue: asyncio.Queue = asyncio.Queue()

        async def emit(event: str, data: dict) -> None:
            await queue.put((event, data))

        async def work() -> None:
            try:
                result = await turn.run(emit)
                await queue.put(("done", {key: result[key] for key in ("trace_id", "steps", "tools", "proposals",
                                                                        "notices")}))
            except HubError as exc:
                await queue.put(("error", {"code": exc.code, "message": exc.message, "trace_id": turn.trace}))
            except Exception as exc:
                logger.error("chat_failure", extra={"error_type": type(exc).__name__, "trace_id": turn.trace})
                await queue.put(("error", {"code": "INTERNAL", "message": "The chat failed unexpectedly",
                                           "trace_id": turn.trace}))
            finally:
                await queue.put(None)

        task = asyncio.create_task(work())
        try:
            yield sse("start", {"trace_id": turn.trace})
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield ": keep-alive\n\n"
                    continue
                if item is None:
                    break
                yield sse(*item)
        finally:
            if not task.done():
                task.cancel()
                with contextlib.suppress(BaseException):
                    await task
            db.close()

    return StreamingResponse(events(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


async def start_turn(db: Session, caller: Caller, body, delegation: str | None):
    """Prepare a turn so every refusal is a plain HTTP error, then stream it or answer once."""

    request = engine.parse_request(body)
    turn = await engine.Turn(db, caller, request, delegation).prepare()
    if isinstance(body, dict) and body.get("stream") is False:
        try:
            async def ignore(_event: str, _data: dict) -> None:
                return None

            return ok(await turn.run(ignore))
        finally:
            db.close()
    return stream_turn(db, turn)


@router.get("/config")
def config(request: Request, db: Session = Depends(get_db)):
    caller = require_caller(db, bearer(request))
    view = engine.public_config(db, caller)
    db.commit()
    return ok(view)


@router.post("/turn")
async def turn(request: Request):
    body = await read_body(request)
    try:
        db = open_session()
    except RuntimeError as exc:
        raise HubError("UNAVAILABLE", "The hub database is not ready", 503) from exc
    try:
        caller = require_caller(db, bearer(request))
        response = await start_turn(db, caller, body, request.headers.get("x-hub-delegation"))
    except BaseException:
        db.close()
        raise
    return response
