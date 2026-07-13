from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from html import unescape
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from .models import PortalForm

FORM_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".zip"}
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
        detail_url: str | None = None,
    ):
        self.index_url = index_url
        self.constituency = constituency.upper().strip()
        self.constituency_code = str(constituency_code).zfill(3)
        self.detail_url = detail_url
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

    def reported_counts(self, html: bytes) -> tuple[int | None, int | None]:
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings)
        pattern = re.compile(
            rf"{re.escape(self.constituency)}\s+(?P<reported>[0-9,]+)\s+of\s+(?P<expected>[0-9,]+)",
            re.I,
        )
        match = pattern.search(page_text)
        if not match:
            return None, None
        return (
            int(match.group("reported").replace(",", "")),
            int(match.group("expected").replace(",", "")),
        )

    def discover(self, html: bytes, base_url: str | None = None) -> list[PortalForm]:
        base_url = base_url or self.index_url
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings).upper()
        if self.constituency not in page_text:
            raise ValueError(
                f"portal structure canary failed: constituency {self.constituency!r} not found"
            )

        forms = self._extract_form_links(soup, base_url, constituency_scoped=False)
        queue = (
            [urljoin(base_url, self.detail_url)]
            if self.detail_url
            else list(self._constituency_detail_urls(soup, base_url))
        )
        visited: set[str] = set()
        # The IEBC portal uses Yii pagination on some result views. Crawl every
        # pagination page so "download all" means all forms for this constituency,
        # not just the first visible page.
        while queue and len(visited) < 40:
            detail_url = queue.pop(0)
            if detail_url in visited:
                continue
            visited.add(detail_url)
            result = self.get_with_backoff(detail_url)
            if result.status_code != 200 or not result.body:
                continue
            requested_ids = parse_qs(urlparse(detail_url).query).get("id", [])
            final_ids = parse_qs(urlparse(result.url).query).get("id", [])
            if requested_ids and final_ids != requested_ids:
                raise RuntimeError(
                    "IEBC constituency detail request lost its row id after redirect; "
                    "refusing to treat the national Download All control as constituency-scoped"
                )
            detail_soup = BeautifulSoup(result.body, "html.parser")
            forms.extend(self._extract_form_links(detail_soup, result.url, constituency_scoped=True))
            for page_url in self._pagination_urls(detail_soup, result.url):
                if page_url not in visited and page_url not in queue:
                    queue.append(page_url)

        unique: dict[str, PortalForm] = {}
        for form in forms:
            unique[form.source_url] = form
        return list(unique.values())

    @staticmethod
    def _candidate_urls(node: object, base_url: str) -> list[str]:
        values: list[str] = []
        attrs = getattr(node, "attrs", {}) or {}
        for key in ("href", "data-url", "data-href", "data-download", "formaction", "src"):
            value = attrs.get(key)
            if isinstance(value, str) and value.strip():
                values.append(urljoin(base_url, value.strip()))
        onclick = attrs.get("onclick")
        if isinstance(onclick, str):
            decoded = unescape(onclick)
            # The current IEBC index builds the constituency URL by concatenating
            # the table-row id inside JavaScript, for example:
            #   location.href = "/index.php?...&id=" + id + "&p=2";
            # Extracting quoted fragments independently loses the id and sends the
            # crawler back to the national index. Reconstruct the complete RHS.
            assignment = re.search(r"location\.href\s*=\s*(.*?);", decoded, re.I | re.S)
            row_id = attrs.get("id")
            reconstructed = None
            if assignment and row_id:
                pieces: list[str] = []
                used_variable = False
                for token in re.finditer(
                    r'"(?P<double>[^"\\]*(?:\\.[^"\\]*)*)"'
                    r"|'(?P<single>[^'\\]*(?:\\.[^'\\]*)*)'"
                    r"|(?P<variable>\bid\b)",
                    assignment.group(1),
                ):
                    if token.group("variable"):
                        pieces.append(str(row_id))
                        used_variable = True
                    else:
                        pieces.append(token.group("double") or token.group("single") or "")
                if used_variable and pieces:
                    reconstructed = "".join(pieces)
                    values.append(urljoin(base_url, reconstructed))
            if reconstructed is None:
                for match in re.findall(r"(?:https?://[^'\"\s]+|(?:/|index\.php\?)[^'\"\s,)]+)", decoded):
                    values.append(urljoin(base_url, match.replace("&amp;", "&")))
        return values

    def _constituency_detail_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        urls: list[str] = []
        for text_node in soup.find_all(string=re.compile(re.escape(self.constituency), re.I)):
            node = text_node.parent
            row = node.find_parent("tr") if node else None
            # Prefer the exact constituency row. Ascending to the whole table can
            # accidentally collect the national Download All control.
            scopes = [row] if row else [node, *list(node.parents)[:3]]
            for scope in scopes:
                if not scope:
                    continue
                urls.extend(self._candidate_urls(scope, base_url))
                for descendant in scope.find_all(["a", "button", "tr", "td", "form"]):
                    urls.extend(self._candidate_urls(descendant, base_url))
                if urls:
                    break
            if urls:
                break
        filtered: list[str] = []
        for url in urls:
            if url == base_url or url.startswith("javascript:") or url.startswith("#"):
                continue
            # A valid constituency detail URL must retain the row id. Discard
            # malformed JavaScript fragments such as URLs ending in '&id='.
            parsed = urlparse(url)
            if re.search(r"(?:[?&])id=$", parsed.query):
                continue
            filtered.append(url)
        return list(dict.fromkeys(filtered))[:12]

    def _pagination_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        base_host = urlparse(base_url).netloc
        urls: list[str] = []
        for anchor in soup.select("ul.pagination a[href], .pagination a[href], a[rel='next']"):
            href = urljoin(base_url, str(anchor.get("href", "")).strip())
            parsed = urlparse(href)
            if parsed.netloc != base_host:
                continue
            label = " ".join(anchor.stripped_strings).strip().lower()
            marker = f"{label} {href}".lower()
            if not any(token in marker for token in ("page", "next", "older", "»", ">")):
                continue
            urls.append(href)
        return list(dict.fromkeys(urls))

    def _extract_form_links(
        self, soup: BeautifulSoup, base_url: str, *, constituency_scoped: bool = False
    ) -> list[PortalForm]:
        output: list[PortalForm] = []
        candidates: list[tuple[str, str, str]] = []
        for node in soup.find_all(["a", "button", "iframe", "embed", "object", "form"]):
            label = " ".join(node.stripped_strings) or node.get("title", "") or node.get("aria-label", "")
            surrounding = " ".join(node.parent.stripped_strings) if node.parent else label
            for href in self._candidate_urls(node, base_url):
                candidates.append((href, label or href, surrounding or label or href))
        # Some Yii views embed endpoints in scripts or row attributes. Parse them as
        # candidates, but retain the same strict form/download marker below.
        script_text = "\n".join(node.get_text(" ", strip=False) for node in soup.find_all("script"))
        for raw in re.findall(r"(?:https?://[^'\"<>\s]+|(?:/|index\.php\?)[^'\"<>\s]+)", script_text):
            href = urljoin(base_url, raw.replace("&amp;", "&"))
            candidates.append((href, href, href))

        seen_urls: set[str] = set()
        for href, label, surrounding in candidates:
            if href in seen_urls:
                continue
            seen_urls.add(href)
            parsed = urlparse(href)
            path_lower = parsed.path.lower()
            marker = f"{label} {surrounding} {href}".lower()
            is_file = any(path_lower.endswith(ext) for ext in FORM_EXTENSIONS)
            is_form_action = any(
                token in marker
                for token in (
                    "35a",
                    "35b",
                    "form a",
                    "form b",
                    "download",
                    "result form",
                    "view form",
                    "site/view",
                    "site/download",
                )
            )
            if not is_file and not is_form_action:
                continue
            # Exclude the top-level Download All endpoint unless an election profile
            # explicitly points to it; it can contain forms for every constituency.
            if "download-all" in marker and not constituency_scoped:
                continue
            if (
                not constituency_scoped
                and self.constituency.lower() not in marker
                and "35a" not in marker
                and "35b" not in marker
            ):
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
    if suffix in {"pdf", "jpg", "jpeg", "png", "webp", "zip"}:
        return suffix
    content_type = headers.get("content-type", "").split(";", 1)[0].strip()
    return {
        "application/pdf": "pdf",
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "application/zip": "zip",
        "application/x-zip-compressed": "zip",
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
