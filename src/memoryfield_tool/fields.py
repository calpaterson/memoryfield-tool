from pathlib import Path

import click
import platformdirs

from . import config, frontmatter, transport


def field_root(field: config.Field) -> Path:
    return Path(field.location).expanduser().resolve()


def connected_fields(cfg: config.Config, field_name: str | None) -> list[config.Field]:
    if field_name is not None:
        return [config.get_field(cfg, field_name)]
    return [cfg.fields[name] for name in sorted(cfg.fields)]


def field_title(field: config.Field) -> str:
    """The title frontmatter from the field's index.md, or ''."""
    t = get_transport(field)
    try:
        text = t.read_object("index.md").decode("utf-8", errors="ignore")
    except transport.TransportError:
        return ""
    fm, _ = frontmatter.parse_frontmatter(text)
    if fm is None:
        return ""
    title = fm.get("title")
    return str(title) if title is not None else ""


def read_write_field(cfg: config.Config, field_name: str | None) -> config.Field:
    if field_name is not None:
        return config.get_field(cfg, field_name)
    if len(cfg.fields) == 0:
        raise click.ClickException("no memoryfields connected (run connect)")
    if len(cfg.fields) == 1:
        return next(iter(cfg.fields.values()))
    raise click.ClickException("multiple memoryfields connected — specify --field")


def cache_root() -> Path:
    """This tool's cache directory (XDG_CACHE_HOME-aware via platformdirs)."""
    return Path(platformdirs.user_cache_dir("memoryfield-tool", appauthor=False))


def index_location(field: config.Field) -> Path:
    """Where the field's vector index sqlite file lives."""
    from . import index

    key = field.index_location
    if key == "in-field":
        if field.transport != "local":
            raise click.ClickException(
                f"memoryfield {field.name!r}: s3 fields cannot store the index in-field"
            )
        return field_root(field) / index.index_filename()
    if key is None and field.transport == "local":
        return field_root(field) / index.index_filename()
    if key is None or key == "cache":
        base = cache_root() / "indexes"
    else:
        base = Path(key).expanduser()
    return base / field.name / index.index_filename()


def _region_for(field: config.Field) -> str | None:
    if field.region is not None:
        return field.region
    if field.endpoint_url is not None and "storage.googleapis.com" in field.endpoint_url:
        return "auto"
    return None


def get_transport(field: config.Field) -> transport.Transport:
    """The field's Transport, from the transport name and location."""
    if field.transport == "local":
        return transport.local(Path(field.location))
    if field.transport == "s3":
        bucket, prefix = transport.parse_s3_uri(field.location)
        return transport.S3Transport(
            bucket,
            prefix,
            endpoint_url=field.endpoint_url,
            region=_region_for(field),
            aws_access_key_id=field.aws_access_key_id,
            aws_secret_access_key=field.aws_secret_access_key,
            aws_session_token=field.aws_session_token,
        )
    raise click.ClickException(
        f"memoryfield {field.name!r} uses unknown transport {field.transport!r}"
    )
