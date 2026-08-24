import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import click
from botocore.exceptions import ClientError

_BUCKET_RE = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int
    last_modified: datetime


class TransportError(Exception):
    """Base class for backend failures and misconfiguration."""


class ObjectNotFound(TransportError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"object not found: {key}")


class ContainmentError(TransportError):
    def __init__(self, key: str) -> None:
        self.key = key
        super().__init__(f"object {key!r} escapes the field root")


class Transport(ABC):
    @abstractmethod
    def list_objects(self, *, recursive: bool = False) -> list[ObjectInfo]:
        """All keys under the field root, sorted; never includes the root itself."""

    @abstractmethod
    def read_object(self, key: str) -> bytes:
        """Read an object's bytes. ObjectNotFound when missing, ContainmentError on escape."""

    @abstractmethod
    def write_object(self, key: str, data: bytes, *, append: bool = False) -> None:
        """Write (or append to) an object. ContainmentError on escape."""

    @abstractmethod
    def delete_object(self, key: str) -> None:
        """Delete an object. ObjectNotFound when missing."""

    @abstractmethod
    def stat_object(self, key: str) -> ObjectInfo | None:
        """Metadata for an object, or None when missing (or escaping)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """True when the object exists; False for missing AND escaping keys."""

    @abstractmethod
    def probe(self) -> None:
        """Raise a descriptive TransportError when the backend is unreachable/misconfigured."""


class LocalTransport(Transport):
    def __init__(self, root: Path) -> None:
        self.root = root

    def _checked(self, key: str) -> Path:
        resolved = (self.root / key).resolve()
        if not resolved.is_relative_to(self.root):
            raise ContainmentError(key)
        return resolved

    def list_objects(self, *, recursive: bool = False) -> list[ObjectInfo]:
        if recursive:
            paths = [f for f in self.root.rglob("*") if f.is_file()]
        else:
            paths = [f for f in self.root.iterdir() if f.is_file()]
        out: list[ObjectInfo] = []
        for f in paths:
            st = f.stat()
            out.append(
                ObjectInfo(
                    key=f.relative_to(self.root).as_posix(),
                    size=st.st_size,
                    last_modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
                )
            )
        return sorted(out, key=lambda o: o.key)

    def read_object(self, key: str) -> bytes:
        path = self._checked(key)
        try:
            return path.read_bytes()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    def write_object(self, key: str, data: bytes, *, append: bool = False) -> None:
        path = self._checked(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        mode = "ab" if append else "wb"
        with path.open(mode) as f:
            f.write(data)

    def delete_object(self, key: str) -> None:
        path = self._checked(key)
        try:
            path.unlink()
        except FileNotFoundError:
            raise ObjectNotFound(key) from None

    def stat_object(self, key: str) -> ObjectInfo | None:
        try:
            path = self._checked(key)
        except ContainmentError:
            return None
        try:
            st = path.stat()
        except FileNotFoundError:
            return None
        return ObjectInfo(
            key=key,
            size=st.st_size,
            last_modified=datetime.fromtimestamp(st.st_mtime, tz=UTC),
        )

    def exists(self, key: str) -> bool:
        try:
            path = self._checked(key)
        except ContainmentError:
            return False
        return path.exists()

    def probe(self) -> None:
        if not self.root.is_dir():
            raise TransportError(f"not a directory: {self.root}")


def _is_404(e: ClientError) -> bool:
    status: int = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    return status == 404


class S3Transport(Transport):
    def __init__(
        self,
        bucket: str,
        prefix: str,
        *,
        client: object = None,
        endpoint_url: str | None = None,
        region: str | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self.region = region
        if client is not None:
            self._client: Any = client
        else:
            kwargs: dict[str, str] = {}
            if endpoint_url is not None:
                kwargs["endpoint_url"] = endpoint_url
            if region is not None:
                kwargs["region_name"] = region
            self._client = boto3.client("s3", **kwargs)

    def _full(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def list_objects(self, *, recursive: bool = False) -> list[ObjectInfo]:
        prefix = self._full("")
        objs: list[ObjectInfo] = []
        kwargs: dict[str, object] = {"Bucket": self.bucket, "Prefix": prefix}
        while True:
            resp = self._client.list_objects_v2(**kwargs)
            for item in resp.get("Contents", []):
                full_key = item["Key"]
                if full_key == prefix:
                    continue
                objs.append(
                    ObjectInfo(
                        key=full_key[len(prefix) :],
                        size=item["Size"],
                        last_modified=item["LastModified"],
                    )
                )
            token = resp.get("NextContinuationToken")
            if not token:
                break
            kwargs["ContinuationToken"] = token
        if not recursive:
            objs = [o for o in objs if "/" not in o.key]
        return sorted(objs, key=lambda o: o.key)

    def read_object(self, key: str) -> bytes:
        try:
            resp = self._client.get_object(Bucket=self.bucket, Key=self._full(key))
            return bytes(resp["Body"].read())
        except ClientError as e:
            if _is_404(e):
                raise ObjectNotFound(key) from None
            raise TransportError(f"s3 read {key!r}: {e}") from e

    def write_object(self, key: str, data: bytes, *, append: bool = False) -> None:
        if append:
            try:
                existing = self.read_object(key)
            except ObjectNotFound:
                existing = b""
            data = existing + data
        self._client.put_object(Bucket=self.bucket, Key=self._full(key), Body=data)

    def delete_object(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket, Key=self._full(key))
        except ClientError as e:
            if _is_404(e):
                raise ObjectNotFound(key) from None
            raise TransportError(f"s3 delete {key!r}: {e}") from e

    def stat_object(self, key: str) -> ObjectInfo | None:
        try:
            resp = self._client.head_object(Bucket=self.bucket, Key=self._full(key))
        except ClientError as e:
            if _is_404(e):
                return None
            raise TransportError(f"s3 stat {key!r}: {e}") from e
        return ObjectInfo(
            key=key,
            size=resp["ContentLength"],
            last_modified=resp["LastModified"],
        )

    def exists(self, key: str) -> bool:
        return self.stat_object(key) is not None

    def probe(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
        except ClientError as e:
            error = e.response.get("Error", {})
            code = error.get("Code", "")
            message = error.get("Message", str(e))
            endpoint = self.endpoint_url or "default endpoint"
            raise TransportError(
                f"s3 bucket {self.bucket!r} (endpoint {endpoint}): {code}: {message}"
            ) from e


def parse_s3_uri(location: str) -> tuple[str, str]:
    """Return (bucket, prefix) for an s3://bucket/prefix location."""
    if not location.startswith("s3://"):
        raise click.ClickException(
            f"invalid s3 location {location!r}: expected an s3://bucket/prefix URI"
        )
    rest = location[len("s3://") :]
    bucket, _sep, key = rest.partition("/")
    if not bucket or not _BUCKET_RE.match(bucket):
        raise click.ClickException(
            f"invalid s3 location {location!r}: bucket {bucket!r} is not a valid bucket name"
        )
    return bucket, key.strip("/")


def local(root: Path) -> LocalTransport:
    return LocalTransport(root.expanduser().resolve())
