from __future__ import annotations

import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[2] / "src" / "saki_api"
BUSINESS_MODULES = {"runtime", "annotation", "project", "access", "system", "storage", "app"}

_REPO_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+saki_api\.(?:modules\.)?([a-z_]+)\.repo(?:\.|\b)")
_DOMAIN_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+saki_api\.(?:modules\.)?([a-z_]+)\.domain(?:\.|\b)")


def _iter_python_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT)
        if "__pycache__" in rel.parts:
            continue
        files.append(path)
    return files


def _resolve_module_context(rel: pathlib.PurePath) -> str | None:
    if not rel.parts:
        return None
    if rel.parts[0] == "modules" and len(rel.parts) >= 2:
        module_name = rel.parts[1]
        if module_name in BUSINESS_MODULES:
            return module_name
        return None
    module_name = rel.parts[0]
    if module_name in BUSINESS_MODULES:
        return module_name
    return None


def _is_api_layer_file(rel: pathlib.PurePath) -> bool:
    if len(rel.parts) < 2:
        return False
    if rel.parts[0] == "modules":
        return len(rel.parts) >= 4 and rel.parts[2] == "api"
    return rel.parts[1] == "api"


def test_no_api_direct_repo_imports() -> None:
    violations: list[str] = []
    for file_path in _iter_python_files():
        rel = file_path.relative_to(ROOT)
        if not _is_api_layer_file(rel):
            continue
        for idx, line in enumerate(file_path.read_text().splitlines(), 1):
            if _REPO_IMPORT_RE.match(line):
                violations.append(f"{rel}:{idx} -> {line.strip()}")
    assert not violations, "API 层禁止直接 import repo:\n" + "\n".join(violations)


def test_no_cross_module_repo_imports_in_business_modules() -> None:
    violations: list[str] = []
    for file_path in _iter_python_files():
        rel = file_path.relative_to(ROOT)
        current_module = _resolve_module_context(rel)
        if current_module is None:
            continue
        for idx, line in enumerate(file_path.read_text().splitlines(), 1):
            match = _REPO_IMPORT_RE.match(line)
            if not match:
                continue
            target_module = match.group(1)
            if target_module != current_module:
                violations.append(f"{rel}:{idx} -> {line.strip()}")
    assert not violations, "业务模块禁止跨模块直接 import repo:\n" + "\n".join(violations)


def test_api_layer_no_cross_module_domain_imports() -> None:
    violations: list[str] = []
    for file_path in _iter_python_files():
        rel = file_path.relative_to(ROOT)
        if not _is_api_layer_file(rel):
            continue
        current_module = _resolve_module_context(rel)
        if current_module is None:
            continue
        for idx, line in enumerate(file_path.read_text().splitlines(), 1):
            match = _DOMAIN_IMPORT_RE.match(line)
            if not match:
                continue
            target_module = match.group(1)
            if target_module != current_module:
                violations.append(f"{rel}:{idx} -> {line.strip()}")
    assert not violations, "API 层禁止跨模块直接 import domain:\n" + "\n".join(violations)
