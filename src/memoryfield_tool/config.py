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
    endpoint_url: str | None = None
    region: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


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
                endpoint_url=raw.get("endpoint_url"),
                region=raw.get("region"),
                aws_access_key_id=raw.get("aws_access_key_id"),
                aws_secret_access_key=raw.get("aws_secret_access_key"),
                aws_session_token=raw.get("aws_session_token"),
            )
    return Config(fields=fields, path=path)


def save_config(cfg: Config) -> None:
    cfg.path.parent.mkdir(parents=True, exist_ok=True)
    memoryfields: dict[str, object] = {}
    for name, field in cfg.fields.items():
        entry: dict[str, object] = {
            "transport": field.transport,
            "location": field.location,
        }
        if field.endpoint_url is not None:
            entry["endpoint_url"] = field.endpoint_url
        if field.region is not None:
            entry["region"] = field.region
        if field.aws_access_key_id is not None:
            entry["aws_access_key_id"] = field.aws_access_key_id
        if field.aws_secret_access_key is not None:
            entry["aws_secret_access_key"] = field.aws_secret_access_key
        if field.aws_session_token is not None:
            entry["aws_session_token"] = field.aws_session_token
        memoryfields[name] = entry
    payload: dict[str, object] = {"memoryfields": memoryfields}

    tmp = cfg.path.with_name(cfg.path.name + ".tmp")
    with tmp.open("wb") as f:
        tomli_w.dump(payload, f)
    os.replace(tmp, cfg.path)


def add_field(
    cfg: Config,
    name: str,
    location: str,
    *,
    transport: str = "local",
    endpoint_url: str | None = None,
    region: str | None = None,
    aws_access_key_id: str | None = None,
    aws_secret_access_key: str | None = None,
    aws_session_token: str | None = None,
) -> Field:
    if not NAME_RE.match(name):
        raise click.ClickException(f"invalid memoryfield name {name!r}")
    if name in cfg.fields:
        raise click.ClickException(f"memoryfield {name!r} already connected")
    if (aws_access_key_id is None) != (aws_secret_access_key is None):
        raise click.ClickException(
            "aws_access_key_id and aws_secret_access_key must be set together"
        )
    if aws_session_token is not None and aws_access_key_id is None:
        raise click.ClickException(
            "aws_session_token requires aws_access_key_id and aws_secret_access_key"
        )
    return Field(
        name=name,
        transport=transport,
        location=location,
        endpoint_url=endpoint_url,
        region=region,
        aws_access_key_id=aws_access_key_id,
        aws_secret_access_key=aws_secret_access_key,
        aws_session_token=aws_session_token,
    )


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
