import json
import os
import shlex
import subprocess
import sys
import tempfile
import webbrowser
from pathlib import Path
from uuid import uuid6

import click
from waitress import serve as waitress_serve

from . import (
    __version__,
    config,
    export,
    fields,
    frontmatter,
    index,
    reindex,
    search,
    transport,
    validate,
    web,
)
from . import catalog as catalog_mod
from . import pages as pages_mod

_SORT_CHOICES = ["path", "title", "created", "updated"]
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


def _jsonable(value: object) -> object:
    if isinstance(value, tuple):
        return list(value)
    return value


def _dump_schema() -> str:
    commands: list[dict[str, object]] = []
    for name in sorted(cli.commands):
        cmd = cli.commands[name]
        summary = (cmd.help or "").splitlines()[0] if cmd.help else ""
        params: list[dict[str, object]] = []
        for p in cmd.params:
            if not isinstance(p, click.Option):
                continue
            entry: dict[str, object] = {
                "name": p.name,
                "opts": p.opts,
                "secondary_opts": p.secondary_opts,
                "required": p.required,
                "default": _jsonable(p.default),
                "type": type(p.type).__name__,
                "help": p.help,
            }
            if isinstance(p.type, click.Choice):
                entry["choices"] = p.type.choices
            params.append(entry)
        commands.append({"name": name, "summary": summary, "help": cmd.help, "params": params})
    return json.dumps(
        {"tool": "memoryfield-tool", "version": __version__, "commands": commands},
        indent=2,
    )


def _schema_callback(ctx: click.Context, param: click.Parameter, value: bool) -> None:
    if value:
        click.echo(_dump_schema())
        raise click.exceptions.Exit(0)


@click.group()
@click.option(
    "--schema",
    is_flag=True,
    is_eager=True,
    expose_value=False,
    help="Print the full command schema as JSON and exit.",
    callback=_schema_callback,
)
def cli() -> None:
    """memoryfield CLI tool."""


def _is_interactive() -> bool:
    """True when stdin is a terminal (edit is a human command)."""
    return sys.stdin.isatty()


def _resolve_field_location(field_name: str, location: str | None) -> Path:
    if location:
        return Path(location).expanduser()
    return Path("~/memoryfields").expanduser() / field_name


@cli.command()
@click.argument("name")
@click.option(
    "--location",
    default=None,
    help="Directory (or s3://bucket/prefix) to create the field in (default ~/memoryfields/<name>)",
)
@click.option("--endpoint-url", default=None, help="S3-compatible endpoint URL (s3 fields)")
@click.option("--aws-access-key-id", default=None, help="AWS access key ID (s3 fields)")
@click.option("--aws-secret-access-key", default=None, help="AWS secret access key (s3 fields)")
@click.option(
    "--aws-session-token", default=None, help="AWS session token (temporary credentials, s3 fields)"
)
def create(
    name: str,
    location: str | None,
    endpoint_url: str | None,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    aws_session_token: str | None,
) -> None:
    """Create a new memoryfield with an introductory index page.

    Examples:

    \b
        memoryfield-tool create notes
        memoryfield-tool create cadentia --location s3://bucket/cadentia
    """
    cfg = config.load_config()

    now = config.now_iso()
    index_fm: dict[str, object] = {
        "title": name,
        "uuid": str(uuid6()),
        "created": now,
        "updated": now,
        "summary": "Introduction and getting-started notes for this memoryfield.",
    }
    index_body = (
        frontmatter.build_frontmatter(index_fm)
        + f"\n# {name}\n\n"
        + "Welcome to your memoryfield. Pages live next to this file.\n\n"
        + "Read and write pages with the `read` and `write` commands, build the "
        + "vector index with `index`, and search it with `search`.\n"
    )

    if location and location.startswith("s3://"):
        transport.parse_s3_uri(location)
        field = config.add_field(
            cfg,
            name,
            location,
            transport="s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )
        t = fields.get_transport(field)
        try:
            t.probe()
        except transport.TransportError as e:
            raise click.ClickException(f"memoryfield {name!r}: {e}") from None
        if t.exists("index.md"):
            raise click.ClickException(
                f"bucket already contains {name} (remove it or pick another name)"
            )
        t.write_object("index.md", index_body.encode("utf-8"))
        cfg = config.with_field(cfg, field)
        config.save_config(cfg)
        click.echo(f"Created memoryfield {name!r} at {location}")
        click.echo(f"  {location}/index.md")
        return

    dest = _resolve_field_location(name, location)
    if dest.exists():
        raise click.ClickException(f"directory already exists: {dest}")

    field = config.add_field(cfg, name, str(dest.resolve()))
    dest.mkdir(parents=True)

    (dest / "index.md").write_text(index_body, encoding="utf-8")

    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    click.echo(f"Created memoryfield {name!r} at {dest}")
    click.echo(f"  {dest / 'index.md'}")


@cli.command()
@click.argument("name")
@click.argument("location")
@click.option("--endpoint-url", default=None, help="S3-compatible endpoint URL (s3 fields)")
@click.option("--region", default=None, help="Region for the S3 endpoint (s3 fields)")
@click.option("--aws-access-key-id", default=None, help="AWS access key ID (s3 fields)")
@click.option("--aws-secret-access-key", default=None, help="AWS secret access key (s3 fields)")
@click.option(
    "--aws-session-token", default=None, help="AWS session token (temporary credentials, s3 fields)"
)
def connect(
    name: str,
    location: str,
    endpoint_url: str | None,
    region: str | None,
    aws_access_key_id: str | None,
    aws_secret_access_key: str | None,
    aws_session_token: str | None,
) -> None:
    """Connect an existing directory (or s3://bucket/prefix) as a memoryfield.

    Examples:

    \b
        memoryfield-tool connect notes ~/memoryfields/notes
        memoryfield-tool connect cadentia s3://bucket/cadentia --endpoint-url https://...
    """
    cfg = config.load_config()
    if location.startswith("s3://"):
        transport.parse_s3_uri(location)
        field = config.add_field(
            cfg,
            name,
            location,
            transport="s3",
            endpoint_url=endpoint_url,
            region=region,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            aws_session_token=aws_session_token,
        )
        t = fields.get_transport(field)
        try:
            t.probe()
        except transport.TransportError as e:
            raise click.ClickException(f"memoryfield {name!r}: {e}") from None
        cfg = config.with_field(cfg, field)
        config.save_config(cfg)

        if not pages_mod.collect_pages(t):
            click.echo(f"warning: {location} contains no pages (will fail validation)", err=True)
        click.echo(f"Connected memoryfield {name!r} at {location}")
        return

    dest = Path(location).expanduser().resolve()
    if not dest.is_dir():
        raise click.ClickException(f"not a directory: {dest}")

    field = config.add_field(cfg, name, str(dest))
    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    if not pages_mod.collect_pages(transport.local(dest)):
        click.echo(f"warning: {dest} contains no pages (will fail validation)", err=True)
    click.echo(f"Connected memoryfield {name!r} at {dest}")


@cli.command(name="disconnect")
@click.argument("name")
def disconnect_cmd(name: str) -> None:
    """Remove a memoryfield from the config (does not delete its data).

    Removes the field's entry from the config file only; the field's pages
    and vector index are left in place. Use this to drop a stale or
    unreachable field.

    Examples:

    \b
        memoryfield-tool disconnect notes
    """
    cfg = config.load_config()
    config.get_field(cfg, name)  # raises if not connected
    cfg = config.remove_field(cfg, name)
    config.save_config(cfg)
    click.echo(f"Disconnected memoryfield {name!r}")


@cli.command(name="fields")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
def fields_cmd(as_json: bool) -> None:
    """List connected memoryfields (name, transport, location, and index.md title).

    Reads each field's index.md for its title frontmatter; a missing or
    unreadable index.md yields an empty title.

    Examples:

    \b
        memoryfield-tool fields
        memoryfield-tool fields --json
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, None)

    rows = [
        {
            "name": f.name,
            "transport": f.transport,
            "location": f.location,
            "title": fields.field_title(f),
        }
        for f in field_list
    ]
    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        click.echo("No memoryfields connected.")
        return

    out = ["| Field | Transport | Location | Title |", "|---|---|---|---|"]
    for row in rows:
        title = str(row["title"] or "—")
        if len(title) > 160:
            title = title[:157] + "..."
        out.append(f"| {row['name']} | {row['transport']} | {row['location']} | {title} |")
    click.echo("\n".join(out))


@cli.command(name="path")
@click.argument("page", required=False)
@click.option("--field", "field_name", default=None, help="Memoryfield to resolve")
def path_cmd(page: str | None, field_name: str | None) -> None:
    """Print a field's root path, or the full path to a page.

    For local fields the root is the resolved directory path; for s3 fields
    it is the s3:// URI. With PAGE, prints that page's path (the page need
    not exist). Useful for working on a field with plain file tools.

    Examples:

    \b
        memoryfield-tool path
        memoryfield-tool path --field notes alpha.md
    """
    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    if page is not None:
        if not pages_mod.is_page_filename(page):
            raise click.ClickException(
                f"invalid page filename {page!r} (must match {pages_mod.PAGE_FILENAME_RE.pattern})"
            )
        if field.transport == "local":
            click.echo(str(fields.field_root(field) / page))
        else:
            click.echo(f"{field.location.rstrip('/')}/{page}")
    elif field.transport == "local":
        click.echo(str(fields.field_root(field)))
    else:
        click.echo(field.location)


def _catalog_markdown(rows: list[dict[str, object]], multi_field: bool) -> str:
    if multi_field:
        out = ["| Field | Page | Summary |", "|-------|------|---------|"]
    else:
        out = ["| Page | Summary |", "|------|---------|"]
    for r in rows:
        summary = str(r["summary"] or "—")
        if len(summary) > 160:
            summary = summary[:157] + "..."
        if multi_field:
            out.append(f"| {r['field']} | {r['filename']} | {summary} |")
        else:
            out.append(f"| {r['filename']} | {summary} |")
    return "\n".join(out)


@cli.command()
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(_SORT_CHOICES),
    default="path",
    help="Sort order (default: path)",
)
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
def catalog(field_name: str | None, sort_by: str, as_json: bool) -> None:
    """List all pages across connected memoryfields with frontmatter metadata.

    Examples:

    \b
        memoryfield-tool catalog --sort updated
        memoryfield-tool catalog --json
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)

    rows: list[dict[str, object]] = []
    for field in field_list:
        try:
            t = fields.get_transport(field)
            rows.extend(catalog_mod.catalog_field(t, field_name=field.name))
        except (transport.TransportError, click.ClickException) as e:
            click.echo(f"error: memoryfield {field.name}: {e}", err=True)
    rows = catalog_mod.catalog_sort(rows, sort_by)

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        click.echo("No pages found.")
        return

    click.echo(catalog_mod.catalog_markdown(rows, show_field=len(field_list) > 1))


def _read_file(
    text: str,
    display_path: str,
    offset: int,
    limit: int,
    show_line_numbers: bool,
    file_label: str | None = None,
) -> list[str] | None:
    lines = text.splitlines()
    selected = lines[offset - 1 : offset - 1 + limit]

    output: list[str] = []
    if file_label is not None:
        output.append(f"### FILE: {file_label}")
    for i, line in enumerate(selected):
        if show_line_numbers:
            output.append(f"{offset + i}: {line}")
        else:
            output.append(line)
    return output


@cli.command(name="read")
@click.argument("pages", nargs=-1, required=True)
@click.option("--field", "field_name", default=None, help="Memoryfield to read from")
@click.option(
    "--offset", type=click.IntRange(min=1), default=1, help="Start reading at this line (1-indexed)"
)
@click.option("--limit", type=int, default=2000, help="Maximum lines to read")
@click.option("--no-limit", is_flag=True, help="Read the entire file (ignore --limit)")
@click.option("--no-line-numbers", is_flag=True, help="Omit line number prefixes")
def read_cmd(
    pages: tuple[str, ...],
    field_name: str | None,
    offset: int,
    limit: int,
    no_limit: bool,
    no_line_numbers: bool,
) -> None:
    """Read one or more pages from a memoryfield.

    Examples:

    \b
        memoryfield-tool read alpha.md --offset 5 --limit 20
    """
    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)

    line_numbers = not no_line_numbers
    effective_limit = sys.maxsize if no_limit else limit
    failed = False
    for page in pages:
        if not pages_mod.is_page_filename(page):
            click.echo(f"error: {page}: page name is invalid or escapes the field root", err=True)
            failed = True
            continue
        try:
            raw = t.read_object(page)
            text = raw.decode("utf-8")
        except transport.ObjectNotFound:
            click.echo(f"error: {page}: file not found", err=True)
            failed = True
            continue
        except UnicodeDecodeError:
            click.echo(f"error: {page}: cannot read binary file", err=True)
            failed = True
            continue
        except PermissionError:
            click.echo(f"error: {page}: permission denied", err=True)
            failed = True
            continue

        output = _read_file(
            text=text,
            display_path=page,
            offset=offset,
            limit=effective_limit,
            show_line_numbers=line_numbers,
            file_label=page if len(pages) > 1 else None,
        )
        if output is None:
            failed = True
            continue
        for line in output:
            click.echo(line)

    if failed:
        sys.exit(1)


@cli.command()
@click.argument("page")
@click.option("--field", "field_name", default=None, help="Memoryfield to write to")
@click.option("--force", is_flag=True, help="Overwrite existing file")
@click.option("--append", is_flag=True, help="Append to existing file instead of overwriting")
@click.option("--dry-run", is_flag=True, help="Print content to stdout instead of writing")
@click.option(
    "--title", default=None, help="Frontmatter title (default: stored title, else filename stem)"
)
@click.option("--summary", default=None, help="Frontmatter summary (only set when provided)")
def write(
    page: str,
    field_name: str | None,
    force: bool,
    append: bool,
    dry_run: bool,
    title: str | None,
    summary: str | None,
) -> None:
    """Write stdin to a page in a memoryfield.

    Missing frontmatter (uuid, created, updated, title) is filled in; a
    summary is never inferred (pass --summary to set one). On overwrite the
    stored uuid/created/title are preserved and updated is always refreshed
    to the current time; pass --title to override the title.

    Examples:

    \b
        echo '# New page' | memoryfield-tool write new-page.md
        echo '# New page' | memoryfield-tool write new-page.md --title 'New Page' --summary 'About'
        memoryfield-tool write --dry-run new-page.md < draft.md
    """
    if not pages_mod.is_page_filename(page):
        raise click.ClickException(
            f"invalid page filename {page!r} (must match {pages_mod.PAGE_FILENAME_RE.pattern})"
        )
    raw = sys.stdin.buffer.read()
    try:
        body = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise click.ClickException("body is not valid UTF-8") from None
    if not body.strip():
        raise click.ClickException("refusing to write an empty page")

    if dry_run:
        now = config.now_iso()
        filled = frontmatter.fill_frontmatter(
            body,
            title=title,
            summary=summary,
            title_fallback=Path(page).stem,
            uuid=str(uuid6()),
            created=now,
            updated=now,
        )
        click.echo(filled, nl=False)
        return

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)

    try:
        result = pages_mod.write_page(
            t,
            page,
            raw,
            force=force,
            append=append,
            title=title,
            summary=summary,
            title_fallback=Path(page).stem,
        )
    except pages_mod.PageWriteError as e:
        raise click.ClickException(str(e)) from None

    reindex.spawn_background_index(field.name)
    click.echo(f"Wrote {result.bytes_written} bytes to {field.name}/{page}", err=True)


@cli.command()
@click.argument("title")
@click.option("--field", "field_name", default=None, help="Memoryfield to create the page in")
@click.option("--name", "page_name", default=None, help="Page filename (default: slugified title)")
@click.option("--summary", default=None, help="Frontmatter summary (only set when provided)")
@click.option(
    "--dry-run", is_flag=True, help="Print the would-be page to stdout instead of creating"
)
def new(
    title: str, field_name: str | None, page_name: str | None, summary: str | None, dry_run: bool
) -> None:
    """Create a new page with generated frontmatter.

    The filename is derived from the title (lowercase, hyphenated) unless
    --name is given. uuid, created and updated are generated; title comes
    from the argument; summary is only set when --summary is provided.
    The body is read from stdin when piped, otherwise a bare
    "# <title>" skeleton is used.

    Examples:

    \b
        echo '# Notes' | memoryfield-tool new 'Carbon Fibre Woks' --summary 'Thermal properties'
        memoryfield-tool new 'Carbon Fibre Woks' --name carbon-fibre.md
        memoryfield-tool new 'Draft' --dry-run
    """
    slug = page_name or pages_mod.slugify_title(title)
    if not slug.endswith(".md"):
        slug += ".md"
    if not pages_mod.is_page_filename(slug):
        raise click.ClickException(
            f"cannot derive a valid page filename from title {title!r} (pass --name)"
        )

    raw = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""
    if not raw.strip():
        raw = f"# {title}\n\n".encode()

    stem = slug.removesuffix(".md")
    if dry_run:
        try:
            body = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise click.ClickException("body is not valid UTF-8") from None
        now = config.now_iso()
        filled = frontmatter.fill_frontmatter(
            body,
            title=title,
            summary=summary,
            title_fallback=stem,
            uuid=str(uuid6()),
            created=now,
            updated=now,
        )
        click.echo(filled, nl=False)
        return

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)
    try:
        result = pages_mod.write_page(
            t, slug, raw, title=title, summary=summary, title_fallback=stem
        )
    except pages_mod.FileExists:
        raise click.ClickException(
            f"page already exists: {slug} (use write --force to overwrite)"
        ) from None
    except pages_mod.PageWriteError as e:
        raise click.ClickException(str(e)) from None

    reindex.spawn_background_index(field.name)
    click.echo(f"Created {field.name}/{slug}")
    if result.uuid:
        click.echo(f"  uuid: {result.uuid}")


@cli.command()
@click.argument("page")
@click.option("--field", "field_name", default=None, help="Memoryfield to edit")
@click.option(
    "--editor",
    default=None,
    help="Editor command (default: $VISUAL, $EDITOR, then vi). May include arguments.",
)
def edit(page: str, field_name: str | None, editor: str | None) -> None:
    """Open a page in $EDITOR and write it back to the field on save.

    The page is copied to a temporary file, opened in the editor
    ($VISUAL, then $EDITOR, then vi; or --editor), and written back
    through the same validation path as `write` (UTF-8, non-empty,
    uuid preserved) when the editor exits successfully. Works
    identically for local and s3 fields. The editor must block until
    you save and quit (e.g. 'code -w', not bare 'code').

    Examples:

    \b
        memoryfield-tool edit alpha.md
        memoryfield-tool edit --field notes alpha.md
        EDITOR='code -w' memoryfield-tool edit alpha.md
    """
    if not pages_mod.is_page_filename(page):
        raise click.ClickException(
            f"invalid page filename {page!r} (must match {pages_mod.PAGE_FILENAME_RE.pattern})"
        )
    if editor is None and not _is_interactive():
        configured = os.environ.get("VISUAL") or os.environ.get("EDITOR")
        if not configured:
            raise click.ClickException(
                "edit is interactive and needs a terminal, and no editor "
                "is configured (set $EDITOR/$VISUAL or pass --editor)"
            )

    editor_cmd = editor or os.environ.get("VISUAL") or os.environ.get("EDITOR") or "vi"
    try:
        editor_parts = shlex.split(editor_cmd)
    except ValueError as e:
        raise click.ClickException(f"invalid editor command {editor_cmd!r}: {e}") from None
    if not editor_parts:
        raise click.ClickException(f"empty editor command {editor_cmd!r}")

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)
    try:
        raw = t.read_object(page)
    except transport.ObjectNotFound:
        raise click.ClickException(f"page not found: {page} (use 'new' to create it)") from None
    try:
        raw.decode("utf-8")
    except UnicodeDecodeError:
        raise click.ClickException(f"cannot edit {page}: not valid UTF-8") from None

    fd, tmp_path = tempfile.mkstemp(prefix="memoryfield-edit-", suffix=".md")
    keep_temp = False
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(raw)
        proc = subprocess.run([*editor_parts, tmp_path], check=False)
        if proc.returncode != 0:
            keep_temp = True
            raise click.ClickException(
                f"editor exited with status {proc.returncode}; no changes written "
                f"(your edits are at {tmp_path})"
            )
        try:
            edited = Path(tmp_path).read_bytes()
        except OSError:
            keep_temp = True
            raise click.ClickException(f"editor did not leave a file at {tmp_path}") from None
        if edited == raw:
            click.echo(f"no changes to {field.name}/{page}", err=True)
            return
        try:
            result = pages_mod.write_page(
                t, page, edited, force=True, title_fallback=Path(page).stem
            )
        except pages_mod.PageWriteError as e:
            keep_temp = True
            raise click.ClickException(f"{e} (your edits are at {tmp_path})") from None
        reindex.spawn_background_index(field.name)
        click.echo(f"Wrote {result.bytes_written} bytes to {field.name}/{page}", err=True)
    finally:
        if not keep_temp:
            Path(tmp_path).unlink(missing_ok=True)


@cli.command(name="delete")
@click.argument("page")
@click.option("--field", "field_name", default=None, help="Memoryfield to delete from")
def delete_cmd(page: str, field_name: str | None) -> None:
    """Delete a page from a memoryfield.

    Removes the page file (local or s3) and its row from the vector index,
    then spawns a background reindex. Refuses to delete index.md.

    Examples:

    \b
        memoryfield-tool delete alpha.md
        memoryfield-tool delete --field notes alpha.md
    """
    if not pages_mod.is_page_filename(page):
        raise click.ClickException(
            f"invalid page filename {page!r} (must match {pages_mod.PAGE_FILENAME_RE.pattern})"
        )
    if page == "index.md":
        raise click.ClickException("refusing to delete index.md (it introduces the memoryfield)")

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)
    try:
        t.delete_object(page)
    except transport.ObjectNotFound:
        raise click.ClickException(f"page not found: {page}") from None

    index.delete_page(fields.index_location(field), page)
    reindex.spawn_background_index(field.name)
    click.echo(f"Deleted {field.name}/{page}")


@cli.command(name="rename")
@click.argument("old")
@click.argument("new")
@click.option("--field", "field_name", default=None, help="Memoryfield to rename in")
def rename_cmd(old: str, new: str, field_name: str | None) -> None:
    """Rename a page within a memoryfield.

    Moves the page (local: rewrite + delete; s3: copy + delete), preserving
    frontmatter (uuid, created, title, summary) and refreshing updated.
    Drops the old page's vector-index row and spawns a background reindex.

    Examples:

    \b
        memoryfield-tool rename alpha.md beta.md
        memoryfield-tool rename --field notes alpha.md beta.md
    """
    if not pages_mod.is_page_filename(old):
        raise click.ClickException(
            f"invalid source filename {old!r} (must match {pages_mod.PAGE_FILENAME_RE.pattern})"
        )
    if not pages_mod.is_page_filename(new):
        raise click.ClickException(
            f"invalid destination filename {new!r} "
            f"(must match {pages_mod.PAGE_FILENAME_RE.pattern})"
        )
    if old == new:
        raise click.ClickException("source and destination are the same page")
    if old == "index.md":
        raise click.ClickException("refusing to rename index.md (it introduces the memoryfield)")

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)

    try:
        raw = t.read_object(old)
    except transport.ObjectNotFound:
        raise click.ClickException(f"page not found: {old}") from None
    if t.exists(new):
        raise click.ClickException(f"page already exists: {new}")

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise click.ClickException(f"cannot rename {old}: not valid UTF-8") from None
    fm, _has = frontmatter.parse_frontmatter(text)
    if fm is not None:
        raw = frontmatter.set_frontmatter_field(text, "updated", config.now_iso()).encode("utf-8")

    try:
        pages_mod.write_page(t, new, raw, force=True)
    except pages_mod.PageWriteError as e:
        raise click.ClickException(str(e)) from None
    t.delete_object(old)

    index.delete_page(fields.index_location(field), old)
    reindex.spawn_background_index(field.name)
    click.echo(f"Renamed {field.name}/{old} -> {field.name}/{new}")


@cli.command(name="index")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
def index_cmd(field_name: str | None) -> None:
    """Build or update the vector index for one or more memoryfields.

    Examples:

    \b
        memoryfield-tool index --field notes
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    for field in field_list:
        try:
            t = fields.get_transport(field)
            t.probe()
            loc = fields.index_location(field)
            indexed, removed, embed_ok = index.build_index(t, loc)
        except (click.ClickException, transport.TransportError) as e:
            click.echo(f"error: memoryfield {field.name}: {e}", err=True)
            continue
        if not embed_ok:
            click.echo(f"{field.name}: embedding unavailable (is ollama running?)")
        elif indexed or removed:
            parts = []
            if indexed:
                parts.append(f"indexed {indexed} files")
            if removed:
                parts.append(f"removed {removed} stale entries")
            click.echo(f"{field.name}: {', '.join(parts)}")
        else:
            click.echo(f"{field.name}: all files up to date")


def _format_result(result: search.SearchResult) -> str:
    line = f"{result.filename}: {result.summary}" if result.summary else result.filename
    if result.distance is not None:
        line = f"{line} (distance {result.distance:.3f})"
    return line


@cli.command(name="search")
@click.argument("query")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
@click.option("--json", "as_json", is_flag=True, help="Output as JSON array")
def search_cmd(query: str, field_name: str | None, as_json: bool) -> None:
    """Search pages across connected memoryfields.

    Examples:

    \b
        memoryfield-tool search 'carbon fibre'
        memoryfield-tool search --json 'carbon fibre'
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)

    results, errors = search.search_all(field_list, query)
    for name, msg in errors:
        click.echo(f"error: memoryfield {name}: {msg}", err=True)
    if as_json:
        payload = [
            {
                "field": fname,
                "filename": r.filename,
                "summary": r.summary,
                "distance": r.distance,
            }
            for fname, r in results
        ]
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    if not results:
        click.echo("No matching results found.")
        return
    if len(field_list) == 1:
        for _fname, r in results:
            click.echo(_format_result(r))
    else:
        for fname, r in results:
            line = f"{fname}/{_format_result(r)}"
            click.echo(line)


@cli.command(name="validate")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
@click.option(
    "--fix",
    "fix",
    is_flag=True,
    help="Rewrite pages with unquoted created/updated datetimes",
)
def validate_cmd(field_name: str | None, fix: bool) -> None:
    """Validate connected memoryfields against the spec.

    Examples:

    \b
        memoryfield-tool validate --field notes
        memoryfield-tool validate --fix --field notes
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    any_error = False
    for field in field_list:
        try:
            t = fields.get_transport(field)
            if fix:
                fixed = 0
                for key in sorted(pages_mod.collect_pages(t)):
                    try:
                        raw = t.read_object(key)
                    except transport.ObjectNotFound:
                        continue
                    text = raw.decode("utf-8", errors="replace")
                    fm, _ = frontmatter.parse_frontmatter(text)
                    if fm is None or not validate.has_unquoted_datetime(fm):
                        continue
                    try:
                        pages_mod.write_page(t, key, raw, force=True)
                    except pages_mod.PageWriteError as e:
                        click.echo(f"{field.name}/{key}: fix failed: {e}", err=True)
                        continue
                    fixed += 1
                if fixed:
                    click.echo(f"{field.name}: fixed {fixed} page(s)", err=True)
            issues = validate.validate_field(t)
            errors = [i for i in issues if i.level == "error"]
            warnings = [i for i in issues if i.level == "warning"]
            for issue in issues:
                loc = issue.filename or "(field)"
                click.echo(f"{field.name}/{loc}: {issue.level}: {issue.message}")
            click.echo(f"{field.name}: {len(errors)} errors, {len(warnings)} warnings")
            if errors:
                any_error = True
        except (transport.TransportError, click.ClickException) as e:
            click.echo(f"error: memoryfield {field.name}: {e}", err=True)
    if any_error:
        sys.exit(1)


@cli.command(name="export")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
@click.option(
    "--output", "output", default=None, help="Output zip path (default ./<name>.memoryfield.zip)"
)
def export_cmd(field_name: str | None, output: str | None) -> None:
    """Export one or more memoryfields as .memoryfield.zip archives.

    Examples:

    \b
        memoryfield-tool export --field notes --output /tmp/notes.memoryfield.zip
    """
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    for field in field_list:
        try:
            out = Path(output).expanduser() if output else Path(f"./{field.name}.memoryfield.zip")
            export.export_field(field, out)
        except (click.ClickException, transport.TransportError) as e:
            click.echo(f"error: memoryfield {field.name}: {e}", err=True)
            continue
        click.echo(f"Wrote {field.name} to {out}", err=True)


@cli.command()
@click.option("--port", default=6211, type=int, help="Port to bind to (default 6211)")
@click.option("--host", default="127.0.0.1", help="Host to bind to (default 127.0.0.1)")
@click.option(
    "--allow-writes",
    is_flag=True,
    help="Enable PUT/DELETE (loopback hosts only; no auth is implemented)",
)
@click.option("--open", "open_browser", is_flag=True, help="Open the landing page in a browser")
def serve(port: int, host: str, allow_writes: bool, open_browser: bool) -> None:
    """Serve connected memoryfields over HTTP (spec data server + HTML).

    Examples:

    \b
        memoryfield-tool serve --port 7000 --open
    """
    if allow_writes and host not in _LOOPBACK_HOSTS:
        raise click.ClickException(
            f"refusing to enable --allow-writes on non-loopback host {host!r} "
            "(no auth is implemented)"
        )
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, None)
    if not field_list:
        raise click.ClickException("no memoryfields connected (run connect)")
    for field in field_list:
        try:
            fields.get_transport(field).probe()
        except transport.TransportError as e:
            raise click.ClickException(f"memoryfield {field.name!r}: {e}") from None

    app = web.create_app(cfg, allow_writes=allow_writes)
    click.echo(f"Serving {len(field_list)} memoryfield(s) at http://{host}:{port}", err=True)
    if open_browser:
        webbrowser.open(f"http://{host}:{port}")
    waitress_serve(app, host=host, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
