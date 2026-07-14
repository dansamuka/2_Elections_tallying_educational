// Execution tests for frontend/archive.js's review workbench (OCR prefill
// display, editable draft inputs, localStorage persistence, CSV export).
// Loads the REAL archive.html/archive.js/config.js and drives them through
// jsdom with realistic synthetic data -- not mocks of the app's own
// functions, the actual shipped code, exercised the way a browser would.
//
// Setup:  cd tests/frontend && npm install
// Run:    npm test   (or: node test_review_workbench.js)
//
// Not wired into the Python test suite (pytest doesn't run JS) -- CI runs
// this as its own step in .github/workflows/ci.yml.
"use strict";
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const assert = require("node:assert/strict");

const FRONTEND = path.resolve(__dirname, "..", "..", "frontend");

// Realistic synthetic payload, same shape as the real
// data/public/elections/banissa-2025.json, but with clearly-fake round
// numbers on every OCR field so this test data could never be mistaken for
// the real dataset if it ever surfaced outside this file.
const PAYLOAD = {
  schema: "kenya.election.archive.v1",
  election_id: "banissa-2025",
  mode: "ARCHIVE",
  generated_at: "2026-07-14T08:25:00Z",
  election: { constituency: "BANISSA", code: "040", date: "2025-11-27", title: "Banissa By-Election 2025" },
  reference: { complete: true, register_source: "Test Gazette", register_source_url: "" },
  archive: {
    forms_expected: 4,
    forms_archived: 3,
    stream_results_transcribed: 0,
    stream_results_complete: false,
    tally_source: "OFFICIAL_DECLARATION",
    replay_available: false,
    replay_events: [],
    methodology_note: "test",
    ocr: { documents_total: 3, pages_total: 3, pages_processed: 3, streams_matched: 2, review_rows: 2, routes: {}, errors: [] },
    portal_sync: { state: "SUCCESS", last_completed_at: "2026-07-14T08:20:00Z" },
    portal_discovered: 4, portal_downloaded: 4, portal_unmatched: 1,
  },
  coverage: { streams_total: 4, published: 0, registered_total: 1000 },
  candidates: [
    { id: "UDA", ballot_no: 1, name: "Test Candidate A", abbr: "UDA", colour: "#F4C542", bloc: "GOVERNMENT", votes: null, share: null },
    { id: "UPA", ballot_no: 2, name: "Test Candidate B", abbr: "UPA", colour: "#5C8FC7", bloc: "OPPOSITION", votes: null, share: null },
  ],
  official_declaration: { winner_id: "UDA", winner_votes: 700, notes: [] },
  totals: { valid_votes: null },
  streams: [
    {
      stream_key: "TEST-001", station_name: "Test School A", ward: "WARD1", state: "OCR_REVIEW",
      registered: 500, votes: {}, form_url: "forms/test1.pdf",
      ocr: {
        route: "QUARANTINE", confidence: 0.41, checks: { V01: "FAIL", V07: "PASS" },
        prefill: { votes: { UDA: 30, UPA: 20 }, registered: 500, rejected: 1, total_valid: 51, total_cast: 52 },
      },
    },
    {
      stream_key: "TEST-002", station_name: "Test School B", ward: "WARD1", state: "ARCHIVED",
      registered: 300, votes: {}, form_url: "forms/test2.pdf", ocr: null,
    },
    {
      stream_key: "TEST-003", station_name: "Test School C", ward: "WARD1", state: "REFERENCE_ONLY",
      registered: 200, votes: {}, form_url: null, ocr: null,
    },
    {
      stream_key: "TEST-004", station_name: "Test School D", ward: "WARD1", state: "PUBLISHED",
      registered: 100, votes: { UDA: 40, UPA: 10 }, valid: 50, form_url: "forms/test4.pdf", ocr: null,
    },
  ],
};

const CATALOG = { schema: "kenya.election.catalog.v1", default: "banissa-2025", elections: [{ id: "banissa-2025", label: "Banissa · 27 Nov 2025" }] };

async function main() {
  const html = fs.readFileSync(path.join(FRONTEND, "archive.html"), "utf8");
  const dom = new JSDOM(html, {
    url: "https://example.org/2_Elections_tallying_educational/archive.html?election=banissa-2025",
    runScripts: "dangerously",
    pretendToBeVisual: true,
  });
  const { window } = dom;

  window.fetch = async (url) => {
    const clean = String(url).split("?")[0];
    const body = clean.includes("catalog.json") ? CATALOG : PAYLOAD;
    return { ok: true, status: 200, json: async () => body };
  };
  // jsdom doesn't implement <dialog> show/close -- stub minimally so the
  // real app code runs completely unmodified.
  window.HTMLDialogElement.prototype.showModal = function () { this.setAttribute("open", ""); };
  window.HTMLDialogElement.prototype.close = function () { this.removeAttribute("open"); };
  window.confirm = () => true;

  // jsdom's Blob implementation varies across versions in which methods it
  // exposes (some lack .text()/.arrayBuffer() entirely) -- capture what's
  // actually passed to `new Blob(...)` directly instead of depending on
  // reading it back out afterward, which is robust to that regardless of
  // jsdom version.
  let capturedBlobParts = null;
  const RealBlob = window.Blob;
  window.Blob = function (parts, opts) {
    capturedBlobParts = parts;
    return new RealBlob(parts, opts);
  };
  window.Blob.prototype = RealBlob.prototype;

  window.eval(fs.readFileSync(path.join(FRONTEND, "config.js"), "utf8"));
  window.eval(fs.readFileSync(path.join(FRONTEND, "archive.js"), "utf8"));

  await new Promise((r) => setTimeout(r, 50)); // let init()'s async fetch settle

  const doc = window.document;
  const openStreamViaClick = (streamKey) => {
    const btn = doc.querySelector(`[data-stream-key="${streamKey}"]`);
    if (!btn) throw new Error(`No clickable element found for ${streamKey}`);
    btn.dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  };

  assert.match(doc.getElementById("archiveTitle").textContent, /Banissa/, "title renders from payload");
  assert.equal(doc.getElementById("archiveForms").textContent.trim(), "3/4",
    "FORMS ARCHIVED must show the honest 3/4, not an inflated max(forms_archived, portal_downloaded)");
  assert.equal(doc.getElementById("archiveGapNote").hidden, false, "gap note must be visible when forms_archived < forms_expected");
  assert.match(doc.getElementById("archiveGapNote").textContent, /Matched to a stream/, "gap note explains the funnel");

  const readinessText = doc.getElementById("archiveReadiness").textContent;
  assert.ok(readinessText.includes("Source documents inventoried") && readinessText.includes("3 / 4"),
    "'Source documents inventoried' must compare against forms_expected (4), not against itself (previously always showed 100%)");
  assert.match(readinessText, /Portal downloads unmatched to a stream/, "portal_unmatched must be surfaced, not hidden");
  assert.match(readinessText, /OCR-read but unmatched to a stream/, "the OCR-vs-matched gap must be surfaced, not hidden");

  openStreamViaClick("TEST-001");
  const body = doc.getElementById("archiveDialogBody").innerHTML;
  assert.ok(body.includes('class="form-frame"') && body.includes("test1.pdf"), "modal embeds the source PDF in an iframe");
  assert.ok(body.includes("Test Candidate A") && body.includes("Test Candidate B"), "modal lists every candidate");
  const voteA = doc.getElementById("rf-vote-UDA");
  const voteB = doc.getElementById("rf-vote-UPA");
  assert.equal(voteA.value, "30", "candidate A input is pre-filled from the OCR reading");
  assert.equal(voteB.value, "20", "candidate B input is pre-filled from the OCR reading");
  assert.ok(body.includes("V01") && body.includes("FAIL") && body.includes("V07") && body.includes("PASS"), "OCR statutory-check badges render");

  // A reviewer corrects candidate A's figure after checking the embedded PDF.
  voteA.value = "245";
  voteA.dispatchEvent(new window.Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 10));
  const saved = JSON.parse(window.localStorage.getItem("olkalou-archive-drafts:banissa-2025") || "{}");
  assert.equal(Number(saved["TEST-001"].votes.UDA), 245, "editing an input persists the correction to localStorage");
  assert.equal(Number(saved["TEST-001"].votes.UPA), 20, "the untouched candidate keeps its OCR-prefilled value in the saved draft");
  assert.match(doc.getElementById("draftCount").textContent, /1 stream/, "the toolbar draft counter updates");

  openStreamViaClick("TEST-001");
  assert.equal(doc.getElementById("rf-vote-UDA").value, "245", "re-opening shows the saved correction, not the original OCR value");

  openStreamViaClick("TEST-003"); // no OCR record at all
  assert.match(doc.getElementById("archiveDialogBody").innerHTML, /No OCR reading exists/,
    "a stream with no OCR record still opens the workbench without crashing");

  openStreamViaClick("TEST-004"); // already PUBLISHED / verified
  const publishedBody = doc.getElementById("archiveDialogBody").innerHTML;
  assert.ok(!publishedBody.includes("<input") && publishedBody.includes("40"),
    "a PUBLISHED (already-verified) stream shows read-only figures, no editable inputs");

  // --- Save & mark reviewed: green cell, tally, auto-advance ------------
  assert.equal(doc.getElementById("reviewProgress").hidden, false, "tally banner is visible even before the first confirmation");
  assert.match(doc.getElementById("reviewProgress").textContent, /0 \/ 4/, "top tally starts at 0 of 4");

  openStreamViaClick("TEST-001"); // already has a saved draft (UDA corrected to 245) from earlier in this run
  assert.equal(doc.querySelector('[data-stream-key="TEST-001"]').className.includes("locally-confirmed"), false,
    "a stream with only an unconfirmed draft is not yet green");
  assert.equal(doc.getElementById("rfConfirm").disabled, true,
    "confirmation is blocked while the corrected candidate sum conflicts with the stated totals");
  const setInput = (id, value) => {
    const input = doc.getElementById(id);
    input.value = value;
    input.dispatchEvent(new window.Event("input", { bubbles: true }));
  };
  setInput("rf-valid", "265");
  setInput("rf-cast", "266");
  setInput("rf-reviewer", "Test Reviewer");
  assert.match(doc.getElementById("rfHumanChecks").textContent, /V01 PASS/,
    "human-entry checks update from the edited values rather than showing only raw OCR checks");
  assert.equal(doc.getElementById("rfConfirm").disabled, false,
    "a complete row with passing arithmetic and a reviewer can be saved");
  doc.getElementById("rfConfirm").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 10));

  const afterConfirm = JSON.parse(window.localStorage.getItem("olkalou-archive-drafts:banissa-2025") || "{}");
  assert.ok(afterConfirm["TEST-001"].confirmed_at, "clicking Save & mark reviewed stamps confirmed_at");
  assert.match(doc.getElementById("archiveDialogBody").innerHTML, /Confirmed/, "confirming a fresh stream shows immediate feedback text (via the auto-advanced dialog or the status line)");

  assert.equal(doc.getElementById("reviewProgress").hidden, false, "tally banner appears once at least one stream is confirmed");
  assert.match(doc.getElementById("reviewProgress").textContent, /1 \/ 4/, "tally shows 1 of 4 streams confirmed");
  assert.match(doc.getElementById("reviewProgress").textContent, /UDA 245/, "tally reflects the corrected value (245), not the raw OCR reading (30)");
  assert.match(doc.getElementById("reviewProgress").textContent, /Provisional browser tally/, "tally carries the same disclaimer discipline as the rest of the review workbench");
  assert.match(doc.getElementById("reviewProgress").textContent, /265 valid/, "top tally includes total valid votes from confirmed rows");

  await new Promise((r) => setTimeout(r, 500)); // let the 450ms auto-advance timer fire
  const cellTest001 = doc.querySelector('[data-stream-key="TEST-001"]');
  assert.ok(cellTest001.className.includes("locally-confirmed"), "the grid cell for the confirmed stream turns green");

  // Auto-advance should have opened the next unconfirmed, non-PUBLISHED stream (TEST-002).
  assert.match(doc.getElementById("archiveDialogBody").innerHTML, /Test School B/,
    "confirming auto-advances to the next unconfirmed stream instead of leaving the reviewer to hunt for it");

  // Editing an already-confirmed stream invalidates that confirmation until re-saved.
  openStreamViaClick("TEST-001");
  const voteAAgain = doc.getElementById("rf-vote-UDA");
  voteAAgain.value = "246";
  voteAAgain.dispatchEvent(new window.Event("input", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 10));
  const afterEdit = JSON.parse(window.localStorage.getItem("olkalou-archive-drafts:banissa-2025") || "{}");
  assert.equal(afterEdit["TEST-001"].confirmed_at, undefined, "editing a confirmed row clears its reviewed stamp until it is re-confirmed");
  assert.equal(Number(afterEdit["TEST-001"].votes.UDA), 246, "the edit itself still applies as a draft");
  assert.equal(doc.querySelector('[data-stream-key="TEST-001"]').className.includes("locally-confirmed"), false,
    "the polling-centre cell leaves green state immediately after an unconfirmed edit");

  let capturedCsv = null;
  window.URL.createObjectURL = (blob) => { capturedCsv = blob; return "blob:test"; };
  window.URL.revokeObjectURL = () => {};
  doc.getElementById("draftDownload").dispatchEvent(new window.MouseEvent("click", { bubbles: true }));
  assert.ok(capturedCsv && capturedCsv.type.includes("text/csv"), "the download button builds a CSV Blob");
  assert.ok(capturedBlobParts && capturedBlobParts.length === 1, "the Blob is constructed from a single string part");

  const csvText = String(capturedBlobParts[0]).replace(/^\ufeff/, ""); // strip the BOM prefix added for Excel compatibility
  assert.ok(
    csvText.includes("stream_key,reported_at,form_url,verification,registered_form,UDA,UPA,rejected,po_total_valid,total_cast_form,reviewer_a,reviewer_b,notes"),
    "exported CSV header matches results_template.csv's real column order exactly"
  );
  assert.ok(csvText.includes("TEST-001") && csvText.includes(",246,20,"),
    "exported CSV contains the latest correction (246, entered after confirming), not the raw OCR value (30)");
  assert.ok(!csvText.includes("TEST-002") && !csvText.includes("TEST-003"),
    "exported CSV omits streams with no draft entered at all");

  console.log("All review-workbench execution tests passed.");
  process.exit(0); // archive.js's own setInterval(..., 60000) auto-refresh timer
  // would otherwise keep this process alive indefinitely -- appropriate in a
  // real browser tab, not in a test runner that needs to actually terminate.
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
