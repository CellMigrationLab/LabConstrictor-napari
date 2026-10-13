"""Dev-only check: every function and method has a full annotation.

A function counts as annotated when every parameter except a leading ``self`` / ``cls`` has an
annotation (``*args`` / ``**kwargs`` included) and the return annotation is present (``-> None``
included). Lambdas have no syntax for annotations and are not counted.

One deliberate exception is allowed: a function that is unannotated ON PURPOSE (a test that checks what
happens to a tool declared without annotations) carries `# lc-annotations: skip - <reason>` on its ``def``
line. A marker without a reason does not count, and exempt functions are listed in the output.

Usage:  python scripts/check_annotations.py [PATH ...]
Without paths it checks the covered paths below, relative to the repository root. Exit status 1 and a
list of the offending functions when any is missing; ``--summary`` prints the per-file counts too.
Standard library only; it reads the files, it never imports them.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COVERED = ["napari_labconstrictor", "tests", "scripts"]


def missing_parts(fn: ast.FunctionDef | ast.AsyncFunctionDef, is_method: bool) -> list[str]:
    """Names of what is not annotated: parameters, and 'return'."""
    a = fn.args
    positional = [*a.posonlyargs, *a.args]
    if is_method and positional and positional[0].arg in ("self", "cls"):
        positional = positional[1:]
    params = [*positional, *a.kwonlyargs]
    if a.vararg:
        params.append(a.vararg)
    if a.kwarg:
        params.append(a.kwarg)
    out = [p.arg for p in params if p.annotation is None]
    if fn.returns is None:
        out.append("return")
    return out


SKIP_MARKER = re.compile(r"#\s*lc-annotations:\s*skip\s+-\s+\S")


def scan(path: Path) -> tuple[int, list[tuple[int, str, list[str]]], list[tuple[int, str]]]:
    """(function count, [(line, qualified name, missing parts)], [(line, name) of the exempt ones]) for one file."""
    text = path.read_text(encoding="utf-8")
    source_lines = text.splitlines()
    tree = ast.parse(text, filename=str(path))
    total = 0
    bad: list[tuple[int, str, list[str]]] = []
    exempt: list[tuple[int, str]] = []

    def visit(node: ast.AST, prefix: str, in_class: bool) -> None:
        nonlocal total
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total += 1
                miss = missing_parts(child, in_class)
                if miss and SKIP_MARKER.search(source_lines[child.lineno - 1]):
                    exempt.append((child.lineno, prefix + child.name))
                elif miss:
                    bad.append((child.lineno, prefix + child.name, miss))
                visit(child, prefix + child.name + ".", False)
            elif isinstance(child, ast.ClassDef):
                visit(child, prefix + child.name + ".", True)
            else:
                visit(child, prefix, in_class)

    visit(tree, "", False)
    return total, bad, exempt


def python_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files.extend(f for f in sorted(p.rglob("*.py")) if "__pycache__" not in f.parts)
        elif p.suffix == ".py":
            files.append(p)
    return files


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("paths", nargs="*", help="files or folders (default: the covered paths)")
    ap.add_argument("--summary", action="store_true", help="print the count per file")
    args = ap.parse_args(argv)
    paths = [Path(p) for p in args.paths] or [ROOT / c for c in COVERED if (ROOT / c).exists()]
    n_funcs = n_bad = n_exempt = 0
    lines: list[str] = []
    for f in python_files(paths):
        total, bad, exempt = scan(f)
        n_funcs += total
        n_bad += len(bad)
        n_exempt += len(exempt)
        try:
            shown = f.resolve().relative_to(ROOT)
        except ValueError:
            shown = f
        if args.summary:
            print(f"{shown}: {total - len(bad) - len(exempt)}/{total} annotated, {len(exempt)} exempt")
        for line, name in exempt:
            print(f"{shown}:{line}: {name} is exempt (lc-annotations: skip)")
        lines.extend(f"{shown}:{line}: {name} (missing: {', '.join(miss)})" for line, name, miss in bad)
    if lines:
        print("\n".join(lines))
    print(
        f"{n_funcs} functions, {n_funcs - n_bad - n_exempt} fully annotated, {n_exempt} exempt, {n_bad} not"
    )
    return 1 if n_bad else 0


if __name__ == "__main__":
    sys.exit(main())
