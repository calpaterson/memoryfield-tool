import json
import sys
from pathlib import Path
from uuid import uuid6

import click

from . import config, export, fields, frontmatter, index, pages, reindex, search, validate

_SORT_CHOICES = ["path", "title", "created", "updated"]


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
    help="Directory to create the field in (default ~/memoryfields/<name>)",
)
def create(name: str, location: str | None) -> None:
    """Create a new memoryfield with an introductory index page."""
    dest = _resolve_field_location(name, location)
    if dest.exists():
        raise click.ClickException(f"directory already exists: {dest}")

    cfg = config.load_config()
    field = config.add_field(cfg, name, str(dest.resolve()))
    dest.mkdir(parents=True)

    now = config.now_iso()
    index_fm: dict[str, object] = {
        "title": name,
        "uuid": str(uuid6()),
        "created": now,
        "updated": now,
        "summary": "Introduction and getting-started notes for this memoryfield.",
    }
    (dest / "index.md").write_text(
        frontmatter.build_frontmatter(index_fm)
        + f"\n# {name}\n\n"
        + "Welcome to your memoryfield. Pages live next to this file.\n\n"
        + "Read and write pages with the `read` and `write` commands, build the "
        + "vector index with `index`, and search it with `search`.\n",
        encoding="utf-8",
    )

    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    click.echo(f"Created memoryfield {name!r} at {dest}")
    click.echo(f"  {dest / 'index.md'}")


@cli.command()
@click.argument("name")
@click.argument("location")
def connect(name: str, location: str) -> None:
    """Connect an existing directory as a memoryfield."""
    dest = Path(location).expanduser().resolve()
    if not dest.is_dir():
        raise click.ClickException(f"not a directory: {dest}")

    cfg = config.load_config()
    field = config.add_field(cfg, name, str(dest))
    cfg = config.with_field(cfg, field)
    config.save_config(cfg)

    if not pages.collect_pages(dest):
        click.echo(f"warning: {dest} contains no pages (will fail validation)", err=True)
    click.echo(f"Connected memoryfield {name!r} at {dest}")


def _catalog_rows(cfg: config.Config, field_list: list[config.Field]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for field in field_list:
        root = fields.field_root(field)
        for p in pages.collect_pages(root):
            text = p.read_text("utf-8")
            fm, _has = frontmatter.parse_frontmatter(text)
            fm_dict = fm if fm is not None else {}
            rows.append(
                {
                    "field": field.name,
                    "filename": p.name,
                    "title": str(fm_dict.get("title", "")),
                    "summary": str(fm_dict.get("summary", "")),
                    "created": fm_dict.get("created", ""),
                    "updated": fm_dict.get("updated", ""),
                }
            )
    return rows


def _sort_rows(rows: list[dict[str, object]], sort_by: str) -> None:
    if sort_by == "path":
        rows.sort(key=lambda r: (str(r["field"]), str(r["filename"])))
    elif sort_by == "title":
        rows.sort(key=lambda r: str(r["title"]).lower())
    elif sort_by == "created":
        rows.sort(key=lambda r: str(r["created"]), reverse=True)
    elif sort_by == "updated":
        rows.sort(key=lambda r: str(r["updated"]), reverse=True)


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

    rows = _catalog_rows(cfg, field_list)
    _sort_rows(rows, sort_by)

    if as_json:
        click.echo(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        click.echo("No pages found.")
        return

    click.echo(_catalog_markdown(rows, multi_field=len(field_list) > 1))


def _read_file(
    path: Path,
    display_path: str,
    offset: int,
    limit: int,
    show_line_numbers: bool,
    file_label: str | None = None,
) -> list[str] | None:
    try:
        text = path.read_text("utf-8")
    except UnicodeDecodeError:
        click.echo(f"error: {display_path}: cannot read binary file", err=True)
        return None
    except FileNotFoundError:
        click.echo(f"error: {display_path}: file not found", err=True)
        return None
    except IsADirectoryError:
        click.echo(f"error: {display_path}: is a directory, not a file", err=True)
        return None
    except PermissionError:
        click.echo(f"error: {display_path}: permission denied", err=True)
        return None

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
    fields.require_local(field)

    line_numbers = not no_line_numbers
    effective_limit = sys.maxsize if no_limit else limit
    failed = False
    for page in pages:
        try:
            resolved = fields.resolve_page(field, page)
        except click.ClickException as e:
            click.echo(f"error: {page}: {e.message}", err=True)
            failed = True
            continue

        output = _read_file(
            path=resolved,
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
    if not pages.is_page_filename(page):
        raise click.ClickException(
            f"invalid page filename {page!r} (must match {pages.PAGE_FILENAME_RE.pattern})"
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
    fields.require_local(field)
    dest = fields.resolve_page(field, page)

    if dest.exists() and not force and not append:
        raise click.ClickException(
            f"file exists: {page} (use --force to overwrite or --append to append)"
        )

    if dest.exists() and not append:
        old_text = dest.read_text("utf-8", errors="replace")
        old_uuid = frontmatter.get_frontmatter_field(old_text, "uuid")
        new_uuid = frontmatter.get_frontmatter_field(body, "uuid")
        if old_uuid is not None and new_uuid is not None and old_uuid != new_uuid:
            raise click.ClickException(
                f"uuid conflict on {page}: body uuid {new_uuid!r} differs from stored {old_uuid!r}"
            )
        if old_uuid is not None and new_uuid is None:
            body = frontmatter.set_frontmatter_field(body, "uuid", old_uuid)

    mode = "ab" if append else "wb"
    with dest.open(mode) as f:
        f.write(raw if append else body.encode("utf-8"))

    reindex.spawn_background_index(field.name)
    click.echo(f"Wrote {len(raw)} bytes to {field.name}/{page}", err=True)


@cli.command(name="index")
@click.option("--field", "field_name", default=None, help="Limit to a single memoryfield")
def index_cmd(field_name: str | None) -> None:
    """Build or update the vector index for one or more memoryfields."""
    cfg = config.load_config()
    field_list = fields.connected_fields(cfg, field_name)
    for field in field_list:
        try:
            fields.require_local(field)
            root = fields.field_root(field)
            indexed, removed, embed_ok = index.build_index(root)
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
        root = fields.field_root(field)
        issues = validate.validate_field(root)
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
            fields.require_local(field)
            out = Path(output).expanduser() if output else Path(f"./{field.name}.memoryfield.zip")
            result = export.export_field(field, out)
        except click.ClickException as e:
            click.echo(f"error: {e.message}", err=True)
            continue
        click.echo(f"Wrote {field.name} to {result}")


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
