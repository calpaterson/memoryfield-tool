import contextlib
import json
from dataclasses import dataclass
from pathlib import Path

import click
import sqlite_vec

from . import config, embed, fields, frontmatter, pages
from .db import sqlite3
from .transport import Transport, TransportError

RESULT_LIMIT = 20


@dataclass(frozen=True)
class SearchResult:
    filename: str
    summary: str
    distance: float | None
    frontmatter: dict[str, object] | None = None


def _open_index(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path), timeout=5.0)
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def _summary_from_json(fm_json: str) -> str:
    try:
        fm = json.loads(fm_json)
    except ValueError:
        return ""
    if not isinstance(fm, dict):
        return ""
    summary = fm.get("summary")
    return str(summary) if summary is not None else ""


def _vector_search(index_loc: Path, query: str) -> list[SearchResult] | None:
    if not index_loc.is_file():
        return None
    result = embed.embed_texts([f"search_query: {query}"])
    if result is None:
        return None
    [qvec] = result
    qblob = sqlite_vec.serialize_float32(qvec)

    with contextlib.closing(_open_index(index_loc)) as db:
        cur = db.execute(
            "SELECT filename, vec_distance_cosine(embedding, ?) AS distance "
            f"FROM pages ORDER BY distance LIMIT {RESULT_LIMIT}",
            (qblob,),
        )
        rows = cur.fetchall()

    return [
        SearchResult(
            filename=filename,
            summary=_summary_from_index(index_loc, filename),
            distance=float(distance),
            frontmatter=_frontmatter_from_index(index_loc, filename),
        )
        for filename, distance in rows
    ]


def _frontmatter_from_index(index_loc: Path, filename: str) -> dict[str, object] | None:
    with contextlib.closing(_open_index(index_loc)) as db:
        row = db.execute("SELECT frontmatter FROM pages WHERE filename = ?", (filename,)).fetchone()
    if row is None:
        return None
    try:
        fm = json.loads(row[0])
    except ValueError:
        return None
    return fm if isinstance(fm, dict) else None


def _summary_from_index(index_loc: Path, filename: str) -> str:
    with contextlib.closing(_open_index(index_loc)) as db:
        row = db.execute("SELECT frontmatter FROM pages WHERE filename = ?", (filename,)).fetchone()
    if row is None:
        return ""
    return _summary_from_json(row[0])


def _substring_search(t: Transport, query: str) -> list[SearchResult]:
    needle = query.lower()
    results: list[SearchResult] = []
    for key in pages.collect_pages(t):
        text = t.read_object(key).decode("utf-8", errors="replace")
        fm, _has = frontmatter.parse_frontmatter(text)
        fm_dict = fm if fm is not None else {}
        title = str(fm_dict.get("title", ""))
        summary = str(fm_dict.get("summary", ""))
        if needle in key.lower() or needle in title.lower() or needle in summary.lower():
            results.append(
                SearchResult(
                    filename=key,
                    summary=summary,
                    distance=None,
                    frontmatter=fm,
                )
            )
    return results[:RESULT_LIMIT]


def search_field(t: Transport, index_loc: Path, query: str) -> list[SearchResult]:
    vector = _vector_search(index_loc, query)
    if vector:
        return vector
    return _substring_search(t, query)


def search_all(
    field_list: list[config.Field], query: str
) -> tuple[list[tuple[str, SearchResult]], list[tuple[str, str]]]:
    """Search all fields, skipping unreachable ones.

    Returns (results, errors) where errors is a list of (field_name, message)
    for fields whose transport failed (dead directory, unreachable bucket).
    """
    results: list[tuple[str, SearchResult]] = []
    errors: list[tuple[str, str]] = []
    for field in field_list:
        try:
            t = fields.get_transport(field)
            loc = fields.index_location(field)
            for result in search_field(t, loc, query):
                results.append((field.name, result))
        except (TransportError, click.ClickException) as e:
            errors.append((field.name, str(e)))
    return results, errors
