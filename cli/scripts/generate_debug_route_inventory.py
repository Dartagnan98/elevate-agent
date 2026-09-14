#!/usr/bin/env python3
"""Generate the desktop debugging route inventory TSV."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
ROUTE_DECORATOR_RE = re.compile(
    r"^\s*@(app|router)\.(get|post|put|patch|delete|websocket)\(\s*['\"]([^'\"]+)['\"]",
)
HOSTED_METHOD_RE = re.compile(
    r"^\s*export\s+(?:async\s+)?function\s+(GET|POST|PUT|PATCH|DELETE)\b",
)


@dataclass(frozen=True)
class RouteRow:
    surface: str
    kind: str
    method: str
    path: str
    family: str
    file: str
    line: int


def route_family(path: str) -> str:
    parts = [part for part in path.strip("/").split("/") if part]
    if not parts:
        return "root"
    if parts[0] == "api":
        if len(parts) >= 3 and parts[1] == "plugins":
            return f"plugin:{parts[2]}"
        return parts[1] if len(parts) > 1 else "api"
    return parts[0]


def iter_decorated_routes(path: Path) -> list[tuple[str, str, int]]:
    routes: list[tuple[str, str, int]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = ROUTE_DECORATOR_RE.match(line)
        if not match:
            continue
        _, method, route_path = match.groups()
        routes.append((method.upper() if method != "websocket" else "WEBSOCKET", route_path, line_no))
    return routes


def iter_local_rows(repo_root: Path) -> list[RouteRow]:
    roots = [
        repo_root / "cli/elevate_cli/web_server.py",
        repo_root / "cli/elevate_cli/web_routes",
    ]
    rows: list[RouteRow] = []
    for root in roots:
        paths = [root] if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            rel = path.relative_to(repo_root).as_posix()
            for method, route_path, line_no in iter_decorated_routes(path):
                rows.append(
                    RouteRow(
                        surface="local",
                        kind="websocket" if method == "WEBSOCKET" else "http",
                        method=method,
                        path=route_path,
                        family=route_family(route_path),
                        file=rel,
                        line=line_no,
                    ),
                )
    return rows


def iter_plugin_rows(repo_root: Path) -> list[RouteRow]:
    rows: list[RouteRow] = []
    for manifest_path in sorted((repo_root / "cli/plugins").glob("*/dashboard/manifest.json")):
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        api_name = manifest.get("api")
        plugin_name = manifest.get("name")
        if not api_name or not plugin_name:
            continue
        api_path = manifest_path.parent / str(api_name)
        if not api_path.exists():
            continue
        rel = api_path.relative_to(repo_root).as_posix()
        prefix = f"/api/plugins/{plugin_name}"
        for method, route_path, line_no in iter_decorated_routes(api_path):
            rows.append(
                RouteRow(
                    surface="local_plugin",
                    kind="websocket" if method == "WEBSOCKET" else "http",
                    method=method,
                    path=f"{prefix}{route_path}",
                    family=f"plugin:{plugin_name}",
                    file=rel,
                    line=line_no,
                ),
            )
    return rows


def hosted_path(api_root: Path, route_file: Path) -> str:
    route_dir = route_file.parent.relative_to(api_root).as_posix()
    return "/api" if route_dir == "." else f"/api/{route_dir}"


def iter_hosted_rows(repo_root: Path) -> list[RouteRow]:
    api_root = repo_root / "backend/src/app/api"
    rows: list[RouteRow] = []
    for route_file in sorted(api_root.rglob("route.ts")):
        rel = route_file.relative_to(repo_root).as_posix()
        route_path = hosted_path(api_root, route_file)
        for line_no, line in enumerate(route_file.read_text(encoding="utf-8").splitlines(), start=1):
            match = HOSTED_METHOD_RE.match(line)
            if not match:
                continue
            rows.append(
                RouteRow(
                    surface="hosted",
                    kind="http",
                    method=match.group(1),
                    path=route_path,
                    family=route_family(route_path),
                    file=rel,
                    line=line_no,
                ),
            )
    return rows


def generate_rows(repo_root: Path = REPO_ROOT) -> list[RouteRow]:
    rows = iter_local_rows(repo_root) + iter_plugin_rows(repo_root) + iter_hosted_rows(repo_root)
    return sorted(rows, key=lambda row: (row.surface, row.path, row.method, row.file, row.line))


def to_tsv(rows: list[RouteRow]) -> str:
    lines = ["surface\tkind\tmethod\tpath\tfamily\tfile\tline"]
    lines.extend(
        "\t".join(
            [
                row.surface,
                row.kind,
                row.method,
                row.path,
                row.family,
                row.file,
                str(row.line),
            ],
        )
        for row in rows
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    print(to_tsv(generate_rows()), end="")


if __name__ == "__main__":
    main()
