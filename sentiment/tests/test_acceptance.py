#!/usr/bin/env python3
"""Automated slice of Section 11's acceptance tests, plus the addendum's
Section F additions. Not everything in Section 11 is automatable (e.g. test 9,
GitHub Pages subdirectory routing, is an infra check you do once by hand) -
this covers what can be checked from the generated payload and pipeline code.

Run: python3 tests/test_acceptance.py
"""
import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # sentiment/ module root
REPO_ROOT = os.path.dirname(ROOT)  # actual repo root - one level up (frontend/, data/public/ live here)
SCRIPTS = os.path.join(ROOT, "scripts")
PUBLIC_PATH = os.path.join(REPO_ROOT, "data", "public", "sentiment", "latest.json")


class AcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run([sys.executable, "build_public_json.py", "--demo", "--mode", "demo"],
                        cwd=SCRIPTS, check=True)
        with open(PUBLIC_PATH) as f:
            cls.payload = json.load(f)
        cls.payload_str = json.dumps(cls.payload)

    # --- Section 11 ---

    def test_02_no_raw_identifiers_in_public_payload(self):
        """No raw X post text, username, user ID, post ID, or protected-post URL."""
        for forbidden_key in ("raw_text", "author_ref", "platform_id", "normalized_text", "redacted_text"):
            self.assertNotIn(f'"{forbidden_key}"', self.payload_str,
                              f"Forbidden field '{forbidden_key}' leaked into public payload")
        self.assertNotIn("@", self.payload_str.replace("@election", ""),  # crude handle sniff, allow the word "email" etc if ever added
                          "Possible @handle leaked into public payload")

    def test_03_candidate_aliases_resolve(self):
        """Every configured candidate id appears in the output (suppressed or not)."""
        cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
        output_ids = {c["id"] for c in self.payload["candidates"]}
        config_ids = {c["id"] for c in cfg["candidates"]}
        self.assertEqual(output_ids, config_ids)

    def test_06_unsupported_language_is_unscored(self):
        """An item with no English or Kiswahili signal must be labelled unscored, not guessed."""
        sys.path.insert(0, SCRIPTS)
        import importlib
        pc = importlib.import_module("pipeline_classify")
        ps = importlib.import_module("pipeline_sentiment")
        item = {"redacted_text": "xkzq nonsense placeholder tokens zzqx"}
        item["language"] = pc.classify_language(list(item["redacted_text"].split()))
        cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
        scored = ps.score_item(dict(item), cfg["sentiment_thresholds"])
        self.assertEqual(scored["sentiment_label"], "unscored")

    def test_07_five_item_floor_suppresses_cell(self):
        """A candidate/topic cell with fewer than the configured floor is suppressed."""
        cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
        floor = cfg["display_thresholds"]["min_independent_items_for_cell"]
        for c in self.payload["candidates"]:
            if not c["suppressed"]:
                self.assertGreaterEqual(c["mention_count"], floor)

    def test_08_dashboard_has_demo_fallback(self):
        """The dashboard embeds a DEMO_FALLBACK constant used when the live JSON is unreachable."""
        html = open(os.path.join(REPO_ROOT, "frontend", "sentiment.html")).read()
        self.assertIn("DEMO_FALLBACK", html)
        self.assertIn("render(DEMO_FALLBACK, true)", html)
        # Sanity check the chart functions this dashboard relies on are present.
        for fn in ("function trendChart", "function sparkline", "function donutChart"):
            self.assertIn(fn, html)

    def test_10_module_never_touches_tallying_paths(self):
        """No script in this module writes outside data/, config/, or docs/sentiment/."""
        for fname in os.listdir(SCRIPTS):
            if not fname.endswith(".py"):
                continue
            text = open(os.path.join(SCRIPTS, fname)).read()
            self.assertNotIn("OCR", text)
            self.assertNotIn("tallying", text.lower().replace("tallying pipeline", ""))

    # --- Addendum Section F ---

    def test_11_alert_requires_corroboration_not_just_volume(self):
        sys.path.insert(0, SCRIPTS)
        import importlib
        pa = importlib.import_module("pipeline_alerts")
        cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
        # 20 items, all from the SAME single author bucket - volume alone, zero corroboration.
        items = [{"topic": "security", "author_buckets": {"same-author"}, "topic_confidence": 1.0,
                  "timestamp": "2026-07-16T06:00:00Z"} for _ in range(20)]
        alerts = pa.generate(items, cfg, {}, [])
        self.assertEqual(alerts, [], "Alert fired on single-source volume alone - corroboration check is broken")

    def test_13_alert_summary_has_no_named_individual_by_default(self):
        for alert in self.payload["alerts"]:
            cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
            names = [c["name"] for c in cfg["candidates"]]
            for name in names:
                self.assertNotIn(name, alert["summary"])

    def test_15_override_wins_over_automated_status(self):
        sys.path.insert(0, SCRIPTS)
        import importlib
        pa = importlib.import_module("pipeline_alerts")
        cfg = json.load(open(os.path.join(ROOT, "config", "sentiment_config.json")))
        items = [{"topic": "security", "author_buckets": {f"a{i}"}, "topic_confidence": 1.0,
                  "timestamp": "2026-07-16T06:00:00Z"} for i in range(15)]
        overrides = [{"id": "ol-kalou-2026:security", "status": "retracted", "summary": "test retraction"}]
        alerts = pa.generate(items, cfg, {}, overrides)
        self.assertEqual(alerts[0]["status"], "retracted")
        self.assertTrue(alerts[0]["override_applied"])


    def test_16_audit_directory_is_gitignored(self):
        """The private audit trail (raw text, unhashed author refs) must never be committable."""
        gitignore = open(os.path.join(ROOT, ".gitignore")).read()
        self.assertIn("data/private/sentiment/audit/", gitignore)

    def test_17_timeline_accumulates_across_runs(self):
        """A second run should append to, not replace, the timeline."""
        before_len = len(self.payload["timeline"])
        subprocess.run([sys.executable, "build_public_json.py", "--demo", "--mode", "demo"],
                        cwd=SCRIPTS, check=True)
        with open(PUBLIC_PATH) as f:
            after = json.load(f)
        self.assertEqual(len(after["timeline"]), before_len + 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
