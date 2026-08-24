import json
import sys
import webbrowser
from pathlib import Path
from uuid import uuid6

import click
from waitress import serve as waitress_serve

from . import catalog as catalog_mod
from . import config, export, fields, frontmatter, index, reindex, search, transport, validate, web
from . import pages as pages_mod

_SORT_CHOICES = ["path", "title", "created", "updated"]
_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


@click.group()
def cli() -> None:
    """memoryfield CLI tool."""


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
    """Create a new memoryfield with an introductory index page."""
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
    """Connect an existing directory (or s3://bucket/prefix) as a memoryfield."""
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
    """List all pages across connected memoryfields with frontmatter metadata."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)

    rows: list[dict[str, object]] = []
    for field in field_list:
        t = fields.get_transport(field)
        rows.extend(catalog_mod.catalog_field(t, field_name=field.name))
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
    """Read one or more pages from a memoryfield."""
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
def write(page: str, field_name: str | None, force: bool, append: bool, dry_run: bool) -> None:
    """Write stdin to a page in a memoryfield."""
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
        click.echo(body, nl=False)
        return

    cfg = config.load_config()
    field = fields.read_write_field(cfg, field_name)
    t = fields.get_transport(field)

    try:
        result = pages_mod.write_page(t, page, raw, force=force, append=append)
    except pages_mod.PageWriteError as e:
        raise click.ClickException(str(e)) from None

    reindex.spawn_background_index(field.name)
    click.echo(f"Wrote {result.bytes_written} bytes to {field.name}/{page}", err=True)


@cli.command(name="index")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
def index_cmd(field_name: str | None) -> None:
    """Build or update the vector index for one or more memoryfields."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    for field in field_list:
        try:
            t = fields.get_transport(field)
            loc = fields.index_location(field)
            indexed, removed, embed_ok = index.build_index(t, loc)
        except click.ClickException as e:
            click.echo(f"error: {e.message}", err=True)
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
    """Search pages across connected memoryfields."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)

    results = search.search_all(field_list, query)
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
def validate_cmd(field_name: str | None) -> None:
    """Validate connected memoryfields against the spec."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    any_error = False
    for field in field_list:
        t = fields.get_transport(field)
        issues = validate.validate_field(t)
        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        for issue in issues:
            loc = issue.filename or "(field)"
            click.echo(f"{field.name}/{loc}: {issue.level}: {issue.message}")
        click.echo(f"{field.name}: {len(errors)} errors, {len(warnings)} warnings")
        if errors:
            any_error = True
    if any_error:
        sys.exit(1)


@cli.command(name="export")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
@click.option(
    "--output", "output", default=None, help="Output zip path (default ./<name>.memoryfield.zip)"
)
def export_cmd(field_name: str | None, output: str | None) -> None:
    """Export one or more memoryfields as .memoryfield.zip archives."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    for field in field_list:
        try:
            out = Path(output).expanduser() if output else Path(f"./{field.name}.memoryfield.zip")
            export.export_field(field, out)
        except click.ClickException as e:
            click.echo(f"error: {e.message}", err=True)
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
    """Serve connected memoryfields over HTTP (spec data server + HTML)."""
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
