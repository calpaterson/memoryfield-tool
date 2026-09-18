from concurrent.futures import ThreadPoolExecutor
from functools import partial

from . import frontmatter, pages
from .transport import Transport

_MAX_WORKERS = 16


def _row(t: Transport, key: str, *, field_name: str | None) -> dict[str, object]:
    text = t.read_object(key).decode("utf-8")
    fm, _has = frontmatter.parse_frontmatter(text)
    fm_dict = fm if fm is not None else {}
    row: dict[str, object] = {
        "filename": key,
        "title": str(fm_dict.get("title", "")),
        "summary": str(fm_dict.get("summary", "")),
        "created": fm_dict.get("created", ""),
        "updated": fm_dict.get("updated", ""),
    }
    if field_name is not None:
        row["field"] = field_name
    return row


def catalog_field(t: Transport, *, field_name: str | None = None) -> list[dict[str, object]]:
    """Return per-page dicts for a field, in filename order (unsorted).

    Page bodies are read concurrently.  Remote (s3) fields pay one round-trip
    per object, so a serial loop is dominated by latency; a thread pool keeps
    the listing responsive for large remote fields.
    """
    keys = pages.collect_pages(t)
    if len(keys) < 2:
        return [_row(t, key, field_name=field_name) for key in keys]
    workers = min(_MAX_WORKERS, len(keys))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        read = partial(_row, t, field_name=field_name)
        return list(pool.map(read, keys))


def catalog_sort(rows: list[dict[str, object]], sort: str) -> list[dict[str, object]]:
    """Return rows sorted per the awiki catalog sort rules."""
    rows = list(rows)
    if sort == "path":
        rows.sort(key=lambda r: str(r["filename"]))
    elif sort == "title":
        rows.sort(key=lambda r: str(r["title"]).lower())
    elif sort == "created":
        rows.sort(key=lambda r: str(r["created"]), reverse=True)
    elif sort == "updated":
        rows.sort(key=lambda r: str(r["updated"]), reverse=True)
    return rows


def catalog_markdown(rows: list[dict[str, object]], *, show_field: bool = False) -> str:
    """Render rows as a markdown table, optionally with a leading Field column."""
    if show_field:
        out = ["| Field | Page | Summary |", "|-------|------|---------|"]
    else:
        out = ["| Page | Summary |", "|------|---------|"]
    for r in rows:
        summary = str(r["summary"] or "—")
        if len(summary) > 160:
            summary = summary[:157] + "..."
        if show_field:
            out.append(f"| {r['field']} | {r['filename']} | {summary} |")
        else:
            out.append(f"| {r['filename']} | {summary} |")
    return "\n".join(out)
