"""AST-based symbol existence check — no code is executed."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path

from ..models import Claim, Evidence, Verdict

_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".tox", "build", "dist"}
_FUNC_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_DEF_NODES = (*_FUNC_NODES, ast.ClassDef)


@dataclass(frozen=True)
class SymbolDef:
    """One place a name is defined in the tree."""

    qualname: str  # e.g. "urls.parse_url" or "Client.fetch"
    file: str  # path relative to the scanned root
    line: int


def _iter_py_files(root: Path):
    for path in sorted(root.rglob("*.py")):
        if any(part in _SKIP_DIRS for part in path.parts):
            continue
        yield path


def find_definitions(root: Path, name: str) -> list[SymbolDef]:
    """Find every top-level function/class/method definition matching ``name``."""
    matches: list[SymbolDef] = []
    for path in _iter_py_files(root):
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        rel = path.relative_to(root).as_posix()
        for node in tree.body:  # top-level only is enough for v1
            if isinstance(node, _DEF_NODES) and node.name == name:
                matches.append(SymbolDef(qualname=node.name, file=rel, line=node.lineno))
            elif isinstance(node, ast.ClassDef):
                for item in node.body:
                    if isinstance(item, _FUNC_NODES) and item.name == name:
                        qualname = f"{node.name}.{item.name}"
                        matches.append(SymbolDef(qualname=qualname, file=rel, line=item.lineno))
    return matches


def _did_you_mean(name: str, all_names: set[str]) -> list[str]:
    return get_close_matches(name, all_names, n=3, cutoff=0.6)


def _all_defined_names(root: Path) -> set[str]:
    names: set[str] = set()
    for path in _iter_py_files(root):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(node.name)
                if isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            names.add(item.name)
    return names


def check_symbol(root: Path, name: str) -> Evidence:
    """Check whether ``name`` is defined anywhere under ``root``."""
    defs = find_definitions(root, name)
    if defs:
        locations = [{"file": d.file, "line": d.line, "qualname": d.qualname} for d in defs]
        return Evidence(
            check="symbol_exists",
            verdict=Verdict.CONFIRMED,
            summary=f"✓ {name}() exists ({len(defs)} definition{'s' if len(defs) != 1 else ''})",
            details={"name": name, "locations": locations},
            sandboxed=False,
        )

    suggestions = _did_you_mean(name, _all_defined_names(root))
    return Evidence(
        check="symbol_exists",
        verdict=Verdict.REFUTED,
        summary=f"✗ {name}() does not exist",
        details={"name": name, "did_you_mean": suggestions},
        sandboxed=False,
    )


def check_symbols(root: Path, claim: Claim) -> list[Evidence]:
    """Run the symbol check for every symbol referenced in the claim."""
    return [check_symbol(root, sym) for sym in claim.symbols]
