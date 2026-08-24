import os
import re
import tomllib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import click
import tomli_w

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


@dataclass(frozen=True)
class Field:
    name: str
    transport: str
    location: str


@dataclass(frozen=True)
class Config:
    fields: dict[str, Field]
    path: Path


def config_path() -> Path:
    env = os.environ.get("MEMORYFIELD_TOOL_CONFIG")
    if env:
        return Path(env)
    return Path("~/.config/memoryfield-tool.toml").expanduser()


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_config() -> Config:
    path = config_path()
    if not path.is_file():
        return Config(fields={}, path=path)
    try:
        data = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise click.ClickException(f"config {path}: invalid TOML: {e}") from None

    fields: dict[str, Field] = {}
    memoryfields = data.get("memoryfields", {})
    if isinstance(memoryfields, dict):
        for name, raw in memoryfields.items():
            if not isinstance(raw, dict):
                continue
            fields[name] = Field(
                name=name,
                transport=str(raw.get("transport", "local")),
                location=str(raw.get("location", "")),
            )
    return Config(fields=fields, path=path)


def save_config(cfg: Config) -> None:
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    memoryfields: dict[str, object] = {}
    for name, field in cfg.fields.items():
        memoryfields[name] = {
            "transport": field.transport,
            "location": field.location,
        }
    payload: dict[str, object] = {"memoryfields": memoryfields}

    tmp = cfg.path.with_name(cfg.path.name + ".tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(payload, f)
    os.replace(tmp, cfg.path)


def add_field(cfg: Config, name: str, location: str) -> Field:
    if not NAME_RE.match(name):
        raise click.ClickException(f"invalid memoryfield name {name!r}")
    if name in cfg.fields:
        raise click.ClickException(f"memoryfield {name!r} already connected")
    return Field(name=name, transport="local", location=location)


def get_field(cfg: Config, name: str) -> Field:
    field = cfg.fields.get(name)
    if field is None:
        raise click.ClickException(f"no memoryfield named {name!r} connected (run connect)")
    return field


def remove_field(cfg: Config, name: str) -> Config:
    fields = dict(cfg.fields)
    fields.pop(name, None)
    return replace(cfg, fields=fields)


def with_field(cfg: Config, field: Field) -> Config:
    fields = dict(cfg.fields)
    fields[field.name] = field
    return replace(cfg, fields=fields)
