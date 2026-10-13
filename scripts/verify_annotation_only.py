"""Dev-only proof that a change touched annotations and nothing else.

For every .py file that differs between BASE (default: origin/main) and the working tree, both versions are parsed and
everything that cannot change what the program does is removed from the syntax tree, then the two trees are compared with
``ast.dump``. Removed on both sides:

  * parameter annotations and return annotations of functions;
  * the annotation of ``x: T = v`` (it stays as the plain assignment ``x = v``) and a bare ``x: T`` (it disappears);
  * ``from __future__ import annotations``;
  * the name ``TYPE_CHECKING`` in ``from typing import ...``, and ``if TYPE_CHECKING:`` blocks that only import.

Anything else that differs (a changed expression, an added statement, a moved import) is reported as a DIFFERENCE and the
exit status is 1. Files that were added or deleted are listed, not compared. ``--allow PATH`` names a file whose difference is
intended (it is reported, and does not fail the run).

Usage:  python scripts/verify_annotation_only.py [--base REF] [--allow PATH ...]
Standard library only; it never imports the files it compares.
"""

from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _only_imports(body: list[ast.stmt]) -> bool:
    return all(isinstance(n, (ast.Import, ast.ImportFrom)) for n in body)


class Strip(ast.NodeTransformer):
    """Removes annotations and the type-checking-only scaffolding."""

    def _function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> ast.AST:
        a = node.args
        for arg in [
            *a.posonlyargs,
            *a.args,
            *a.kwonlyargs,
            *([a.vararg] if a.vararg else []),
            *([a.kwarg] if a.kwarg else []),
        ]:
            arg.annotation = None
        node.returns = None
        self.generic_visit(node)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        return self._function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        return self._function(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> ast.AST | None:
        self.generic_visit(node)
        if node.value is None:
            return None
        return ast.copy_location(ast.Assign(targets=[node.target], value=node.value, type_comment=None), node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.AST | None:
        if node.module == "__future__":
            node.names = [n for n in node.names if n.name != "annotations"]
        if node.module == "typing":
            node.names = [n for n in node.names if n.name != "TYPE_CHECKING"]
        return node if node.names else None

    def visit_If(self, node: ast.If) -> ast.AST | None:
        if (
            isinstance(node.test, ast.Name)
            and node.test.id == "TYPE_CHECKING"
            and not node.orelse
            and _only_imports(node.body)
        ):
            return None
        self.generic_visit(node)
        return node


def normalised(source: str, filename: str) -> str:
    tree = Strip().visit(ast.parse(source, filename=filename))
    return ast.dump(ast.fix_missing_locations(tree))


def git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603 - fixed argument list, no shell
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
    )
    return done.stdout


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--base", default="origin/main", help="the version to compare with (a git ref)")
    ap.add_argument(
        "--allow", action="append", default=[], metavar="PATH", help="a file whose difference is intended"
    )
    args = ap.parse_args(argv)

    changed = [p for p in git("diff", "--name-status", args.base, "--", "*.py").splitlines() if p.strip()]
    compared = 0
    identical: list[str] = []
    intended: list[str] = []
    different: list[str] = []
    added: list[str] = []
    deleted: list[str] = []
    for row in changed:
        status, _, path = row.partition("\t")
        if status.startswith("A"):
            added.append(path)
            continue
        if status.startswith("D"):
            deleted.append(path)
            continue
        if status.startswith("R"):
            path = path.split("\t")[-1]
        old = git("show", f"{args.base}:{path}")
        new = (ROOT / path).read_text(encoding="utf-8")
        compared += 1
        same = normalised(old, path) == normalised(new, path)
        if same:
            identical.append(path)
        elif path in args.allow:
            intended.append(path)
        else:
            different.append(path)
    print(f"compared {compared} changed .py files against {args.base}")
    print(f"  identical after stripping annotations: {len(identical)}")
    print(f"  intentional differences ({len(intended)}): {', '.join(intended) or 'none'}")
    print(f"  DIFFERENCES: {len(different)}")
    for path in different:
        print(f"    DIFFERENT: {path}")
    print(f"  added files (not compared): {', '.join(added) or 'none'}")
    if deleted:
        print(f"  deleted files (not compared): {', '.join(deleted)}")
    print("identical" if not different else "NOT IDENTICAL")
    return 1 if different else 0


if __name__ == "__main__":
    sys.exit(main())
