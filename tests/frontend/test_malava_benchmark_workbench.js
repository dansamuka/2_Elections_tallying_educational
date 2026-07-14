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
  generated_at: "2026-07-14T12:00:00Z",
  election: { constituency: "MALAVA", code: "201", date: "2025-11-27", title: "Malava By-Election 2025 · OCR Validation" },
  reference: {
    complete: false,
    candidate_list_complete: false,
    benchmark_only: true,
    register_source: "pending",
    errors: ["benchmark"],
  },
  archive: {
    forms_expected: 2, forms_archived: 2, stream_results_transcribed: 0,
    stream_results_complete: false, tally_source: "NO_VERIFIED_TALLY",
    replay_available: false, replay_events: [], methodology_note: "benchmark",
    ocr: { documents_total: 2, pages_total: 2, pages_processed: 2, streams_matched: 2, review_rows: 2, routes: { OCR_BENCHMARK_REVIEW: 2 }, errors: [] },
    portal_sync: { state: "SUCCESS", last_completed_at: "2026-07-14T11:55:00Z" },
    portal_discovered: 2, portal_downloaded: 2, portal_unique_files: 2, portal_unmatched: 0,
  },
  coverage: { streams_total: 2, stream_rows_loaded: 2, published: 0, registered_total: 0 },
  candidates: [
    { id: "UDA", ballot_no: null, name: "David Athman Ndakwa", abbr: "UDA", colour: "#F4C542", bloc: "GOVERNMENT", votes: null, share: null },
    { id: "DAPK", ballot_no: null, name: "Seth Panyako", abbr: "DAP-K", colour: "#E85C41", bloc: "OPPOSITION", votes: null, share: null },
  ],
  official_declaration: { notes: [] },
  totals: { valid_votes: null },
  streams: [
    {
      stream_key: "201-P0001-01", station_name: "Benchmark School 1", ward: "WARD TO VERIFY",
      state: "OCR_REVIEW", registered: null, votes: {}, form_url: "forms/malava1.pdf",
      ocr: { route: "OCR_BENCHMARK_REVIEW", confidence: 0.7, checks: { V01: "NOT_RUN", V02: "PASS", V03: "NOT_RUN", V07: "NOT_RUN" }, prefill: null },
    },
    {
      stream_key: "201-P0002-01", station_name: "Benchmark School 2", ward: "WARD TO VERIFY",
      state: "ARCHIVED", registered: null, votes: {}, form_url: "forms/malava2.pdf", ocr: null,
    },
  ],
};
const CATALOG = { schema: "kenya.election.catalog.v1", default: "malava-2025", elections: [{ id: "malava-2025", label: "Malava · 27 Nov 2025" }] };

async function main() {
  const html = fs.readFileSync(path.join(FRONTEND, "archive.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "https://example.org/archive.html?election=malava-2025",
    runScripts: "dangerously", pretendToBeVisual: true,
  });
  const { window } = dom;
  window.fetch = async (url) => ({ ok: true, status: 200, json: async () => String(url).includes("catalog.json") ? CATALOG : PAYLOAD });
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  window.confirm = () => true;
  window.eval(fs.readFileSync(path.join(FRONTEND, "config.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(FRONTEND, "archive.js"), "utf8"));
  await new Promise((resolve) => setTimeout(resolve, 50));

  const doc = window.document;
  doc.querySelector('[data-stream-key="201-P0001-01"]').dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  assert.match(doc.getElementById("archiveDialogBody").textContent, /OCR VALIDATION BENCHMARK/);
  assert.equal(doc.getElementById("rfConfirm").textContent.trim(), "Save OCR benchmark review");

  const setInput = (id, value) => {
    const input = doc.getElementById(id);
    input.value = value;
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  };
  setInput("rf-registered", "500");
  setInput("rf-vote-UDA", "30");
  setInput("rf-vote-DAPK", "20");
  setInput("rf-rejected", "1");
  setInput("rf-valid", "60"); // configured candidate subtotal is deliberately only 50
  setInput("rf-cast", "61");
  setInput("rf-reviewer", "Benchmark Reviewer");

  assert.match(doc.getElementById("rfHumanChecks").textContent, /V01 NOT_RUN/);
  assert.match(doc.getElementById("rfHumanChecks").textContent, /V02 PASS/);
  assert.match(doc.getElementById("rfArithmetic").textContent, /Configured candidate subtotal/);
  assert.equal(doc.getElementById("rfConfirm").disabled, false,
    "an incomplete candidate roster must not force its subtotal to equal total valid");

  doc.getElementById("rfConfirm").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((resolve) => setTimeout(resolve, 20));
  assert.match(doc.getElementById("reviewProgress").textContent, /1 \/ 2 OCR benchmark streams reviewed/);
  assert.match(doc.getElementById("reviewProgress").textContent, /60 PO-stated valid/,
    "benchmark tally uses the independently reviewed PO total, not the incomplete candidate subtotal");
  assert.match(doc.getElementById("reviewProgress").textContent, /configured-field subtotal/);
  assert.ok(doc.querySelector('[data-stream-key="201-P0001-01"]').className.includes("locally-confirmed"));

  console.log("Malava benchmark workbench test passed.");
  process.exit(0);
}

main().catch((error) => { console.error(error); process.exit(1); });
