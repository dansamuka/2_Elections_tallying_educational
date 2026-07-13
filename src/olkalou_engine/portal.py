from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import PortalForm

FORM_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
STREAM_CODE_RE = re.compile(r"(?P<full>\d{9,14})(?P<stream>\d{2})\b")
SHORT_STREAM_RE = re.compile(r"\b(?P<station>\d{3,8})[-/ ]?(?P<stream>0?[1-9]\d?)\b")


@dataclass
class FetchResult:
    status_code: int
    body: bytes | None
    headers: dict[str, str]
    url: str


class PortalClient:
    def __init__(
        self,
        index_url: str,
        constituency: str,
        user_agent: str,
        timeout: float = 30,
        constituency_code: str = "091",
    ):
        self.index_url = index_url
        self.constituency = constituency.upper().strip()
        self.constituency_code = str(constituency_code).zfill(3)
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": user_agent, "Accept": "text/html,application/xhtml+xml"},
        )

    def close(self) -> None:
        self.client.close()

    def conditional_get(
        self, url: str, etag: str | None = None, last_modified: str | None = None
    ) -> FetchResult:
        headers: dict[str, str] = {}
        if etag:
            headers["If-None-Match"] = etag
        if last_modified:
            headers["If-Modified-Since"] = last_modified
        response = self.client.get(url, headers=headers)
        return FetchResult(
            status_code=response.status_code,
            body=None if response.status_code == 304 else response.content,
            headers={k.lower(): v for k, v in response.headers.items()},
            url=str(response.url),
        )

    def get_with_backoff(self, url: str, attempts: int = 5) -> FetchResult:
        delay = 2.0
        for attempt in range(attempts):
            result = self.conditional_get(url)
            if result.status_code not in {429, 500, 502, 503, 504}:
                return result
            if attempt == attempts - 1:
                return result
            time.sleep(min(300, delay) + random.random())
            delay *= 2
        raise RuntimeError("unreachable")

    def discover(self, html: bytes, base_url: str | None = None) -> list[PortalForm]:
        base_url = base_url or self.index_url
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings).upper()
        if self.constituency not in page_text:
            raise ValueError(
                f"portal structure canary failed: constituency {self.constituency!r} not found"
            )

        detail_urls = self._constituency_detail_urls(soup, base_url)
        forms = self._extract_form_links(soup, base_url)
        for detail_url in detail_urls:
            result = self.get_with_backoff(detail_url)
            if result.status_code == 200 and result.body:
                detail_soup = BeautifulSoup(result.body, "html.parser")
                forms.extend(self._extract_form_links(detail_soup, result.url))

        unique: dict[str, PortalForm] = {}
        for form in forms:
            unique[form.source_url] = form
        return list(unique.values())

    def _constituency_detail_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        urls: list[str] = []
        for text_node in soup.find_all(string=re.compile(re.escape(self.constituency), re.I)):
            node = text_node.parent
            for ancestor in [node, *list(node.parents)[:4]]:
                if not ancestor:
                    continue
                for anchor in ancestor.find_all("a", href=True):
                    href = urljoin(base_url, anchor["href"])
                    if href != base_url:
                        urls.append(href)
                if urls:
                    break
        return list(dict.fromkeys(urls))[:5]

    def _extract_form_links(self, soup: BeautifulSoup, base_url: str) -> list[PortalForm]:
        output: list[PortalForm] = []
        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, anchor["href"])
            parsed = urlparse(href)
            path_lower = parsed.path.lower()
            label = " ".join(anchor.stripped_strings) or anchor.get("title", "") or href
            surrounding = " ".join(anchor.parent.stripped_strings) if anchor.parent else label
            marker = f"{label} {surrounding} {href}".lower()
            is_file = any(path_lower.endswith(ext) for ext in FORM_EXTENSIONS)
            is_form_action = any(token in marker for token in ("35a", "35b", "download", "result form", "view form"))
            if not is_file and not is_form_action:
                continue
            if self.constituency.lower() not in marker and "35a" not in marker and "35b" not in marker:
                continue
            stream_key, stream_no = infer_stream_identity(marker, self.constituency_code)
            form_type = "35B" if "35b" in marker or "form b" in marker else "35A"
            output.append(
                PortalForm(
                    source_url=href,
                    source_label=surrounding[:500],
                    stream_key=stream_key,
                    station_name=extract_station_name(surrounding),
                    stream_no=stream_no,
                    form_type=form_type,
                )
            )
        return output


def infer_stream_identity(text: str, constituency_code: str = "091") -> tuple[str | None, int | None]:
    compact = re.sub(r"\s+", " ", text)
    match = STREAM_CODE_RE.search(compact)
    if match:
        full = match.group("full")
        stream_no = int(match.group("stream"))
        station_code = full[-6:-2] if len(full) >= 6 else full[:-2]
        return f"{str(constituency_code).zfill(3)}-{station_code}-{stream_no:02d}", stream_no
    match = SHORT_STREAM_RE.search(compact)
    if match:
        station = match.group("station")
        stream_no = int(match.group("stream"))
        return f"{str(constituency_code).zfill(3)}-{station}-{stream_no:02d}", stream_no
    return None, None


def extract_station_name(text: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = re.sub(r"\b(Form|Download|View|35A|35B)\b", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:|")
    return cleaned[:180] or None


class Manifest:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.data = json.loads(path.read_text(encoding="utf-8"))
        else:
            self.data = {"index": {}, "forms": {}}

    def index_headers(self, url: str) -> tuple[str | None, str | None]:
        item = self.data.get("index", {}).get(url, {})
        return item.get("etag"), item.get("last_modified")

    def update_index(self, url: str, headers: dict[str, str]) -> None:
        self.data.setdefault("index", {})[url] = {
            "etag": headers.get("etag"),
            "last_modified": headers.get("last-modified"),
        }
        self.save()

    def known_url(self, url: str) -> dict | None:
        return self.data.get("forms", {}).get(url)

    def record_form(self, form: PortalForm, *, sha256: str, version: int) -> None:
        self.data.setdefault("forms", {})[form.source_url] = {
            "stream_key": form.stream_key,
            "sha256": sha256,
            "version": version,
            "etag": form.etag,
            "last_modified": form.last_modified,
        }
        self.save()

    def save(self) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        temp.replace(self.path)


def extension_from_response(url: str, headers: dict[str, str]) -> str:
    suffix = Path(urlparse(url).path).suffix.lower().lstrip(".")
    if suffix in {"pdf", "jpg", "jpeg", "png", "webp"}:
        return suffix
    content_type = headers.get("content-type", "").split(";", 1)[0].strip()
    return {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(content_type, "bin")


def match_unresolved_forms(
    forms: Iterable[PortalForm], known_streams: dict[str, dict]
) -> list[PortalForm]:
    by_name: dict[str, list[dict]] = {}
    for row in known_streams.values():
        key = re.sub(r"[^A-Z0-9]", "", row["station_name"].upper())
        by_name.setdefault(key, []).append(row)
    output: list[PortalForm] = []
    for form in forms:
        if form.stream_key:
            output.append(form)
            continue
        label_key = re.sub(r"[^A-Z0-9]", "", (form.station_name or form.source_label).upper())
        candidates = [rows for key, rows in by_name.items() if key and key in label_key]
        flattened = [row for rows in candidates for row in rows]
        if len(flattened) == 1:
            row = flattened[0]
            output.append(form.model_copy(update={"stream_key": row["stream_key"], "stream_no": row["stream_no"]}))
        else:
            output.append(form)
    return output
