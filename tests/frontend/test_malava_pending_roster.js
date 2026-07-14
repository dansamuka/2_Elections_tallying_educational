"use strict";
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const assert = require("node:assert/strict");

const FRONTEND = path.resolve(__dirname, "..", "..", "frontend");
const PAYLOAD = {
  schema: "kenya.election.archive.v1",
  election_id: "malava-2025",
  mode: "ARCHIVE",
  status: "OCR_BENCHMARK",
  generated_at: "2026-07-14T15:08:21Z",
  election: {
    constituency: "MALAVA", code: "201", date: "2025-11-27",
    title: "Malava By-Election 2025 · OCR Validation",
  },
  reference: {
    complete: false,
    candidate_list_complete: false,
    benchmark_only: true,
    errors: ["register pending"],
  },
  archive: {
    forms_expected: 198, forms_archived: 0, stream_results_transcribed: 0,
    stream_results_complete: false, tally_source: "NO_VERIFIED_TALLY",
    replay_available: false, replay_events: [], methodology_note: "benchmark",
    ocr: { pages_processed: 0, pages_total: 0, review_rows: 0, documents_total: 0, streams_matched: 0, routes: {}, errors: [] },
    portal_sync: { state: "NEVER_RUN", last_completed_at: null },
    portal_discovered: 0, portal_downloaded: 0, portal_unique_files: 0,
    portal_duplicate_assignments: 0, portal_failed_downloads: 0, portal_unmatched: 0,
  },
  coverage: {
    streams_total: 198, stream_rows_loaded: 0, published: 0, in_review: 0,
    awaiting: 198, registered_total: 0,
  },
  candidates: [
    { id: "UDA", name: "David Athman Ndakwa", abbr: "UDA", colour: "#F4C542", votes: null, share: null },
    { id: "DAPK", name: "Seth Panyako", abbr: "DAP-K", colour: "#E85C41", votes: null, share: null },
  ],
  official_declaration: { notes: [] },
  totals: { valid_votes: null },
  streams: [],
  wards: [],
};
const CATALOG = {
  schema: "kenya.election.catalog.v1",
  default: "malava-2025",
  elections: [{ id: "malava-2025", label: "Malava OCR benchmark · 27 Nov 2025" }],
};

async function main() {
  const html = fs.readFileSync(path.join(FRONTEND, "archive.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "https://example.org/archive.html?election=malava-2025",
    runScripts: "dangerously",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  window.fetch = async (url) => ({
    ok: true,
    status: 200,
    json: async () => String(url).includes("catalog.json") ? CATALOG : PAYLOAD,
  });
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  window.confirm = () => true;

  window.eval(fs.readFileSync(path.join(FRONTEND, "config.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(FRONTEND, "archive.js"), "utf8"));
  await new Promise((resolve) => setTimeout(resolve, 50));

  const doc = window.document;
  assert.equal(doc.querySelectorAll(".roster-placeholder").length, 198,
    "the expected Malava coverage must remain visible before the first portal sync");
  assert.equal(doc.querySelectorAll(".archive-stream-cell").length, 0,
    "placeholder boxes must not masquerade as source-linked clickable streams");
  assert.equal(doc.getElementById("archiveReplayLabel").textContent, "OCR BENCHMARK");
  assert.equal(doc.getElementById("archiveReplayState").textContent, "AWAITING FORMS");
  assert.match(doc.getElementById("archiveGridCounter").textContent, /0\/198 roster pending/);
  assert.match(doc.getElementById("replayUnavailable").textContent, /OCR benchmark mode/);
  assert.doesNotMatch(doc.getElementById("replayUnavailable").textContent, /Replay withheld/);
  assert.match(doc.getElementById("archiveTable").textContent, /awaiting the first IEBC portal sync/);
  assert.match(doc.getElementById("archiveGapNote").textContent, /showing 198 disabled placeholders/);

  console.log("Malava pending-roster UI test passed.");
  process.exit(0);
}

main().catch((error) => { console.error(error); process.exit(1); });
