import re
from dataclasses import dataclass

from . import frontmatter
from .transport import ObjectInfo, Transport

PAGE_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


class PageWriteError(Exception):
    """Base class for write_page validation/save failures."""


class InvalidFilename(PageWriteError):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(
            f"invalid page filename {filename!r} (must match {PAGE_FILENAME_RE.pattern})"
        )


class InvalidUtf8(PageWriteError):
    def __init__(self) -> None:
        super().__init__("body is not valid UTF-8")


class EmptyBody(PageWriteError):
    def __init__(self) -> None:
        super().__init__("refusing to write an empty page")


class FileExists(PageWriteError):
    def __init__(self, filename: str) -> None:
        self.filename = filename
        super().__init__(
            f"file exists: {filename} (use --force to overwrite or --append to append)"
        )


class UuidConflict(PageWriteError):
    def __init__(self, filename: str, old_uuid: object, new_uuid: object) -> None:
        self.filename = filename
        self.old_uuid = old_uuid
        self.new_uuid = new_uuid
        super().__init__(
            f"uuid conflict on {filename}: body uuid {new_uuid!r} differs from stored {old_uuid!r}"
        )


@dataclass(frozen=True)
class WriteResult:
    created: bool
    bytes_written: int


def write_page(
    t: Transport,
    filename: str,
    body: bytes,
    *,
    force: bool = False,
    append: bool = False,
) -> WriteResult:
    """Validate and write a page, applying the v1 CLI write rules."""
    if not is_page_filename(filename):
        raise InvalidFilename(filename)
    try:
        text = body.decode("utf-8")
    except UnicodeDecodeError:
        raise InvalidUtf8() from None
    if not text.strip():
        raise EmptyBody()

    created = not t.exists(filename)

    if t.exists(filename) and not force and not append:
        raise FileExists(filename)

    if t.exists(filename) and not append:
        old_text = t.read_object(filename).decode("utf-8", errors="replace")
        old_uuid = frontmatter.get_frontmatter_field(old_text, "uuid")
        new_uuid = frontmatter.get_frontmatter_field(text, "uuid")
        if old_uuid is not None and new_uuid is not None and old_uuid != new_uuid:
            raise UuidConflict(filename, old_uuid, new_uuid)
        if old_uuid is not None and new_uuid is None:
            text = frontmatter.set_frontmatter_field(text, "uuid", old_uuid)

    data = body if append else text.encode("utf-8")
    t.write_object(filename, data, append=append)
    return WriteResult(created=created, bytes_written=len(data))


def is_page_filename(name: str) -> bool:
    return bool(PAGE_FILENAME_RE.match(name))


def collect_pages(t: Transport) -> list[str]:
    return sorted(key for key in (o.key for o in t.list_objects()) if key.endswith(".md"))


def collect_all_files(t: Transport) -> list[str]:
    return sorted(o.key for o in t.list_objects(recursive=True))


def page_infos(t: Transport) -> list[ObjectInfo]:
    return sorted(
        (o for o in t.list_objects() if o.key.endswith(".md")),
        key=lambda o: o.key,
    )
