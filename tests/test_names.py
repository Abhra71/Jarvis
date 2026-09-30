"""Every name the code uses is defined somewhere (1 Oct bug hunt: no linter is installed, and a typo in a
rarely-used path only shows up as a crash in the middle of the user's session, like IsZoomed did on 30 Sep).

Rough but useful: a name read anywhere in a module must be assigned, imported, defined or a parameter somewhere
in that module, or be a builtin."""

import ast
import builtins
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def undefined(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    known = set(dir(builtins)) | {"__file__", "__name__", "__doc__", "__spec__", "__path__"}
    used: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                used.append((node.id, node.lineno))
            else:
                known.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            known.add(node.name)
        elif isinstance(node, ast.arg):
            known.add(node.arg)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for a in node.names:
                known.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ExceptHandler) and node.name:
            known.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            known.update(node.names)
        elif isinstance(node, ast.MatchAs) and node.name:
            known.add(node.name)
        elif isinstance(node, ast.MatchStar) and node.name:
            known.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            known.add(node.rest)
    return [f"{path.relative_to(ROOT)}:{line} {name}" for name, line in used if name not in known]


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def missing_attributes(path: Path) -> list[str]:
    """`desktop.something(...)` where `desktop` is one of Jarvis's own modules and has no `something`."""
    import importlib
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    here = _module_name(path)
    package = here if path.name == "__init__.py" else here.rpartition(".")[0]
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                up = package.split(".")
                up = up[:len(up) - (node.level - 1)] if node.level > 1 else up
                base = ".".join(up + ([base] if base else []))
            for a in node.names:
                full = f"{base}.{a.name}" if base else a.name
                if full.startswith("jarvis"):
                    aliases[a.asname or a.name] = full
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("jarvis") and a.asname:
                    aliases[a.asname] = a.name
    problems = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in aliases:
            try:
                mod = importlib.import_module(aliases[node.value.id])
            except ImportError:
                continue  # a name imported from a module (a function or class), not a module itself
            if not hasattr(mod, node.attr):
                problems.append(f"{path.relative_to(ROOT)}:{node.lineno} {node.value.id}.{node.attr}")
    return problems


class NamesTest(unittest.TestCase):
    def test_calls_into_our_own_modules_exist(self):
        problems = []
        for path in sorted((ROOT / "jarvis").rglob("*.py")):
            problems += missing_attributes(path)
        self.assertEqual(problems, [])

    def test_no_undefined_names(self):
        problems = []
        for folder in ("jarvis", "tools"):
            for path in sorted((ROOT / folder).rglob("*.py")):
                problems += undefined(path)
        self.assertEqual(problems, [])


if __name__ == "__main__":
    unittest.main()
