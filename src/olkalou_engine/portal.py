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
        county: str | None = None,
    ):
        self.index_url = index_url
        self.constituency = constituency.upper().strip()
        self.constituency_code = str(constituency_code).zfill(3)
        self.detail_url = detail_url
        self.county = (county or "").upper().strip()
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
        """Discover constituency form downloads by walking IEBC's full hierarchy.

        The IEBC site is stateful and exposes navigation rows rather than durable
        hyperlinks. A constituency page can lead through county, constituency,
        ward, polling centre and finally polling-stream pages. We therefore crawl
        only the exact configured route until the constituency breadcrumb is
        reached, then descend every child row inside that constituency. Bulk
        ``Download All`` controls are deliberately ignored because an ordinary GET
        can fall back to a broader county/national HTML page.
        """
        base_url = base_url or self.index_url
        soup = BeautifulSoup(html, "html.parser")
        page_text = " ".join(soup.stripped_strings).upper()
        if self.constituency not in page_text:
            raise ValueError(
                f"portal structure canary failed: constituency {self.constituency!r} not found"
            )

        forms: list[PortalForm] = []
        queue = (
            [urljoin(base_url, self.detail_url)]
            if self.detail_url
            else list(self._constituency_detail_urls(soup, base_url))
        )
        visit_counts: dict[str, int] = {}
        pages_fetched = 0
        max_pages = 500
        while queue and pages_fetched < max_pages:
            detail_url = queue.pop(0)
            # IEBC reuses the same id URL at different hierarchy levels and keeps
            # the current level in session state. Permit a small bounded revisit.
            if visit_counts.get(detail_url, 0) >= 3:
                continue
            visit_counts[detail_url] = visit_counts.get(detail_url, 0) + 1
            pages_fetched += 1
            result = self.get_with_backoff(detail_url)
            if result.status_code != 200 or not result.body:
                continue
            requested_ids = parse_qs(urlparse(detail_url).query).get("id", [])
            final_ids = parse_qs(urlparse(result.url).query).get("id", [])
            detail_soup = BeautifulSoup(result.body, "html.parser")
            if requested_ids and final_ids != requested_ids:
                # IEBC sometimes drops the id while returning a legitimate county
                # selector. Allow that only when the page exposes a safe next hop
                # matching the configured county/constituency route.
                safe_children = self._hierarchy_child_urls(detail_soup, result.url)
                if not safe_children:
                    raise RuntimeError(
                        "IEBC hierarchy request lost its row id or changed it after redirect; "
                        "refusing to widen the crawl beyond the configured constituency"
                    )

            forms.extend(
                self._extract_form_links(
                    detail_soup,
                    result.url,
                    constituency_scoped=True,
                    include_bulk=False,
                )
            )

            for child_url in self._hierarchy_child_urls(detail_soup, result.url):
                if visit_counts.get(child_url, 0) < 3 and child_url not in queue:
                    queue.append(child_url)
            for page_url in self._pagination_urls(detail_soup, result.url):
                if visit_counts.get(page_url, 0) < 3 and page_url not in queue:
                    queue.append(page_url)

        if queue:
            raise RuntimeError(
                f"IEBC hierarchy crawl exceeded {max_pages} pages for {self.constituency}; "
                "refusing to publish a potentially incomplete archive"
            )

        unique: dict[str, PortalForm] = {}
        for form in forms:
            unique[form.source_url] = form
        return list(unique.values())

    @staticmethod
    def _breadcrumb_text(soup: BeautifulSoup) -> str:
        nodes = soup.select("ul.breadcrumb li, ol.breadcrumb li, .breadcrumb li")
        return " ".join(" ".join(node.stripped_strings) for node in nodes).upper()

    @staticmethod
    def _row_label(row: object) -> str:
        cells = getattr(row, "find_all", lambda *args, **kwargs: [])("td", recursive=False)
        if not cells:
            cells = getattr(row, "find_all", lambda *args, **kwargs: [])("td")
        if not cells:
            return ""
        return " ".join(cells[0].stripped_strings).upper().strip()

    def _navigation_rows(self, soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
        output: list[tuple[str, str]] = []
        base_host = urlparse(base_url).netloc
        for row in soup.find_all("tr"):
            label = self._row_label(row)
            if not label:
                continue
            # Leaf polling-stream rows carry explicit view/download anchors and
            # should not be treated as another hierarchy level.
            row_marker = f"{label} {' '.join(row.stripped_strings)}".lower()
            if row.find("a", href=re.compile(r"(?:download|view)", re.I)) and "reported" in row_marker:
                continue
            urls = self._candidate_urls(row, base_url)
            for url in urls:
                parsed = urlparse(url)
                if parsed.netloc != base_host or url == base_url:
                    continue
                if not parse_qs(parsed.query).get("id"):
                    continue
                output.append((label, url))
                break
        # Preserve portal order while deduplicating by URL.
        seen: set[str] = set()
        result: list[tuple[str, str]] = []
        for label, url in output:
            if url not in seen:
                seen.add(url)
                result.append((label, url))
        return result

    def _hierarchy_child_urls(self, soup: BeautifulSoup, base_url: str) -> list[str]:
        """Choose only safe child rows for the configured election route."""
        rows = self._navigation_rows(soup, base_url)
        if not rows:
            return []
        breadcrumb = self._breadcrumb_text(soup)
        page_headers = " ".join(
            " ".join(node.stripped_strings) for node in soup.select("table thead th")
        ).upper()

        # Once BANISSA is present in the breadcrumb, all navigation rows are
        # descendants (wards, polling centres, then stations) and are safe to crawl.
        if self.constituency in breadcrumb:
            return [url for _, url in rows]

        # Some portal responses fall back to the county selector. Follow only the
        # configured county, never every county.
        if self.county:
            county_matches = [url for label, url in rows if self._label_matches(label, self.county)]
            if county_matches and ("COUNTY" in page_headers or self.county not in breadcrumb):
                return county_matches[:1]

        # At county level follow only the configured constituency row.
        constituency_matches = [
            url for label, url in rows if self._label_matches(label, self.constituency)
        ]
        if constituency_matches:
            return constituency_matches[:1]
        return []

    @staticmethod
    def _label_matches(label: str, target: str) -> bool:
        normal = re.sub(r"[^A-Z0-9]", "", label.upper())
        wanted = re.sub(r"[^A-Z0-9]", "", target.upper())
        return bool(wanted and normal == wanted)

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
        self,
        soup: BeautifulSoup,
        base_url: str,
        *,
        constituency_scoped: bool = False,
        include_bulk: bool = False,
    ) -> list[PortalForm]:
        output: list[PortalForm] = []
        candidates: list[tuple[str, str, str, str]] = []
        for node in soup.find_all(["a", "button", "iframe", "embed", "object", "form"]):
            label = " ".join(node.stripped_strings) or node.get("title", "") or node.get("aria-label", "")
            row = node.find_parent("tr")
            station_hint = ""
            if row is not None:
                surrounding = " ".join(row.stripped_strings)
                cells = row.find_all("td")
                if len(cells) >= 2:
                    station_hint = " ".join(cells[1].stripped_strings).strip()
            else:
                surrounding = " ".join(node.parent.stripped_strings) if node.parent else label
            for href in self._candidate_urls(node, base_url):
                candidates.append((href, label or href, surrounding or label or href, station_hint))
        # Some Yii views embed endpoints in scripts or row attributes. Parse them as
        # candidates, but retain the same strict form/download marker below.
        script_text = "\n".join(node.get_text(" ", strip=False) for node in soup.find_all("script"))
        for raw in re.findall(r"(?:https?://[^'\"<>\s]+|(?:/|index\.php\?)[^'\"<>\s]+)", script_text):
            href = urljoin(base_url, raw.replace("&amp;", "&"))
            candidates.append((href, href, href, ""))

        seen_urls: set[str] = set()
        for href, label, surrounding, station_hint in candidates:
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
            href_marker = href.lower()
            is_direct_download = is_file or any(
                token in href_marker
                for token in (
                    "site%2fdownload",
                    "site/download",
                    "download-form",
                    "download&id=",
                    "download=" ,
                )
            ) or "download" in label.lower()
            # The eye icon usually opens an HTML preview. Prefer the cloud/download
            # icon so the archive receives the original PDF or image bytes.
            if not is_direct_download:
                continue
            # Never treat a bulk control as an individual form unless a caller
            # explicitly opts in. IEBC may return a broader HTML selector page.
            if "download-all" in marker and not include_bulk:
                continue
            if (
                not constituency_scoped
                and self.constituency.lower() not in marker
                and "35a" not in marker
                and "35b" not in marker
            ):
                continue
            identity_marker = station_hint or marker
            stream_key, stream_no = infer_stream_identity(identity_marker, self.constituency_code)
            station_name = extract_station_name(station_hint or surrounding)
            if station_hint:
                suffix = re.search(r"\s+0?([0-9]{1,2})\s*$", station_hint)
                if suffix:
                    stream_no = int(suffix.group(1))
                    station_name = re.sub(r"\s+0?[0-9]{1,2}\s*$", "", station_hint).strip() or station_name
            form_type = "35B" if "35b" in marker or "form b" in marker else "35A"
            output.append(
                PortalForm(
                    source_url=href,
                    source_label=surrounding[:500],
                    stream_key=stream_key,
                    station_name=station_name,
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
