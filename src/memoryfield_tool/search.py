import json
from dataclasses import dataclass
from pathlib import Path

import pysqlite3 as sqlite3
import sqlite_vec

from . import config, embed, fields, frontmatter, index, pages

SEARCH_DISTANCE = 0.7


@dataclass(frozen=True)
class SearchResult:
    filename: str
    summary: str
    distance: float | None


def _open_index(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(str(path))
    db.enable_load_extension(True)
    sqlite_vec.load(db)
    db.enable_load_extension(False)
    return db


def _summary_from_json(fm_json: str) -> str:
    try:
        fm = json.loads(fm_json)
    except ValueError, TypeError:
        return ""
    if not isinstance(fm, dict):
        return ""
    summary = fm.get("summary")
    return str(summary) if summary is not None else ""


def _vector_search(root: Path, query: str) -> list[SearchResult] | None:
    idx = index.index_path(root)
    if not idx.is_file():
        return None
    result = embed.embed_texts([f"search_query: {query}"])
    if result is None:
        return None
    [qvec] = result
    qblob = sqlite_vec.serialize_float32(qvec)

    db = _open_index(idx)
    try:
        cur = db.execute(
            "SELECT filename, vec_distance_cosine(embedding, ?) AS distance "
            "FROM pages ORDER BY distance LIMIT 20",
            (qblob,),
        )
        rows = cur.fetchall()
    finally:
        db.close()

    results: list[SearchResult] = []
    for filename, distance in rows:
        if distance >= SEARCH_DISTANCE:
            continue
        results.append(
            SearchResult(
                filename=filename,
                summary=_summary_from_index(idx, filename),
                distance=float(distance),
            )
        )
    return results


def _summary_from_index(idx: Path, filename: str) -> str:
    db = _open_index(idx)
    try:
        row = db.execute("SELECT frontmatter FROM pages WHERE filename = ?", (filename,)).fetchone()
    finally:
        db.close()
    if row is None:
        return ""
    return _summary_from_json(row[0])


def _substring_search(root: Path, query: str) -> list[SearchResult]:
    needle = query.lower()
    results: list[SearchResult] = []
    for f in pages.collect_pages(root):
        text = f.read_text("utf-8", errors="replace")
        fm, _has = frontmatter.parse_frontmatter(text)
        fm_dict = fm if fm is not None else {}
        title = str(fm_dict.get("title", ""))
        summary = str(fm_dict.get("summary", ""))
        if needle in f.name.lower() or needle in title.lower() or needle in summary.lower():
            results.append(SearchResult(filename=f.name, summary=summary, distance=None))
    return results


def search_field(root: Path, query: str) -> list[SearchResult]:
    vector = _vector_search(root, query)
    if vector:
        return vector
    return _substring_search(root, query)


def search_all(field_list: list[config.Field], query: str) -> list[tuple[str, SearchResult]]:
    results: list[tuple[str, SearchResult]] = []
    for field in field_list:
        root = fields.field_root(field)
        for result in search_field(root, query):
            results.append((field.name, result))
    return results
