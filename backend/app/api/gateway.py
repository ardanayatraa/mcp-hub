"""Model gateway endpoints apps call from their server with a client key (see app.chat.gateway).

GET  /gateway/v1/models            the models the app may pick, OpenAI style, plus "default"
POST /gateway/v1/chat/completions  one completion, OpenAI style; "stream": true sends it as one SSE chunk
POST /gateway/mcp                  JSON-RPC: tools list_ai_models and chat_ai, the model bridge apps such as
                                   HiReach speak (plain JSON answers, no session)
"""

import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from sqlalchemy.orm import Session

from app import __version__
from app.api.chat import bearer, read_body
from app.chat import gateway
from app.config import get_settings
from app.errors import HubError
from app.persistence.session import get_db
from app.security.clients import require_caller

router = APIRouter(prefix="/gateway", tags=["model gateway"])

TOOLS = [
    {"name": "list_ai_models", "title": "List AI models",
     "description": "The models this app may use through the Hub, with the default.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "chat_ai", "title": "Chat with an AI model",
     "description": "One chat completion in the OpenAI shape, with optional function tools.",
     "inputSchema": {"type": "object", "required": ["model", "messages"], "properties": {
         "model": {"type": "string"}, "messages": {"type": "array"}, "tools": {"type": "array"},
         "tool_choice": {}, "metadata": {"type": "object"}, "temperature": {"type": "number"},
         "top_p": {"type": "number"}, "max_tokens": {"type": "integer"}}}},
]


@router.get("/v1/models")
async def models(request: Request, db: Session = Depends(get_db)):
    caller = require_caller(db, bearer(request))
    listing = await gateway.catalog(db, get_settings(), caller)
    db.commit()
    return {"object": "list", "default": listing["default"],
            "data": [{"id": row["id"], "object": "model", "owned_by": row["provider"], "name": row["name"]}
                     for row in listing["data"]]}


@router.post("/v1/chat/completions")
async def completions(request: Request, db: Session = Depends(get_db)):
    body = await read_body(request)
    caller = require_caller(db, bearer(request))
    try:
        answer = await gateway.complete(db, get_settings(), caller, body)
    finally:
        db.commit()  # keeps the audit row of a refused call too
    if isinstance(body, dict) and body.get("stream") is True:
        choice = answer["choices"][0]
        delta = dict(choice["message"])
        if delta.get("tool_calls"):  # streamed tool calls carry their position, as OpenAI's do
            delta["tool_calls"] = [{"index": n, **call} for n, call in enumerate(delta["tool_calls"])]
        chunk = {**answer, "object": "chat.completion.chunk",
                 "choices": [{"index": 0, "delta": delta, "finish_reason": choice["finish_reason"]}]}
        payload = f"data: {json.dumps(chunk, ensure_ascii=False)}\n\ndata: [DONE]\n\n"
        return StreamingResponse(iter([payload]), media_type="text/event-stream")
    return answer


def _rpc(request_id, *, result=None, error=None) -> JSONResponse:
    body = {"jsonrpc": "2.0", "id": request_id}
    body.update({"error": error} if error else {"result": result})
    return JSONResponse(body)


@router.post("/mcp")
async def bridge(request: Request, db: Session = Depends(get_db)):
    body = await read_body(request)
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or not isinstance(body.get("method"), str):
        return _rpc(None, error={"code": -32600, "message": "Invalid request"})
    request_id, method, params = body.get("id"), body["method"], body.get("params") or {}
    caller = require_caller(db, bearer(request))
    if "id" not in body:  # a notification, such as notifications/initialized
        db.commit()
        return Response(status_code=202)
    if method == "initialize":
        version = params.get("protocolVersion") if isinstance(params, dict) else None
        version = version if isinstance(version, str) and len(version) <= 32 else None
        db.commit()
        return _rpc(request_id, result={"protocolVersion": version or "2025-06-18", "capabilities": {"tools": {}},
                                        "serverInfo": {"name": "MCP Hub model gateway", "version": __version__}})
    if method == "tools/list":
        db.commit()
        return _rpc(request_id, result={"tools": TOOLS})
    if method != "tools/call":
        return _rpc(request_id, error={"code": -32601, "message": "Method not found"})
    name = params.get("name") if isinstance(params, dict) else None
    arguments = params.get("arguments") if isinstance(params, dict) else None
    try:
        if name == "list_ai_models":
            data = await gateway.catalog(db, get_settings(), caller)
        elif name == "chat_ai":
            data = await gateway.complete(db, get_settings(), caller, arguments)
        else:
            return _rpc(request_id, error={"code": -32602, "message": f"Unknown tool: {name}"})
    except HubError as exc:
        db.commit()
        return _rpc(request_id, result={"isError": True, "content": [{"type": "text", "text": f"{exc.code}: {exc.message}"}]})
    db.commit()
    return _rpc(request_id, result={"isError": False, "structuredContent": {"result": data},
                                    "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}]})
