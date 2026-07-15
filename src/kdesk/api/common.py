from __future__ import annotations

import logging
import time
import uuid

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("kdesk.http")


async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.exception("request_failed request_id=%s path=%s", request_id, request.url.path)
        response = JSONResponse({"ok": False, "error": str(exc), "requestId": request_id}, status_code=500)
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Elapsed-Ms"] = str(elapsed_ms)
    logger.info("request request_id=%s method=%s path=%s status=%s elapsed_ms=%s", request_id, request.method, request.url.path, response.status_code, elapsed_ms)
    return response


def legacy_filters(params) -> dict[str, str]:
    return {
        "platform": str(params.get("platform", "") or "").strip(),
        "server": str(params.get("server", "") or "").strip(),
        "symbol": str(params.get("symbol", "") or "").strip(),
        "start": str(params.get("start", "") or "").strip(),
        "end": str(params.get("end", "") or "").strip(),
    }
