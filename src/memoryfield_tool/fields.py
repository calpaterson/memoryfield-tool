import os
from pathlib import Path

import click

from . import config, transport


def field_root(field: config.Field) -> Path:
    return Path(field.location).expanduser().resolve()


def connected_fields(cfg: config.Config, field_name: str | None) -> list[config.Field]:
    if field_name is not None:
        return [config.get_field(cfg, field_name)]
    return [cfg.fields[name] for name in sorted(cfg.fields)]


def read_write_field(cfg: config.Config, field_name: str | None) -> config.Field:
    if field_name is not None:
        return config.get_field(cfg, field_name)
    if len(cfg.fields) == 0:
        raise click.ClickException("no memoryfields connected (run connect)")
    if len(cfg.fields) == 1:
        return next(iter(cfg.fields.values()))
    raise click.ClickException("multiple memoryfields connected — specify --field")


def index_location(field: config.Field) -> Path:
    """Where the vector index sqlite file lives: in-field for local, cache for s3."""
    if field.transport == "local":
        from . import index

        return field_root(field) / index.index_filename()
    cache = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return cache / "memoryfield-tool" / "indexes" / f"{field.name}.sqlite3"


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
        )
    raise click.ClickException(
        f"memoryfield {field.name!r} uses unknown transport {field.transport!r}"
    )
