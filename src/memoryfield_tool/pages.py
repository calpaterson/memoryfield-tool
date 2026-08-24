import re
from pathlib import Path

PAGE_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


def is_page_filename(name: str) -> bool:
    return bool(PAGE_FILENAME_RE.match(name))


def collect_pages(root: Path) -> list[Path]:
    pages: list[Path] = []
    for f in root.iterdir():
        if f.is_file() and f.name.endswith(".md"):
            pages.append(f)
    return sorted(pages)


def collect_all_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for f in root.rglob("*"):
        if f.is_file():
            files.append(f)
    return sorted(files)
