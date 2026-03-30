from __future__ import annotations

import ast
import re
from typing import List

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

class FunctionInfo(BaseModel):
    name: str
    lineno: int
    arg_count: int


class CodeStructure(BaseModel):
    functions: List[FunctionInfo] = []
    classes: List[str] = []
    imports: List[str] = []
    has_error_handling: bool = False


# ---------------------------------------------------------------------------
# Complexity helper
# ---------------------------------------------------------------------------

def _complexity_via_radon(code: str) -> int:
    """Return max cyclomatic complexity across all blocks using radon."""
    try:
        from radon.complexity import cc_visit
        results = cc_visit(code)
        if not results:
            return 1
        return max(r.complexity for r in results)
    except Exception:
        return -1


def _complexity_fallback(code: str) -> int:
    """Simple token-count fallback when radon is unavailable."""
    keywords = [
        r"\bif\b", r"\belif\b", r"\bfor\b", r"\bwhile\b",
        r"\band\b", r"\bor\b", r"\bexcept\b", r"\bcase\b",
        r"\b\?\b",  # ternary in JS-like
        r"&&", r"\|\|",
    ]
    count = 1
    for kw in keywords:
        count += len(re.findall(kw, code))
    return count

# ---------------------------------------------------------------------------
# Python parser (stdlib ast)
# ---------------------------------------------------------------------------

class _PythonVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.functions: list[FunctionInfo] = []
        self.classes: list[str] = []
        self.imports: list[str] = []
        self.has_error_handling: bool = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.functions.append(FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            arg_count=len(node.args.args),
        ))
        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.classes.append(node.name)
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = node.module or ""
        for alias in node.names:
            self.imports.append(f"{module}.{alias.name}" if module else alias.name)

    def visit_Try(self, node: ast.Try) -> None:
        if node.handlers:
            self.has_error_handling = True
        self.generic_visit(node)

    # Python 3.11+ TryStar
    def visit_TryStar(self, node: ast.AST) -> None:
        self.has_error_handling = True
        self.generic_visit(node)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JavaScript / TypeScript parser (regex-based)
# ---------------------------------------------------------------------------

_JS_FUNC_RE = re.compile(
    r"(?:function\s+(?P<name1>\w+)\s*\((?P<args1>[^)]*)\)"
    r"|(?:const|let|var)\s+(?P<name2>\w+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|\w+)\s*=>"
    r"|(?P<name3>\w+)\s*:\s*(?:async\s*)?function\s*\((?P<args3>[^)]*)\))"
)
_JS_CLASS_RE = re.compile(r"(?:^|\s)class\s+(\w+)")
_JS_IMPORT_RE = re.compile(r"(?:import|require)\s*[({]?\s*['\"]([^'\"]+)['\"]")
_JS_TRY_RE = re.compile(r"\btry\s*\{")


def _count_args(args_str: str) -> int:
    args_str = args_str.strip()
    if not args_str:
        return 0
    return len([a for a in args_str.split(",") if a.strip()])


def _parse_js_generic(code: str) -> CodeStructure:
    functions: list[FunctionInfo] = []
    classes: list[str] = []
    imports: list[str] = []
    has_error_handling = bool(_JS_TRY_RE.search(code))

    for lineno, line in enumerate(code.splitlines(), start=1):
        for m in _JS_FUNC_RE.finditer(line):
            name = m.group("name1") or m.group("name2") or m.group("name3") or "<anonymous>"
            args_str = m.group("args1") or m.group("args3") or ""
            functions.append(FunctionInfo(
                name=name, lineno=lineno, arg_count=_count_args(args_str)
            ))
        for m in _JS_CLASS_RE.finditer(line):
            classes.append(m.group(1))
        for m in _JS_IMPORT_RE.finditer(line):
            imports.append(m.group(1))

    return CodeStructure(
        functions=functions,
        classes=classes,
        imports=imports,
        has_error_handling=has_error_handling,
    )


# ---------------------------------------------------------------------------
# ASTParser
# ---------------------------------------------------------------------------

class ASTParser:
    """Parse source code into a structured CodeStructure."""

    # -- Python -------------------------------------------------------------
    def parse_python(self, code: str) -> CodeStructure:
        try:
            tree = ast.parse(code)
            visitor = _PythonVisitor()
            visitor.visit(tree)
            return CodeStructure(
                functions=visitor.functions,
                classes=visitor.classes,
                imports=visitor.imports,
                has_error_handling=visitor.has_error_handling,
            )
        except Exception:
            return CodeStructure()

    # -- JavaScript / TypeScript --------------------------------------------
    def parse_javascript(self, code: str) -> CodeStructure:
        try:
            return _parse_js_generic(code)
        except Exception:
            return CodeStructure()

    # -- Complexity ---------------------------------------------------------
    def get_complexity(self, code: str, language: str) -> int:
        """
        Return cyclomatic complexity.
        Uses radon for Python; falls back to a token-count heuristic for
        other languages or when radon is not installed.
        Returns -1 if analysis failed entirely.
        """
        try:
            if language == "python":
                result = _complexity_via_radon(code)
                if result != -1:
                    return result
            return _complexity_fallback(code)
        except Exception:
            return -1

