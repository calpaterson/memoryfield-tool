import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from . import embed, frontmatter, pages

_URI_SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
MDLINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


@dataclass(frozen=True)
class Issue:
    level: str
    filename: str
    message: str


def _is_external_link(url: str) -> bool:
    return bool(_URI_SCHEME_RE.match(url)) or url.startswith("//") or url.startswith("#")


def _is_fence(line: str) -> bool:
    return line.startswith("```")


def _skip_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def _resolve_link(url: str, page: Path, root: Path) -> Path | None:
    path_part = url.split("#")[0]
    if path_part == "":
        return None
    candidates = [root / path_part, page.parent / path_part]
    if not Path(path_part).suffix:
        candidates.extend([root / (path_part + ".md"), page.parent / (path_part + ".md")])
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


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


def validate_field(root: Path) -> list[Issue]:
    issues: list[Issue] = []
    page_files = pages.collect_pages(root)

    if not page_files:
        issues.append(Issue("error", "", "field contains no pages"))

    for f in root.rglob("*.md"):
        if f.is_file() and f.parent != root and not pages.is_debris(f.name):
            issues.append(Issue("error", str(f.relative_to(root)), "page inside a subdirectory"))

    for f in page_files:
        if not pages.is_page_filename(f.name):
            issues.append(
                Issue(
                    "error",
                    f.name,
                    f"filename {f.name!r} must match {pages.PAGE_FILENAME_RE.pattern}",
                )
            )

    for f in page_files:
        try:
            text = f.read_text("utf-8")
        except UnicodeDecodeError:
            issues.append(Issue("error", f.name, "not valid UTF-8"))
            continue

        fm, has = frontmatter.parse_frontmatter(text)
        if has and fm is None:
            issues.append(Issue("error", f.name, "frontmatter YAML failed to parse"))

        if f.stat().st_size > 8192:
            issues.append(Issue("warning", f.name, "page exceeds 8192 bytes"))

        if fm is not None:
            missing = [
                field for field in ("title", "uuid", "created", "updated") if field not in fm
            ]
            if missing:
                issues.append(
                    Issue(
                        "warning",
                        f.name,
                        f"missing recommended frontmatter field(s): {', '.join(missing)}",
                    )
                )

        summary = (fm or {}).get("summary")
        if isinstance(summary, str) and len(summary) > 160:
            issues.append(
                Issue(
                    "warning",
                    f.name,
                    f"summary too long ({len(summary)} chars, max 160)",
                )
            )

        for m in _iter_mdlinks(text):
            url = m.group(2)
            if _is_external_link(url):
                continue
            if _resolve_link(url, f, root) is None:
                issues.append(Issue("warning", f.name, f"broken link: {url}"))

    for f in root.iterdir():
        if f.is_file() and f.suffix == ".sqlite3":
            if not f.name.startswith(embed.MODEL_CODE):
                issues.append(
                    Issue(
                        "error",
                        f.name,
                        f"vector index filename must begin with {embed.MODEL_CODE}",
                    )
                )

    return issues
