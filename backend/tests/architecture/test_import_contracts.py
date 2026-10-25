"""The import-linter contracts must actually catch boundary violations.

Each case copies the code to a temporary directory, adds one import, and runs `lint-imports`
there, so the real tree is never touched.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _lint_with_extra_import(
    tmp_path: Path, importer: str, target: str
) -> subprocess.CompletedProcess[str]:
    for package in ("app", "engine"):
        shutil.copytree(
            ROOT / package, tmp_path / package, ignore=shutil.ignore_patterns("__pycache__")
        )
    shutil.copy(ROOT / "pyproject.toml", tmp_path / "pyproject.toml")

    # Create our own target module if it doesn't exist yet; external packages stay real.
    target_file = tmp_path / Path(*target.split(".")).with_suffix(".py")
    is_ours = target.split(".")[0] in ("app", "engine")
    if is_ours and not target_file.exists() and not target_file.with_suffix("").is_dir():
        target_file.write_text("")
    importer_file = tmp_path / Path(*importer.split(".")).with_suffix(".py")
    importer_file.write_text(f"import {target}\n")

    lint_imports = Path(sys.executable).with_name("lint-imports")
    return subprocess.run(
        [str(lint_imports), "--config", "pyproject.toml"],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.mark.parametrize(
    ("importer", "target", "broken_contract"),
    [
        (
            "app.modules.content.violation",
            "app.modules.scoring.models",
            "Modules talk to each other only through service and schemas",
        ),
        (
            "app.modules.accounts.violation",
            "app.modules.competitions.service",
            "accounts may call only: no other module",
        ),
        (
            "app.modules.scoring.violation",
            "app.modules.analysis.service",
            "scoring may call only: competitions, rules",
        ),
        ("engine.violation", "app.core.time", "Engine is a pure library: no app code"),
        (
            "engine.violation",
            "sqlalchemy",
            "Engine is a pure library: no web, database, cache or logging frameworks",
        ),
        (
            "app.modules.content.violation",
            "engine",
            "Only analysis, rules, setup (and scoring, below) use the engine",
        ),
        (
            "app.modules.scoring.violation",
            "engine.standings",
            "Scoring uses only engine.sports",
        ),
        (
            "app.core.violation",
            "app.modules.accounts",
            "Core infrastructure does not depend on domain modules",
        ),
    ],
    ids=[
        "cross-module-internals",
        "against-dependency-direction",
        "scoring-calls-analysis",
        "engine-imports-app",
        "engine-imports-database",
        "module-uses-engine",
        "scoring-uses-more-than-sports",
        "core-imports-module",
    ],
)
def test_violation_breaks_contract(
    tmp_path: Path, importer: str, target: str, broken_contract: str
) -> None:
    result = _lint_with_extra_import(tmp_path, importer, target)

    assert result.returncode != 0, result.stdout
    assert f"{broken_contract} BROKEN" in result.stdout


def test_allowed_service_call_keeps_all_contracts(tmp_path: Path) -> None:
    result = _lint_with_extra_import(
        tmp_path, "app.modules.scoring.allowed", "app.modules.competitions.service"
    )

    assert result.returncode == 0, result.stdout


def test_no_provider_sdk_outside_the_llm_gateway() -> None:
    """CLAUDE.md rule 4: only app/core/llm imports a model provider SDK."""
    import ast

    root = Path(__file__).resolve().parents[2]
    offenders = []
    for path in [*root.glob("app/**/*.py"), *root.glob("engine/**/*.py")]:
        if "app/core/llm" in path.as_posix():
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names = (
                [a.name for a in node.names]
                if isinstance(node, ast.Import)
                else [node.module or ""]
                if isinstance(node, ast.ImportFrom)
                else []
            )
            if any(n.split(".")[0] in {"anthropic", "openai"} for n in names):
                offenders.append(path.relative_to(root).as_posix())
    assert offenders == []
