from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .alerts import AlertSink
from .corrections import result_deltas
from .config import Settings
from .db import EngineDB
from .extraction import build_extractor, extraction_to_stream_result
from .models import StreamResult, TrustState, VerificationType, utc_now_iso
from .portal import Manifest, PortalClient, extension_from_response, match_unresolved_forms
from .publisher import Publisher
from .reference import load_reference
from .storage import archive_form, build_store
from .validation import Validator

LOGGER = logging.getLogger(__name__)


def load_eat_timezone(zoneinfo_factory=ZoneInfo):
    """Return Nairobi time even when Windows has no system IANA timezone database."""
    try:
        return zoneinfo_factory("Africa/Nairobi")
    except ZoneInfoNotFoundError:
        # Nairobi is UTC+03:00 year-round and does not observe daylight saving time.
        return timezone(timedelta(hours=3), name="EAT")


EAT = load_eat_timezone()


class Worker:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = EngineDB(settings.db_path)
        self.reference = load_reference(settings.candidates_path, settings.streams_path)
        self.store = build_store(settings)
        self.publisher = Publisher(
            settings=settings, db=self.db, reference=self.reference, store=self.store
        )
        self.portal = PortalClient(
            settings.portal_index_url,
            settings.portal_constituency,
            settings.portal_user_agent,
            constituency_code=settings.portal_constituency_code,
            detail_url=settings.portal_detail_url,
            county=settings.portal_county,
        )
        self.manifest = Manifest(settings.manifest_path)
        self.extractor = build_extractor(settings)
        self.validator = Validator(
            confidence_threshold=settings.machine_confidence_threshold,
            rejected_rate_low=settings.rejected_rate_low,
            rejected_rate_high=settings.rejected_rate_high,
        )
        self.alerts = AlertSink(settings.alert_webhook_url)
        self.zero_ticks_after_canary = 0

    def close(self) -> None:
        self.portal.close()

    def run_forever(self) -> None:
        if not self.reference.complete and not self.settings.allow_incomplete_reference:
            errors = "; ".join(self.reference.production_errors())
            raise RuntimeError(
                "Production safety gate blocked the worker because reference data is incomplete: "
                + errors
            )
        try:
            while True:
                started = time.monotonic()
                try:
                    self.tick()
                except Exception as exc:
                    LOGGER.exception("worker tick failed")
                    self.db.set_metadata("watcher_status", "ERROR")
                    self.db.heartbeat(self.settings.worker_id, "ERROR", {"error": str(exc)})
                    self.alerts.send("OL KALOU WORKER ERROR", str(exc))
                elapsed = time.monotonic() - started
                time.sleep(max(1, self.settings.portal_poll_seconds - elapsed))
        finally:
            self.close()

    def tick(self) -> dict:
        etag, last_modified = self.manifest.index_headers(self.settings.portal_index_url)
        result = self.portal.conditional_get(
            self.settings.portal_index_url, etag=etag, last_modified=last_modified
        )
        if result.status_code == 304:
            self._healthy_heartbeat(0, "NOT_MODIFIED")
            return self.publisher.publish()
        if result.status_code != 200 or result.body is None:
            raise RuntimeError(f"portal returned HTTP {result.status_code}")

        self.manifest.update_index(self.settings.portal_index_url, result.headers)
        forms = self.portal.discover(result.body, result.url)
        known = {stream.stream_key: stream.model_dump() for stream in self.reference.streams.streams}
        forms = match_unresolved_forms(forms, known)
        self.db.set_metadata("last_portal_ok", utc_now_iso())
        self.db.set_metadata("watcher_status", "OK")

        processable = [form for form in forms if form.stream_key]
        unresolved = [form for form in forms if not form.stream_key]
        if unresolved:
            self.alerts.send(
                "UNMATCHED IEBC FORMS",
                f"{len(unresolved)} discovered forms could not be matched to a certified stream.",
                {"labels": [form.source_label for form in unresolved[:10]]},
            )
        for form in processable:
            self._process_form(form)

        self._canary(len(forms))
        self._healthy_heartbeat(len(forms), "OK")
        return self.publisher.publish()

    def _process_form(self, form) -> None:
        response = self.portal.get_with_backoff(form.source_url)
        if response.status_code != 200 or response.body is None:
            raise RuntimeError(f"form download failed: {response.status_code} {form.source_url}")
        digest = hashlib.sha256(response.body).hexdigest()
        if self.db.find_by_sha(digest):
            return
        stream_key = str(form.stream_key)
        version = self.db.next_version(stream_key)
        archived = archive_form(
            settings=self.settings,
            store=self.store,
            stream_key=stream_key,
            version=version,
            body=response.body,
            extension=extension_from_response(response.url, response.headers),
            source_url=form.source_url,
            headers=response.headers,
        )
        self.db.add_form(
            stream_key=stream_key,
            version=version,
            form_type=form.form_type,
            source_url=form.source_url,
            archive_path=str(archived.archive_path),
            public_url=archived.public_url,
            sha256=archived.sha256,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )
        self.manifest.record_form(form, sha256=archived.sha256, version=version)
        if form.form_type == "35B":
            self.db.update_form_state(stream_key, version, TrustState.QUARANTINED)
            return

        extraction = self.extractor.extract(
            stream_key=stream_key, version=version, file_path=archived.archive_path
        )
        stream_result = extraction_to_stream_result(
            extraction,
            form_url=archived.public_url,
            source_url=form.source_url,
            sha256=archived.sha256,
        )
        if stream_result is None:
            self.db.update_form_state(stream_key, version, TrustState.QUARANTINED)
            return
        reference = next(
            stream for stream in self.reference.streams.streams if stream.stream_key == stream_key
        )
        prior = [
            StreamResult.model_validate(json.loads(row["payload_json"]))
            for row in self.db.stream_results(stream_key, before_version=version)
            if row.get("payload_json")
        ]
        report = self.validator.validate(stream_result, reference, prior_versions=prior)
        if prior:
            for correction in result_deltas(
                prior[-1], stream_result, reason="IEBC uploaded a newer Form 35A version."
            ):
                self.db.add_correction(correction)
        self.db.save_result(
            stream_key,
            version,
            stream_result.model_dump(mode="json"),
            report.model_dump(mode="json"),
        )
        self.db.update_form_state(stream_key, version, report.route)
        for check in report.checks:
            if check.status.value in {"FAIL", "WARN"}:
                self.db.add_anomaly(
                    stream_key,
                    check.code,
                    check.severity.value,
                    check.message,
                    archived.public_url,
                )
        if report.route == TrustState.AUTO_VERIFIED and self.settings.auto_publish_machine_verified:
            self.db.update_form_state(
                stream_key,
                version,
                TrustState.PUBLISHED,
                VerificationType.MACHINE.value,
            )

    def _canary(self, discovered: int) -> None:
        now = datetime.now(EAT)
        if now.hour >= 19 and discovered == 0:
            self.zero_ticks_after_canary += 1
        else:
            self.zero_ticks_after_canary = 0
        if self.zero_ticks_after_canary >= 3:
            self.alerts.send(
                "PORTAL SILENT-FAILURE CANARY",
                "No Ol Kalou forms discovered for three consecutive ticks after 19:00 EAT.",
            )

    def _healthy_heartbeat(self, discovered: int, status: str) -> None:
        self.db.heartbeat(
            self.settings.worker_id,
            status,
            {"discovered_forms": discovered, "at": utc_now_iso()},
        )
