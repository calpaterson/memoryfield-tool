import re
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date as _date_type
from datetime import datetime as _datetime_type
from pathlib import Path

from . import embed, frontmatter, pages
from .transport import Transport

_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
MDLINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


@dataclass(frozen=True)
class Issue:
    level: str
    filename: str
    message: str


def _is_external_link(url: str) -> bool:
    return bool(_URI_SCHEME_RE.match(url)) or url.startswith("//") or url.startswith("#")


def has_unquoted_datetime(fm: dict[str, object]) -> bool:
    return any(
        isinstance(fm.get(field), (_date_type, _datetime_type))
        for field in ("created", "updated")
    )


def _is_fence(line: str) -> bool:
    return line.startswith("```")


def _skip_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def _link_exists(t: Transport, url: str) -> bool:
    path_part = url.split("#")[0]
    if path_part == "":
        return True
    candidates = [path_part]
    if not Path(path_part).suffix:
        candidates.append(path_part + ".md")
    return any(t.exists(candidate) for candidate in candidates)


def _iter_mdlinks(text: str) -> Iterator[re.Match[str]]:
    lines = text.split("\n")
    in_fence = False
    for raw_line in lines:
        stripped = raw_line.strip()
        if _is_fence(stripped):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = _skip_code(raw_line)
        yield from MDLINK_RE.finditer(cleaned)


def validate_field(t: Transport) -> list[Issue]:
    issues: list[Issue] = []
    flat = {o.key: o for o in t.list_objects()}
    page_keys = pages.collect_pages(t)

    if not page_keys:
        issues.append(Issue("error", "", "field contains no pages"))

    for o in t.list_objects(recursive=True):
        if "/" in o.key and o.key.endswith(".md"):
            issues.append(Issue("error", o.key, "page inside a subdirectory"))

    for key in page_keys:
        if not pages.is_page_filename(key):
            issues.append(
                Issue(
                    "error",
                    key,
                    f"filename {key!r} must match {pages.PAGE_FILENAME_RE.pattern}",
                )
            )

    for key in page_keys:
        try:
            text = t.read_object(key).decode("utf-8")
        except UnicodeDecodeError:
            issues.append(Issue("error", key, "not valid UTF-8"))
            continue

        fm, has = frontmatter.parse_frontmatter(text)
        if has and fm is None:
            issues.append(Issue("error", key, "frontmatter YAML failed to parse"))

        info = flat.get(key)
        if info is not None and info.size > 8192:
            issues.append(Issue("warning", key, "page exceeds 8192 bytes"))

        if fm is not None:
            missing = [
                field for field in ("title", "uuid", "created", "updated") if field not in fm
            ]
            if missing:
                issues.append(
                    Issue(
                        "warning",
                        key,
                        f"missing recommended frontmatter field(s): {', '.join(missing)}",
                    )
                )
            for field in ("created", "updated"):
                value = fm.get(field)
                if isinstance(value, (_date_type, _datetime_type)):
                    issues.append(
                        Issue(
                            "error",
                            key,
                            f"frontmatter {field!r} must be a quoted string "
                            f"(unquoted value parsed as {type(value).__name__})",
                        )
                    )

        summary = (fm or {}).get("summary")
        if isinstance(summary, str) and len(summary) > 160:
            issues.append(
                Issue(
                    "warning",
                    key,
                    f"summary too long ({len(summary)} chars, max 160)",
                )
            )

        for m in _iter_mdlinks(text):
            url = m.group(2)
            if _is_external_link(url):
                continue
            if not _link_exists(t, url):
                issues.append(Issue("warning", key, f"broken link: {url}"))

    for key in flat:
        if key.endswith(".sqlite3"):
            if not key.startswith(embed.MODEL_CODE):
                issues.append(
                    Issue(
                        "error",
                        key,
                        f"vector index filename must begin with {embed.MODEL_CODE}",
                    )
                )

    return issues
