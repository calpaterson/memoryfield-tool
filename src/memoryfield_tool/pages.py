import re
from pathlib import Path

PAGE_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")

SPECIAL_FILES = {"index.md", "listing.md"}

_DEBRIS_NAMES = {".DS_Store", "desktop.ini", "Thumbs.db"}


def is_debris(name: str) -> bool:
    return ".sync-conflict-" in name or name.endswith("~") or name in _DEBRIS_NAMES


def is_page_filename(name: str) -> bool:
    return bool(PAGE_FILENAME_RE.match(name))


def collect_pages(root: Path) -> list[Path]:
    pages: list[Path] = []
    for f in root.iterdir():
        if not f.is_file():
            continue
        name = f.name
        if name in SPECIAL_FILES:
            continue
        if is_debris(name):
            continue
        if name.endswith(".md"):
            pages.append(f)
    return sorted(pages)


def collect_all_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for f in root.rglob("*"):
        if not f.is_file():
            continue
        if is_debris(f.name):
            continue
        files.append(f)
    return sorted(files)
