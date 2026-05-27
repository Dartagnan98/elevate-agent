#!/usr/bin/env python3
"""Translate a SQLite .schema dump to PostgreSQL DDL.

Two-pass:
  1. Regex passes for type renames / SQLite-only clauses.
  2. CREATE TABLE rewrite — strip inline FOREIGN KEY clauses, re-emit
     them as ALTER TABLE ... ADD CONSTRAINT at the end of the file.
     SQLite tolerates forward FK references; Postgres requires the
     referenced table to exist at CREATE time.

Designed for Elevate's operational.db head schema. Anything more
exotic should be hand-ported.
"""

import re
import sys


def _phase1(sql: str) -> str:
    out = sql

    # BLOB -> BYTEA
    out = re.sub(r"\bBLOB\b", "BYTEA", out)

    # REAL -> DOUBLE PRECISION (sqlite REAL is 8-byte IEEE float)
    out = re.sub(r"\bREAL\b", "DOUBLE PRECISION", out)

    # Strip SQLite-only keywords/clauses.
    out = re.sub(r"\bAUTOINCREMENT\b", "", out, flags=re.IGNORECASE)
    out = re.sub(r"^\s*PRAGMA[^;]*;\s*$", "", out, flags=re.MULTILINE | re.IGNORECASE)
    out = re.sub(r"\bWITHOUT\s+ROWID\b", "", out, flags=re.IGNORECASE)

    # Internal sqlite tables in dumps.
    out = re.sub(
        r"CREATE TABLE sqlite_[a-z_]+\s*\([^;]+\);\s*",
        "",
        out,
        flags=re.IGNORECASE | re.DOTALL,
    )
    out = re.sub(
        r"INSERT INTO sqlite_sequence[^;]*;\s*",
        "",
        out,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return out


_CREATE_TABLE_HEAD_RE = re.compile(
    r"CREATE TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+(?:\"([^\"]+)\"|(\w+))\s*\(",
    re.IGNORECASE,
)


def _find_create_tables(sql: str):
    """Yield (start_idx, end_idx, table_name, body) for each CREATE TABLE.

    Walks the open-paren forward with depth tracking, ignoring chars
    inside single-quoted strings and `--` line comments, so nested
    ``CHECK (...)`` parens don't break the match.
    """
    for m in _CREATE_TABLE_HEAD_RE.finditer(sql):
        name = m.group(1) or m.group(2)
        i = m.end()  # just past the opening `(`
        depth = 1
        in_sq = False
        while i < len(sql) and depth > 0:
            ch = sql[i]
            if not in_sq and ch == "-" and i + 1 < len(sql) and sql[i + 1] == "-":
                j = sql.find("\n", i)
                if j == -1:
                    i = len(sql)
                    break
                i = j + 1
                continue
            if ch == "'":
                in_sq = not in_sq
            elif not in_sq:
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                    if depth == 0:
                        body = sql[m.end() : i]
                        # consume trailing `;`
                        end = i + 1
                        while end < len(sql) and sql[end] in " \t":
                            end += 1
                        if end < len(sql) and sql[end] == ";":
                            end += 1
                        yield m.start(), end, name, body
                        break
            i += 1


def _strip_line_comments(s: str) -> str:
    """Remove ``-- ...\\n`` comments while preserving newlines."""
    out: list[str] = []
    i = 0
    in_sq = False  # single-quoted string
    while i < len(s):
        ch = s[i]
        if not in_sq and ch == "-" and i + 1 < len(s) and s[i + 1] == "-":
            # consume to end of line
            j = s.find("\n", i)
            if j == -1:
                break
            i = j  # keep the newline
            continue
        if ch == "'":
            in_sq = not in_sq
        out.append(ch)
        i += 1
    return "".join(out)


def _split_top_level(body: str) -> list[str]:
    """Split a CREATE TABLE body on top-level commas (ignore nested parens)."""
    body = _strip_line_comments(body)
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in body:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    if buf:
        last = "".join(buf).strip()
        if last:
            parts.append(last)
    return parts


_FK_RE = re.compile(
    r"^FOREIGN\s+KEY\s*\(\s*([^)]+?)\s*\)\s*REFERENCES\s+(\w+)\s*\(\s*([^)]+?)\s*\)(.*)$",
    re.IGNORECASE | re.DOTALL,
)


def _rewrite_create_table(table: str, body: str) -> tuple[str, list[str]]:
    """Rewrite a CREATE TABLE; return (new_create_stmt, list_of_fk_alters)."""
    parts = _split_top_level(body)
    keep: list[str] = []
    fk_alters: list[str] = []
    fk_idx = 0
    for p in parts:
        m = _FK_RE.match(p)
        if m:
            cols, ref_tbl, ref_cols, tail = m.groups()
            fk_idx += 1
            cname = f"fk_{table}_{fk_idx}"
            alter = (
                f"ALTER TABLE {table} ADD CONSTRAINT {cname} "
                f"FOREIGN KEY ({cols.strip()}) REFERENCES {ref_tbl.strip()}({ref_cols.strip()})"
                f"{tail.rstrip()};"
            )
            fk_alters.append(alter)
        else:
            keep.append(p)
    new_body = ",\n    ".join(keep)
    new_create = f"CREATE TABLE {table} (\n    {new_body}\n);"
    return new_create, fk_alters


def translate(sql: str) -> str:
    sql = _phase1(sql)

    out_chunks: list[str] = []
    fk_alters_all: list[str] = []
    pos = 0
    for start, end, name, body in _find_create_tables(sql):
        out_chunks.append(sql[pos:start])
        new_create, fks = _rewrite_create_table(name, body)
        out_chunks.append(new_create)
        fk_alters_all.extend(fks)
        pos = end
    out_chunks.append(sql[pos:])

    body = "".join(out_chunks)
    if fk_alters_all:
        body += "\n\n-- Foreign keys (deferred to end so referenced tables exist)\n"
        body += "\n".join(fk_alters_all)
        body += "\n"
    return body


if __name__ == "__main__":
    src = sys.stdin.read()
    sys.stdout.write(translate(src))
