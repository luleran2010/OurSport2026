"""The mock serves the backend's v1 contract: every /api/v1 operation the mock has must exist
in backend/docs/frontend-handoff/openapi.json with the same method, path, operation id,
parameters, success status, and request/response fields (names, required, types)."""

import json
from pathlib import Path
from typing import Any

import pytest

from app.main import app

CONTRACT = Path(__file__).resolve().parents[2] / "backend" / "docs" / "frontend-handoff" / "openapi.json"
pytestmark = pytest.mark.skipif(not CONTRACT.exists(), reason="backend contract not found next to the mock")


def _ops(spec: dict) -> dict[tuple[str, str], dict]:
    return {(m, p): o for p, v in spec["paths"].items() for m, o in v.items() if p.startswith("/api/v1")}


def _resolve(spec: dict, schema: dict) -> dict:
    while "$ref" in schema:
        schema = spec["components"]["schemas"][schema["$ref"].split("/")[-1]]
    return schema


def _shape(spec: dict, schema: dict | None, depth: int = 0) -> Any:
    """A comparable outline: object -> {field: (required, shape)}, array -> [shape], else type."""
    if not schema or depth > 6:
        return None
    schema = _resolve(spec, schema)
    if "anyOf" in schema:
        options = [_shape(spec, s, depth + 1) for s in schema["anyOf"]]
        return ("anyOf", tuple(sorted(map(json.dumps, options))))
    if schema.get("type") == "array":
        return ["array", _shape(spec, schema.get("items"), depth + 1)]
    if "properties" in schema:
        required = set(schema.get("required", []))
        return {k: (k in required, _shape(spec, v, depth + 1)) for k, v in schema["properties"].items()}
    if "enum" in schema:
        return ("enum", tuple(sorted(schema["enum"])))
    if "const" in schema:
        return ("const", schema["const"])
    # uuid/date-time formats are the backend's; the mock types ids as plain strings
    return schema.get("type", "any")


def _relaxed(shape: Any) -> Any:
    return json.loads(json.dumps(shape).replace('"format"', '"_"'))


def _body(spec: dict, op: dict) -> Any:
    content = op.get("requestBody", {}).get("content", {})
    schema = next(iter(content.values()), {}).get("schema")
    return _shape(spec, schema)


def _success(spec: dict, op: dict) -> tuple[str, Any]:
    code = next(c for c in op["responses"] if c.startswith("2"))
    schema = op["responses"][code].get("content", {}).get("application/json", {}).get("schema")
    return code, _shape(spec, schema)


def _params(op: dict) -> set[tuple[str, str]]:
    return {(p["in"], p["name"]) for p in op.get("parameters", []) if p["in"] in ("path", "query")}


backend = json.loads(CONTRACT.read_text(encoding="utf-8")) if CONTRACT.exists() else {"paths": {}}
mock = app.openapi()
MOCK_OPS = sorted(_ops(mock))


def test_the_mock_serves_the_phase_one_operations() -> None:
    ids = {o["operationId"] for o in _ops(mock).values()}
    assert {"getMe", "listMatches", "getTournament", "listFollows", "getScoringState", "postMatchEvent"} <= ids
    assert len(ids) >= 50


@pytest.mark.parametrize(("method", "path"), MOCK_OPS)
def test_operation_matches_the_backend(method: str, path: str) -> None:
    ours = _ops(mock)[(method, path)]
    theirs = _ops(backend).get((method, path))
    assert theirs is not None, f"{method.upper()} {path} is not in the backend contract"
    assert ours["operationId"] == theirs["operationId"]
    assert _params(ours) == _params(theirs) - {("cookie", "oursport_refresh")}
    assert _body(mock, ours) == _body(backend, theirs)
    our_code, our_shape = _success(mock, ours)
    their_code, their_shape = _success(backend, theirs)
    assert our_code == their_code
    assert _relaxed(our_shape) == _relaxed(their_shape)
