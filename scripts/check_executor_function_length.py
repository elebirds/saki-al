#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class FunctionStat:
    length: int
    file_path: Path
    start_line: int
    end_line: int
    qualified_name: str


def _iter_python_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*.py")):
        if "grpc_gen" in path.parts:
            continue
        yield path


def collect_function_stats(root: Path) -> list[FunctionStat]:
    stats: list[FunctionStat] = []
    for path in _iter_python_files(root):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        class Visitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self.scope: list[str] = []

            def visit_ClassDef(self, node: ast.ClassDef) -> None:
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                self._record(node)
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
                self._record(node)
                self.scope.append(node.name)
                self.generic_visit(node)
                self.scope.pop()

            def _record(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                end_line = getattr(node, "end_lineno", None)
                if not end_line:
                    return
                stats.append(
                    FunctionStat(
                        length=end_line - node.lineno + 1,
                        file_path=path,
                        start_line=node.lineno,
                        end_line=end_line,
                        qualified_name=".".join([*self.scope, node.name]),
                    )
                )

        Visitor().visit(tree)
    return sorted(stats, key=lambda item: item.length, reverse=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit function lengths for saki-executor.")
    parser.add_argument(
        "--root",
        default="saki-executor/src/saki_executor",
        help="Root directory to scan.",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=30,
        help="Show top N longest functions.",
    )
    parser.add_argument(
        "--target-soft",
        type=int,
        default=60,
        help="Soft target for readable function size.",
    )
    parser.add_argument(
        "--max-hard",
        type=int,
        default=100,
        help="Hard threshold for oversized functions.",
    )
    parser.add_argument(
        "--fail-on-hard",
        action="store_true",
        help="Exit with non-zero code when hard threshold is exceeded.",
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    stats = collect_function_stats(root)
    hard = [item for item in stats if item.length > args.max_hard]
    soft = [item for item in stats if item.length > args.target_soft]

    print(f"scan_root={root}")
    print(f"total_functions={len(stats)}")
    print(f"over_soft({args.target_soft})={len(soft)}")
    print(f"over_hard({args.max_hard})={len(hard)}")
    print("")
    print("length  file:lines  name")
    for item in stats[: max(1, args.top)]:
        rel_path = item.file_path.relative_to(Path.cwd())
        print(f"{item.length:6d}  {rel_path}:{item.start_line}-{item.end_line}  {item.qualified_name}")

    if hard:
        print("")
        print("hard_threshold_violations:")
        for item in hard:
            rel_path = item.file_path.relative_to(Path.cwd())
            print(f"- {rel_path}:{item.start_line}-{item.end_line} {item.qualified_name} ({item.length})")

    if args.fail_on_hard and hard:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

