"""Domain errors and their mapping to RFC 9457 problem details.

Services raise a `DomainError` subclass; the handlers installed by `install_error_handlers`
turn it into `application/problem+json` with a stable machine-readable `code`.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import ClassVar

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

PROBLEM_CONTENT_TYPE = "application/problem+json"


class FieldError(BaseModel):
    field: str
    message: str


class Problem(BaseModel):
    type: str
    title: str
    status: int
    detail: str | None = None
    code: str
    errors: list[FieldError] = []


def problem_type(code: str) -> str:
    """Relative URI identifying the problem type (RFC 9457 §3.1.1)."""
    return f"/problems/{code}"


class DomainError(Exception):
    """Base class for errors that are part of the API contract."""

    code: ClassVar[str]
    status: ClassVar[int]
    title: ClassVar[str]

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: Sequence[FieldError] = (),
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = list(errors)
        self.headers = dict(headers or {})

    def to_problem(self) -> Problem:
        return Problem(
            type=problem_type(self.code),
            title=self.title,
            status=self.status,
            detail=self.detail,
            code=self.code,
            errors=self.errors,
        )


class NotAuthenticated(DomainError):
    code, status, title = "not_authenticated", 401, "Sign-in required"


class Forbidden(DomainError):
    code, status, title = "forbidden", 403, "Not allowed"


class PremiumRequired(DomainError):
    code, status, title = "premium_required", 402, "Premium access required"


class NotFound(DomainError):
    code, status, title = "not_found", 404, "Not found"


class ValidationFailed(DomainError):
    code, status, title = "validation_error", 422, "Invalid request"


class StaleVersion(DomainError):
    code, status, title = "stale_version", 409, "Resource changed since it was read"


class Conflict(DomainError):
    code, status, title = "conflict", 409, "Conflict with the current state"


class SeatLimitReached(DomainError):
    code, status, title = "seat_limit_reached", 409, "All premium seats are in use"


class InviteExpired(DomainError):
    code, status, title = "invite_expired", 409, "Invite has expired"


class RulesNotConfirmed(DomainError):
    code, status, title = "rules_not_confirmed", 409, "Tournament rules are not confirmed"


class SetupNotReady(DomainError):
    code, status, title = "setup_not_ready", 409, "Tournament setup is not ready"


class OpenQuestionsRemaining(DomainError):
    code, status, title = "open_questions_remaining", 409, "Open setup questions remain"


class DrawInfeasible(DomainError):
    code, status, title = "draw_infeasible", 422, "The draw constraints cannot all be met"


class ScheduleInfeasible(DomainError):
    code, status, title = "schedule_infeasible", 422, "The schedule does not fit"


class ProcessingAgreementRequired(DomainError):
    code, status, title = "processing_agreement_required", 409, "Accept the processing terms"


class FilmingNotPermitted(DomainError):
    code, status, title = "filming_not_permitted", 409, "Filming checks have not passed"


class MatchNotLive(DomainError):
    code, status, title = "match_not_live", 409, "Match is not live"


class ScorerNotAssigned(DomainError):
    code, status, title = "scorer_not_assigned", 403, "Not a scorer for this match"


class PassRevoked(DomainError):
    code, status, title = "pass_revoked", 401, "Scorer pass is no longer valid"


class PassNotYetValid(DomainError):
    code, status, title = "pass_not_yet_valid", 401, "Scorer pass is not valid yet"


class RateLimited(DomainError):
    code, status, title = "rate_limited", 429, "Too many requests"

    def __init__(self, retry_after_s: int, detail: str | None = None) -> None:
        super().__init__(detail, headers={"Retry-After": str(retry_after_s)})
        self.retry_after_s = retry_after_s


class UpstreamUnavailable(DomainError):
    code, status, title = "upstream_unavailable", 503, "A required service is unavailable"


# Codes for errors raised by the framework rather than our services.
_HTTP_STATUS_CODES = {
    400: "bad_request",
    401: NotAuthenticated.code,
    403: Forbidden.code,
    404: NotFound.code,
    405: "method_not_allowed",
    409: Conflict.code,
    422: ValidationFailed.code,
    429: RateLimited.code,
}


def _problem_response(problem: Problem, headers: Mapping[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        problem.model_dump(mode="json"),
        status_code=problem.status,
        headers=dict(headers or {}),
        media_type=PROBLEM_CONTENT_TYPE,
    )


async def _handle_domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _problem_response(exc.to_problem(), exc.headers)


async def _handle_request_validation(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        FieldError(field=".".join(str(part) for part in err["loc"]), message=err["msg"])
        for err in exc.errors()
    ]
    return _problem_response(ValidationFailed(errors=errors).to_problem())


async def _handle_http_exception(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_STATUS_CODES.get(exc.status_code, "http_error")
    problem = Problem(
        type=problem_type(code),
        title=HTTPStatus(exc.status_code).phrase,
        status=exc.status_code,
        detail=exc.detail if isinstance(exc.detail, str) else None,
        code=code,
    )
    return _problem_response(problem, exc.headers)


async def _handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
    # Already logged with its request id by RequestIdMiddleware; never leak details.
    problem = Problem(
        type=problem_type("internal_error"),
        title="Internal server error",
        status=500,
        code="internal_error",
    )
    return _problem_response(problem)


def install_error_handlers(app: FastAPI) -> None:
    """Map every error raised inside the app to a problem-details response."""
    app.add_exception_handler(DomainError, _handle_domain_error)
    app.add_exception_handler(RequestValidationError, _handle_request_validation)
    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(Exception, _handle_unexpected)
