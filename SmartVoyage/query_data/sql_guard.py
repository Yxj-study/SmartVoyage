"""Conservative validation for model-produced read-only SQL."""

from __future__ import annotations

import re
from collections.abc import Iterable


_COMMENT_MARKERS = ("--", "#", "/*", "*/")
_FORBIDDEN_KEYWORDS = (
    "ALTER",
    "CALL",
    "CREATE",
    "DELETE",
    "DROP",
    "GRANT",
    "HANDLER",
    "INSERT",
    "LOAD",
    "LOCK",
    "RENAME",
    "REPLACE",
    "REVOKE",
    "SET",
    "TRUNCATE",
    "UNLOCK",
    "UPDATE",
    "USE",
)
_TABLE_REFERENCE = re.compile(
    r"\b(?:FROM|JOIN)\s+(`?[A-Za-z_][\w$]*`?(?:\s*\.\s*`?[A-Za-z_][\w$]*`?)?)",
    re.IGNORECASE,
)


def _normalize_identifier(identifier: str) -> str:
    parts = [part.strip().strip("`").lower() for part in identifier.split(".")]
    return ".".join(parts)


def validate_read_only_query(sql: str, allowed_tables: Iterable[str]) -> str:
    """Return normalized SQL when it is a single, allowed-table SELECT.

    This guard is intentionally conservative because its input may come from a
    language model. Unsupported syntax is rejected instead of being guessed.
    """

    if not isinstance(sql, str) or not sql.strip() or "\x00" in sql:
        raise ValueError("只允许单条只读 SELECT")

    normalized = sql.strip()
    if any(marker in normalized for marker in _COMMENT_MARKERS):
        raise ValueError("不允许 SQL 注释")

    if normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    if ";" in normalized:
        raise ValueError("只允许单条只读 SELECT")

    if not re.match(r"^SELECT\b", normalized, re.IGNORECASE):
        raise ValueError("只允许单条只读 SELECT")

    keyword_pattern = r"\b(?:" + "|".join(_FORBIDDEN_KEYWORDS) + r")\b"
    if re.search(keyword_pattern, normalized, re.IGNORECASE):
        raise ValueError("只允许单条只读 SELECT")

    if re.search(r"\bINTO\s+(?:OUTFILE|DUMPFILE|@)", normalized, re.IGNORECASE):
        raise ValueError("禁止文件或变量输出")

    if re.search(r"\b(?:FROM|JOIN)\s*\(", normalized, re.IGNORECASE):
        raise ValueError("不支持子查询数据源")

    table_references = [
        _normalize_identifier(match.group(1))
        for match in _TABLE_REFERENCE.finditer(normalized)
    ]
    if not table_references:
        raise ValueError("查询必须访问允许的数据表")

    allowed = {_normalize_identifier(table) for table in allowed_tables}
    for reference in table_references:
        if reference not in allowed:
            raise ValueError(f"不允许访问数据表: {reference}")

    return normalized
