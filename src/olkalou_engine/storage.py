from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .config import Settings
from .models import utc_now_iso


class ObjectStore(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str, cache_control: str) -> str: ...
    def put_json(self, key: str, payload: dict[str, Any], cache_control: str) -> str: ...
    def get_json(self, key: str) -> dict[str, Any] | None: ...


@dataclass
class LocalObjectStore:
    root: Path
    public_base_url: str

    def _path(self, key: str) -> Path:
        return self.root / key.lstrip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str, cache_control: str) -> str:
        del content_type, cache_control
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, path)
        finally:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
        return f"{self.public_base_url.rstrip('/')}/{key.lstrip('/')}"

    def put_json(self, key: str, payload: dict[str, Any], cache_control: str = "max-age=20") -> str:
        data = json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8")
        return self.put_bytes(key, data, "application/json", cache_control)

    def get_json(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))


class S3ObjectStore:
    def __init__(self, settings: Settings):
        try:
            import boto3
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("Install the s3 extra: pip install -e '.[s3]'") from exc
        if not settings.s3_bucket:
            raise ValueError("S3_BUCKET is required")
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix.strip("/")
        self.public_base_url = (settings.s3_public_base_url or "").rstrip("/")
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
        )

    def _key(self, key: str) -> str:
        return f"{self.prefix}/{key.lstrip('/')}" if self.prefix else key.lstrip("/")

    def put_bytes(self, key: str, data: bytes, content_type: str, cache_control: str) -> str:
        object_key = self._key(key)
        self.client.put_object(
            Bucket=self.bucket,
            Key=object_key,
            Body=data,
            ContentType=content_type,
            CacheControl=cache_control,
        )
        return f"{self.public_base_url}/{object_key}" if self.public_base_url else object_key

    def put_json(self, key: str, payload: dict[str, Any], cache_control: str = "max-age=20") -> str:
        return self.put_bytes(
            key,
            json.dumps(payload, indent=2, ensure_ascii=False).encode("utf-8"),
            "application/json",
            cache_control,
        )

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except self.client.exceptions.NoSuchKey:
            return None
        return json.loads(response["Body"].read())


def build_store(settings: Settings) -> ObjectStore:
    if settings.s3_bucket:
        return S3ObjectStore(settings)
    return LocalObjectStore(settings.path("data/public"), settings.public_base_url)


@dataclass(frozen=True)
class ArchivedForm:
    archive_path: Path
    public_url: str
    sha256: str
    metadata_path: Path


def archive_form(
    *,
    settings: Settings,
    store: ObjectStore,
    stream_key: str,
    version: int,
    body: bytes,
    extension: str,
    source_url: str,
    headers: dict[str, str],
) -> ArchivedForm:
    digest = hashlib.sha256(body).hexdigest()
    extension = extension.lower().lstrip(".") or "bin"
    file_name = f"v{version}_{digest[:12]}.{extension}"
    relative = Path("raw") / stream_key / file_name
    local_path = settings.raw_dir / stream_key / file_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    if not local_path.exists():
        local_path.write_bytes(body)
    meta = {
        "stream_key": stream_key,
        "version": version,
        "source_url": source_url,
        "sha256": digest,
        "content_length": len(body),
        "discovered_at": utc_now_iso(),
        "http_headers": headers,
    }
    meta_path = settings.raw_dir / stream_key / f"v{version}_meta.json"
    meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    content_type = {
        "pdf": "application/pdf",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "png": "image/png",
    }.get(extension, "application/octet-stream")
    public_url = store.put_bytes(str(relative), body, content_type, "public,max-age=31536000,immutable")
    store.put_json(str(relative.with_name(f"v{version}_meta.json")), meta, "public,max-age=31536000,immutable")
    return ArchivedForm(local_path, public_url, digest, meta_path)
