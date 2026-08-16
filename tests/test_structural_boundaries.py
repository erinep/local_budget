"""Structural tests for agent-legible architecture boundaries."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"


def _python_files() -> list[Path]:
    return sorted(APP.rglob("*.py"))


def _module_name(path: Path) -> str:
    return ".".join(path.relative_to(ROOT).with_suffix("").parts)


def _imports(path: Path) -> list[tuple[str, str | None]]:
    tree = ast.parse(path.read_text(), filename=str(path))
    imports: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend((alias.name, None) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            imports.extend((module, alias.name) for alias in node.names)
    return imports


def test_supabase_sdk_is_not_imported_by_application_code() -> None:
    offenders: list[str] = []
    for path in _python_files():
        for module, _name in _imports(path):
            if module == "supabase" or module.startswith("supabase."):
                offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []


def test_route_modules_do_not_import_other_route_modules() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if path.name != "routes.py":
            continue
        current_module = _module_name(path)
        for module, _name in _imports(path):
            if module.endswith(".routes") and module != current_module:
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")

    assert offenders == []


def test_service_modules_do_not_import_flask_request_or_session() -> None:
    forbidden = {"request", "session"}
    offenders: list[str] = []

    for path in _python_files():
        if path.name != "services.py":
            continue
        for module, name in _imports(path):
            if module == "flask" and name in forbidden:
                offenders.append(f"{path.relative_to(ROOT)} imports flask.{name}")

    assert offenders == []


def test_service_modules_do_not_import_route_modules() -> None:
    offenders: list[str] = []

    for path in _python_files():
        if path.name != "services.py":
            continue
        for module, _name in _imports(path):
            if module.startswith("app.") and module.endswith(".routes"):
                offenders.append(f"{path.relative_to(ROOT)} imports {module}")

    assert offenders == []
