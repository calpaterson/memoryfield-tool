from pathlib import Path

import click

from . import config


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


def require_local(field: config.Field) -> None:
    if field.transport != "local":
        raise click.ClickException(
            f"memoryfield {field.name!r} uses transport {field.transport!r}; "
            "only local transports are supported in v1"
        )


def resolve_page(field: config.Field, page_name: str) -> Path:
    root = field_root(field)
    resolved = (root / page_name).resolve()
    if not resolved.is_relative_to(root):
        raise click.ClickException(f"page {page_name!r} escapes the field root")
    return resolved
