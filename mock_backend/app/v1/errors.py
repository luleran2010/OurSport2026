"""RFC 9457 problem details, as the backend sends every error (backend/app/core/errors.py)."""

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

PREFIX = "/api/v1"
_CODES = {400: "validation_error", 401: "not_authenticated", 402: "premium_required", 403: "forbidden",
          404: "not_found", 409: "conflict", 422: "validation_error", 429: "rate_limited"}
_TITLES = {"validation_error": "Invalid request", "not_authenticated": "Sign-in required",
           "forbidden": "Not allowed", "not_found": "Not found", "conflict": "Conflict with the current state",
           "premium_required": "Premium access required", "rate_limited": "Too many requests",
           "match_not_live": "Match is not live", "scorer_not_assigned": "Not a scorer for this match"}
# codes the mock's shared helpers raise -> the backend's code for the same situation
_LEGACY = {"finished": "match_not_live", "not_started": "match_not_live", "results_only": "match_not_live",
           "started": "conflict", "between_periods": "validation_error", "no_next_period": "validation_error",
           "event_type": "validation_error", "team": "validation_error", "player": "validation_error",
           "control": "conflict", "sport": "validation_error", "not_found": "not_found"}


class Problem(HTTPException):
    def __init__(self, status: int, code: str, detail: str, errors: list[dict] | None = None) -> None:
        super().__init__(status, detail)
        self.code, self.errors = code, errors or []


def problem(status: int, code: str, detail: str = "", errors: list[dict] | None = None) -> Problem:
    return Problem(status, code, detail or _TITLES.get(code, code), errors)


def _body(status: int, code: str, detail: str, errors: list[dict]) -> JSONResponse:
    return JSONResponse(
        {"type": f"/problems/{code}", "title": _TITLES.get(code, code.replace("_", " ").capitalize()),
         "status": status, "detail": detail, "code": code, "errors": errors},
        status_code=status, media_type="application/problem+json",
    )


def as_problem(exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc, Problem):
        return _body(exc.status_code, exc.code, str(exc.detail), exc.errors)
    detail = exc.detail
    code = _CODES.get(exc.status_code, "conflict")
    if isinstance(detail, dict):
        code = _LEGACY.get(detail.get("code", ""), code)
        detail = detail.get("message", "")
    return _body(exc.status_code, code, str(detail or ""), [])


def install(app) -> None:
    """Problem details for /api/v1 only; the old routes keep FastAPI's `{detail}` errors."""
    default_http = app.exception_handlers[StarletteHTTPException]
    default_validation = app.exception_handlers[RequestValidationError]

    async def on_http(request: Request, exc: StarletteHTTPException):
        if request.url.path.startswith(PREFIX):
            return as_problem(exc)
        return await default_http(request, exc)

    async def on_validation(request: Request, exc: RequestValidationError):
        if request.url.path.startswith(PREFIX):
            errors = [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
            return _body(422, "validation_error", "The request is not valid", errors)
        return await default_validation(request, exc)

    app.add_exception_handler(StarletteHTTPException, on_http)
    app.add_exception_handler(RequestValidationError, on_validation)
