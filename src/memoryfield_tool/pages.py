import re
import unicodedata
from dataclasses import dataclass

from . import config, frontmatter
from .transport import ObjectInfo, Transport
from .uuid_compat import uuid6

PAGE_FILENAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\.md$")


def slugify_title(title: str) -> str:
    """Derive a spec-valid page-name stem from a title.

    NFKD-normalizes (dropping combining marks, so 'ä' -> 'a'), lowercases,
    collapses runs of non [a-z0-9] to '-', strips leading/trailing '-'.
    Returns '' when nothing usable remains.
    """
    nfkd = unicodedata.normalize("NFKD", title)
    ascii_ish = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", ascii_ish.lower()).strip("-")


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
    uuid: str | None = None


def write_page(
    t: Transport,
    filename: str,
    body: bytes,
    *,
    force: bool = False,
    append: bool = False,
    title: str | None = None,
    summary: str | None = None,
    title_fallback: str | None = None,
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

    old_text: str | None = None
    stored_fm: dict[str, object] = {}
    if t.exists(filename):
        old_text = t.read_object(filename).decode("utf-8", errors="replace")
        stored, _has = frontmatter.parse_frontmatter(old_text)
        if stored is None:
            stored = {}
        stored_fm = stored

    if t.exists(filename) and not force and not append:
        assert old_text is not None
        title = str(stored_fm.get("title") or filename.removesuffix(".md"))
        if frontmatter.page_body(old_text) != f"# {title}\n\n":
            raise FileExists(filename)

    if title_fallback is None:
        title_fallback = filename.removesuffix(".md")

    if append:
        if created:
            now = config.now_iso()
            fresh_uuid = str(uuid6())
            filled = frontmatter.fill_frontmatter(
                text,
                title=title,
                summary=summary,
                title_fallback=title_fallback,
                uuid=fresh_uuid,
                created=now,
                updated=now,
            )
            data = filled.encode("utf-8")
            t.write_object(filename, data)
            return WriteResult(created=True, bytes_written=len(data), uuid=fresh_uuid)

        existing_text = t.read_object(filename).decode("utf-8", errors="replace")
        stored, _has = frontmatter.parse_frontmatter(existing_text)
        if stored is not None:
            now = config.now_iso()
            filled = frontmatter.fill_frontmatter(
                existing_text,
                title=title,
                summary=summary,
                title_fallback=title_fallback,
                preserve=stored,
                uuid=str(uuid6()),
                created=now,
                updated=now,
                refresh_updated=True,
            )
            data = filled.encode("utf-8") + body
            t.write_object(filename, data)
            preserved_uuid = frontmatter.get_frontmatter_field(filled, "uuid")
            return WriteResult(
                created=False,
                bytes_written=len(data),
                uuid=preserved_uuid if isinstance(preserved_uuid, str) else None,
            )

        t.write_object(filename, body, append=True)
        return WriteResult(created=False, bytes_written=len(body))

    now = config.now_iso()
    filled = frontmatter.fill_frontmatter(
        text,
        title=title,
        summary=summary,
        title_fallback=title_fallback,
        preserve=stored_fm,
        uuid=str(uuid6()),
        created=now,
        updated=now,
        refresh_updated=not created,
    )

    new_uuid = frontmatter.get_frontmatter_field(filled, "uuid")
    stored_uuid = (
        frontmatter.get_frontmatter_field(old_text, "uuid") if old_text is not None else None
    )
    if new_uuid is not None and stored_uuid is not None and new_uuid != stored_uuid:
        raise UuidConflict(filename, stored_uuid, new_uuid)

    data = filled.encode("utf-8")
    t.write_object(filename, data)
    return WriteResult(
        created=created,
        bytes_written=len(data),
        uuid=new_uuid if isinstance(new_uuid, str) else None,
    )


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
