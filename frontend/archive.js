(() => {
  const config = window.OLKALOU_CONFIG || {};
  const catalogUrl = config.archiveCatalogUrl || "../data/public/elections/catalog.json";
  const updateWorkflowUrl = config.archiveUpdateWorkflowUrl || "https://github.com/dansamuka/2_Elections_tallying_educational/actions/workflows/sync-historical-forms.yml";
  const syncMinutes = Number(config.archiveSyncMinutes || 5);
  const $ = (id) => document.getElementById(id);
  const number = (value) => value == null ? "—" : new Intl.NumberFormat("en-KE").format(Number(value));
  const percent = (value, digits = 1) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  let catalog = null;
  let payload = null;
  let replayTimer = null;
  let replayPosition = null;

  // ---------------------------------------------------------------------
  // Review workbench: pure CSV/draft logic (execution-tested end to end,
  // including real DOM interaction and localStorage, in
  // tests/frontend/test_review_workbench.js against this exact code).
  // Everything here is client-side only -- typing into these fields never
  // sends anything anywhere. It only prepares a CSV in the same shape
  // import_verified_results() already expects, for whoever runs
  // `archive-import` to actually verify and publish. See the OCR prefill
  // banner text rendered in openStream() for the same point made to readers.
  // ---------------------------------------------------------------------
  function csvEscape(value) {
    const str = String(value ?? "");
    if (/[",\n\r]/.test(str)) return `"${str.replace(/"/g, '""')}"`;
    return str;
  }
  function csvHeader(candidateIds) {
    return ["stream_key","reported_at","form_url","verification","registered_form",...candidateIds,"rejected","po_total_valid","total_cast_form","reviewer_a","reviewer_b","notes"].join(",");
  }
  function buildCsvRow(candidateIds, draft) {
    const cols = [
      draft.stream_key || "", draft.reported_at || "", draft.form_url || "", draft.verification || "HUMAN",
      draft.registered_form ?? "", ...candidateIds.map((id) => draft.votes?.[id] ?? ""),
      draft.rejected ?? "", draft.po_total_valid ?? "", draft.total_cast_form ?? "",
      draft.reviewer_a || "", draft.reviewer_b || "", draft.notes || "",
    ];
    return cols.map(csvEscape).join(",");
  }
  function isDraftFilled(candidateIds, draft) {
    return candidateIds.some((id) => draft?.votes?.[id] !== undefined && draft.votes[id] !== null && draft.votes[id] !== "");
  }
  function buildDraftCsv(candidateIds, drafts) {
    const rows = Object.values(drafts || {}).filter((d) => isDraftFilled(candidateIds, d));
    return [csvHeader(candidateIds), ...rows.map((d) => buildCsvRow(candidateIds, d))].join("\r\n") + "\r\n";
  }
  function mergeDraft(existing, patch) {
    return {...(existing || {}), ...patch, votes: {...(existing?.votes || {}), ...(patch.votes || {})}};
  }
  function draftOrPrefill(stream, ocrPrefill, savedDraft) {
    const base = {
      stream_key: stream.stream_key, form_url: stream.form_url || "",
      registered_form: ocrPrefill?.registered ?? stream.registered ?? "",
      votes: {...(ocrPrefill?.votes || {})},
      rejected: ocrPrefill?.rejected ?? "", po_total_valid: ocrPrefill?.total_valid ?? "",
      total_cast_form: ocrPrefill?.total_cast ?? "", verification: "HUMAN",
      reviewer_a: "", reviewer_b: "", notes: "",
    };
    return savedDraft ? mergeDraft(base, savedDraft) : base;
  }

  // Drafts persist in this browser's localStorage only, namespaced per
  // election so switching the picker never mixes data between elections.
  // This is a real deployed site (not a Claude-artifact preview), so
  // localStorage is the right tool here -- it survives a page reload,
  // which matters if reviewing 81 streams takes more than one sitting.
  function draftStorageKey(electionId) { return `olkalou-archive-drafts:${electionId}`; }
  function loadAllDrafts(electionId) {
    try { return JSON.parse(localStorage.getItem(draftStorageKey(electionId)) || "{}"); }
    catch { return {}; }
  }
  function saveDraft(electionId, streamKey, draft) {
    const all = loadAllDrafts(electionId);
    all[streamKey] = draft;
    localStorage.setItem(draftStorageKey(electionId), JSON.stringify(all));
    return all;
  }
  function clearDraft(electionId, streamKey) {
    const all = loadAllDrafts(electionId);
    delete all[streamKey];
    localStorage.setItem(draftStorageKey(electionId), JSON.stringify(all));
    return all;
  }
  function clearAllDrafts(electionId) {
    localStorage.removeItem(draftStorageKey(electionId));
  }
  function updateDraftCount() {
    if (!payload) return;
    const ids = (payload.candidates || []).map((c) => c.id);
    const all = loadAllDrafts(payload.election_id);
    const filled = Object.values(all).filter((d) => isDraftFilled(ids, d)).length;
    const benchmark = Boolean(payload.reference?.benchmark_only);
    const suffix = benchmark
      ? "saved locally for OCR accuracy validation · benchmark rows never publish a result"
      : "drafted in this browser · nothing is published until you run archive-import";
    $("draftCount").textContent = `${filled} stream${filled === 1 ? "" : "s"} ${suffix}`;
    renderReviewProgress();
  }

  function isConfirmed(draft) {
    return Boolean(draft && draft.confirmed_at);
  }

  function renderReviewProgress() {
    if (!payload) return;
    const el = $("reviewProgress");
    const candidateList = payload.candidates || [];
    const ids = candidateList.map((c) => c.id);
    const all = loadAllDrafts(payload.election_id);
    const confirmed = Object.values(all).filter(isConfirmed);
    const total = payload.coverage?.streams_total || 0;
    const benchmark = Boolean(payload.reference?.benchmark_only);
    el.hidden = false;
    const totals = {};
    ids.forEach((id) => { totals[id] = 0; });
    confirmed.forEach((d) => ids.forEach((id) => { totals[id] += Number(d.votes?.[id] || 0); }));
    const configuredSubtotal = ids.reduce((sum, id) => sum + Number(totals[id] || 0), 0);
    const statedValid = confirmed.reduce((sum, d) => sum + Number(d.po_total_valid || 0), 0);
    const totalValid = benchmark ? statedValid : configuredSubtotal;
    const breakdown = candidateList.map((c) => `${escapeHtml(c.abbr)} ${number(totals[c.id])}`).join(" · ");
    if (benchmark) {
      el.innerHTML = `<span><strong>${confirmed.length} / ${number(total)}</strong> OCR benchmark streams reviewed · <strong>${number(totalValid)} PO-stated valid</strong>${breakdown ? ` — configured-field subtotal: ${breakdown}` : ""}</span><span class="rp-note">Accuracy-validation truth set only. The candidate roster and stream register are not yet certified, so these figures are not a constituency tally and cannot be published.</span>`;
    } else {
      el.innerHTML = `<span><strong>${confirmed.length} / ${number(total)}</strong> human-reviewed streams · <strong>${number(totalValid)} valid</strong>${breakdown ? ` — ${breakdown}` : ""}</span><span class="rp-note">Provisional browser tally only. It reflects rows you checked and explicitly saved here; archive-import and independent verification are still required for publication.</span>`;
    }
  }

  async function fetchJson(url) {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, {cache: "no-store"});
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
  }

  function resolveDataUrl(entry) {
    return entry.data_url || `../data/public/elections/${entry.id}.json`;
  }

  async function init() {
    $("archiveUpdateNow").href = updateWorkflowUrl;
    $("archiveUpdateNow").addEventListener("click", () => {
      $("archiveUpdateNow").textContent = "Open GitHub Actions ↗";
    });
    $("archiveRefresh").addEventListener("click", async () => {
      if (!catalog) return;
      $("archiveRefresh").disabled = true;
      $("archiveRefresh").textContent = "Refreshing…";
      try {
        await loadElection($("electionSelect").value, false);
      } finally {
        $("archiveRefresh").disabled = false;
        $("archiveRefresh").textContent = "Refresh data";
      }
    });
    try {
      catalog = await fetchJson(catalogUrl);
      if (catalog.schema !== "kenya.election.catalog.v1") throw new Error("Unexpected archive catalog schema");
      const select = $("electionSelect");
      select.innerHTML = catalog.elections.map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.label)}</option>`).join("");
      const requested = new URLSearchParams(location.search).get("election");
      select.value = catalog.elections.some(row => row.id === requested) ? requested : catalog.default;
      select.addEventListener("change", () => loadElection(select.value, true));
      await loadElection(select.value, false);
    } catch (error) {
      console.error(error);
      $("archiveStatus").textContent = "The historical-election catalog could not be loaded.";
    }
  }

  async function loadElection(electionId, updateUrl) {
    stopReplay();
    const entry = catalog.elections.find(row => row.id === electionId);
    if (!entry) return;
    payload = await fetchJson(resolveDataUrl(entry));
    if (payload.schema !== "kenya.election.archive.v1") throw new Error("Unexpected historical payload schema");
    replayPosition = payload.archive?.replay_available ? payload.archive.replay_events.length : null;
    if (updateUrl) history.replaceState({}, "", `${location.pathname}?election=${encodeURIComponent(electionId)}`);
    render();
  }

  function render() {
    const election = payload.election || {};
    const archive = payload.archive || {};
    const coverage = payload.coverage || {};
    const benchmark = Boolean(payload.reference?.benchmark_only);
    $("archiveEyebrow").textContent = `${election.constituency || "ELECTION"} · CONSTITUENCY ${election.code || "—"} · ${election.date || "—"}`;
    $("archiveTitle").textContent = election.title || `${election.constituency || "Election"} archive`;
    $("archiveUpdated").textContent = new Date(payload.generated_at).toLocaleString("en-KE", {dateStyle:"medium", timeStyle:"short"});
    $("archiveSourceState").textContent = payload.reference?.complete ? "Certified register loaded" : "Reference incomplete";
    const sync = archive.portal_sync || {};
    const lastSync = sync.last_completed_at ? new Date(sync.last_completed_at).toLocaleString("en-KE", {dateStyle:"medium", timeStyle:"short"}) : null;
    $("archiveSyncState").textContent = lastSync
      ? `Portal sync ${sync.state || "UNKNOWN"} · ${lastSync}`
      : `Portal sync not yet run · scheduled every ${syncMinutes} min`;
    $("archiveStreams").textContent = `${coverage.stream_rows_loaded ?? coverage.streams_total ?? 0}/${coverage.streams_total || 0}`;
    // Honest number, matching what every other stat on this page (and the
    // sidebar readiness list) already shows -- this used to take
    // Math.max(forms_archived, portal_downloaded), which is why the top of
    // the page could say "81/81" while the readiness list further down said
    // "72/81" for what reads as the same thing. IEBC reporting 100% only
    // means all 81 forms were PUBLISHED on their portal; it says nothing
    // about how many of those this pipeline has successfully downloaded,
    // inventoried, OCR'd, and matched to a specific stream -- see the gap
    // note below, which explains exactly where any shortfall is.
    const formsArchived = Number(archive.forms_archived || 0);
    $("archiveForms").textContent = `${formsArchived}/${archive.forms_expected || coverage.streams_total || 0}`;
    $("archiveTranscribed").textContent = `${archive.stream_results_transcribed || 0}/${coverage.streams_total || 0}`;
    $("archiveOcrReview").textContent = `${archive.ocr?.review_rows || 0}`;
    $("archiveRegistered").textContent = benchmark && !coverage.registered_total ? "PENDING" : number(coverage.registered_total);
    $("archiveReplayLabel").textContent = benchmark ? "OCR BENCHMARK" : "REPLAY";
    $("archiveReplayState").textContent = benchmark
      ? (Number(archive.ocr?.review_rows || 0) > 0 ? "REVIEW READY" : "AWAITING FORMS")
      : (archive.replay_available ? "READY" : "WITHHELD");
    $("archiveValid").textContent = benchmark ? "truth set" : `${number(payload.totals?.valid_votes)} valid`;
    renderGapNote(archive, coverage);
    $("archiveStatus").textContent = benchmark
      ? `${coverage.stream_rows_loaded || 0} of ${coverage.streams_total || 0} Malava stream identities loaded; ${formsArchived} forms archived and ${archive.ocr?.review_rows || 0} OCR rows ready for human validation. Placeholder boxes remain visible until the first portal sync hydrates the real polling-centre roster.`
      : archive.stream_results_complete
        ? "All stream results are source-linked and the count can be replayed."
        : payload.mode === "LIVE"
          ? `${formsArchived} of ${archive.forms_expected || coverage.streams_total || 0} IEBC forms archived; ${archive.ocr?.review_rows || 0} OCR-prefilled rows await human review; ${archive.stream_results_transcribed || 0} stream tallies are independently verified. No OCR figure enters the live tally automatically.`
          : `${formsArchived} of ${archive.forms_expected || coverage.streams_total || 0} forms archived; ${archive.ocr?.review_rows || 0} OCR-prefilled rows awaiting human review; ${archive.stream_results_transcribed || 0} stream tallies independently transcribed. Declared constituency totals remain separate from the incomplete Form 35A sum.`;
    renderCandidates(payload.candidates || []);
    renderDeclaration();
    renderReplay();
    renderSnapshot();
    renderReadiness();
    renderSources();
    populateFilters();
    renderTable();
    updateDraftCount();
  }

  function currentSnapshot() {
    if (!payload.archive?.replay_available || replayPosition == null) return payload;
    const events = payload.archive.replay_events.slice(0, replayPosition);
    const visible = new Set(events.map(event => event.stream_key));
    const streams = payload.streams.map(stream => visible.has(stream.stream_key) ? stream : {...stream, state:"ARCHIVED", votes:{}, rejected:null, valid:null, cast:null, turnout:null});
    const totals = Object.fromEntries((payload.candidates || []).map(candidate => [candidate.id, 0]));
    let validVotes = 0;
    streams.filter(stream => stream.state === "PUBLISHED").forEach(stream => {
      Object.entries(stream.votes || {}).forEach(([id, value]) => { totals[id] = (totals[id] || 0) + Number(value); });
      validVotes += Number(stream.valid || 0);
    });
    const candidates = payload.candidates.map(candidate => ({...candidate, votes:totals[candidate.id] || 0, share:validVotes ? (totals[candidate.id] || 0) / validVotes : 0}));
    return {...payload, streams, candidates, totals:{...payload.totals, valid_votes:validVotes}, coverage:{...payload.coverage, published:visible.size}};
  }

  function renderSnapshot() {
    const snapshot = currentSnapshot();
    renderCandidates(snapshot.candidates || []);
    renderGrid(snapshot);
    renderTable(snapshot.streams || []);
    const total = payload.archive?.replay_events?.length || 0;
    if (payload.archive?.replay_available) {
      $("replayPosition").textContent = `${replayPosition} / ${total}`;
      $("archiveGridCounter").textContent = `${snapshot.coverage.published}/${snapshot.coverage.streams_total}`;
    } else {
      const archivedSourceCount = Number(payload.archive?.forms_archived || 0);
      const totalStreams = Number(payload.coverage?.streams_total || 0);
      const rosterLoaded = Number(payload.coverage?.stream_rows_loaded ?? (payload.streams || []).length);
      $("archiveGridCounter").textContent = payload.reference?.benchmark_only && rosterLoaded === 0
        ? `0/${totalStreams} roster pending`
        : `${archivedSourceCount}/${totalStreams} forms`;
    }
  }

  function renderCandidates(candidates) {
    const knownVotes = candidates.filter(candidate => candidate.votes != null).map(candidate => Number(candidate.votes));
    const maxVotes = Math.max(1, ...knownVotes);
    $("archiveCandidates").innerHTML = candidates.map((candidate, index) => {
      const width = candidate.votes == null ? 0 : Number(candidate.votes) / maxVotes * 100;
      return `<article class="candidate-row">
        <div class="candidate-meta"><span class="candidate-name">${index + 1}. ${escapeHtml(candidate.name)}</span><span class="party-chip">${escapeHtml(candidate.abbr)}</span></div>
        <div><span class="candidate-votes">${number(candidate.votes)}</span><span class="candidate-share">${percent(candidate.share)}</span></div>
        <div class="candidate-track"><div class="candidate-fill" style="width:${width}%;background:${escapeHtml(candidate.colour)}"></div></div>
      </article>`;
    }).join("");
  }

  function renderDeclaration() {
    const official = payload.official_declaration || {};
    if (payload.reference?.benchmark_only) {
      $("declarationNote").innerHTML = `<p class="eyebrow">OCR VALIDATION DATASET</p>
        <p><strong>No constituency result is being asserted here.</strong> Candidate fields and PO control totals are shown only so human-reviewed rows can be compared with the OCR output.</p>
        <p class="microcopy">Benchmark source state: <strong>${escapeHtml(payload.archive?.tally_source || "NO_VERIFIED_TALLY")}</strong>. ${escapeHtml(payload.archive?.methodology_note || "")}</p>`;
      return;
    }
    const winner = (payload.candidates || []).find(candidate => candidate.id === official.winner_id);
    $("declarationNote").innerHTML = `<p class="eyebrow">OFFICIAL DECLARATION</p>
      <p><strong>${escapeHtml(winner?.name || official.winner_id || "—")}</strong> was gazetted with <span class="numeric">${number(official.winner_votes)}</span> votes.</p>
      <p class="microcopy">Dashboard tally source: <strong>${escapeHtml(payload.archive?.tally_source || "UNKNOWN")}</strong>. ${escapeHtml(payload.archive?.methodology_note || "")}</p>`;
  }

  function renderReplay() {
    const available = Boolean(payload.archive?.replay_available);
    const benchmark = Boolean(payload.reference?.benchmark_only);
    $("replayControls").hidden = !available;
    $("replayUnavailable").hidden = available;
    if (benchmark) {
      $("replayControls").hidden = true;
      $("replayUnavailable").hidden = false;
      const rowsLoaded = Number(payload.coverage?.stream_rows_loaded ?? (payload.streams || []).length);
      const reviewRows = Number(payload.archive?.ocr?.review_rows || 0);
      $("replayUnavailable").innerHTML = `<strong>OCR benchmark mode</strong><p>This module is a handwriting-accuracy test, not an election replay. ${rowsLoaded ? `${number(rowsLoaded)} stream identities are loaded and ${number(reviewRows)} OCR rows are ready for checking.` : `The first IEBC portal sync must hydrate all ${number(payload.coverage?.streams_total)} stream identities before the boxes become reviewable.`}</p><p>After checking a form, save the row: its box turns green and it enters the browser-local benchmark truth tally above.</p>`;
      return;
    }
    if (!available) {
      $("replayUnavailable").innerHTML = `<strong>Replay withheld</strong><p>A genuine replay needs all ${number(payload.coverage?.streams_total)} stream-level Form 35A totals and reporting timestamps. The engine will not invent either.</p><code>python -m olkalou_engine.cli --root . archive-run ${escapeHtml(payload.election_id)}</code><code>python -m olkalou_engine.cli --root . archive-import ${escapeHtml(payload.election_id)} data/elections/${escapeHtml(payload.election_id)}/results_template.csv</code>`;
      return;
    }
    const total = payload.archive.replay_events.length;
    $("replayRange").max = String(total);
    $("replayRange").value = String(replayPosition ?? total);
    $("replayRange").oninput = (event) => { replayPosition = Number(event.target.value); renderSnapshot(); };
    $("replayPlay").onclick = toggleReplay;
    $("replayReset").onclick = () => { stopReplay(); replayPosition = 0; $("replayRange").value = "0"; renderSnapshot(); };
  }

  function toggleReplay() {
    if (replayTimer) { stopReplay(); return; }
    $("replayPlay").textContent = "Pause";
    if (replayPosition >= payload.archive.replay_events.length) replayPosition = 0;
    replayTimer = setInterval(() => {
      replayPosition += 1;
      $("replayRange").value = String(replayPosition);
      renderSnapshot();
      if (replayPosition >= payload.archive.replay_events.length) stopReplay();
    }, 450);
  }

  function stopReplay() {
    if (replayTimer) clearInterval(replayTimer);
    replayTimer = null;
    if ($("replayPlay")) $("replayPlay").textContent = "Play";
  }

  function renderGrid(snapshot) {
    const streams = snapshot.streams || [];
    const total = Number(snapshot.coverage?.streams_total || streams.length);
    $("archiveGridTitle").textContent = `${total}-stream grid`;
    if (!streams.length && total > 0) {
      const benchmark = Boolean(payload.reference?.benchmark_only);
      const label = benchmark ? "PORTAL ROSTER PENDING" : "STREAM REGISTER PENDING";
      const cells = Array.from({length: total}, (_, index) =>
        `<button type="button" class="stream-cell roster-placeholder" disabled title="Stream ${index + 1}: awaiting portal roster" aria-label="Stream ${index + 1} awaiting portal roster"></button>`
      ).join("");
      $("archiveStreamGrid").innerHTML = `<section class="ward-block pending-roster"><h3><span>${label}</span><span>0/${total}</span></h3><p class="grid-empty-note">${benchmark ? `The IEBC reports ${number(total)} Malava Form 35A assignments. These placeholders will be replaced with named, clickable polling-centre boxes when the first sync completes.` : "Named stream boxes will appear when the register is loaded."}</p><div class="ward-cells">${cells}</div></section>`;
      return;
    }

    const byWard = new Map();
    streams.forEach(stream => {
      if (!byWard.has(stream.ward)) byWard.set(stream.ward, []);
      byWard.get(stream.ward).push(stream);
    });
    const candidateMap = new Map((snapshot.candidates || []).map(candidate => [candidate.id, candidate]));
    const drafts = payload ? loadAllDrafts(payload.election_id) : {};
    $("archiveStreamGrid").innerHTML = [...byWard.entries()].map(([ward, wardStreams]) => {
      const completed = wardStreams.filter(stream => stream.state === "PUBLISHED" || isConfirmed(drafts[stream.stream_key])).length;
      return `<section class="ward-block"><h3><span>${escapeHtml(ward)}</span><span>${completed}/${wardStreams.length}</span></h3><div class="ward-cells">${wardStreams.map(stream => archiveCell(stream, candidateMap, drafts[stream.stream_key])).join("")}</div></section>`;
    }).join("");
    document.querySelectorAll(".archive-stream-cell").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function archiveCell(stream, candidateMap, draft) {
    let className = "stream-cell archive-stream-cell";
    let style = "";
    if (stream.state === "PUBLISHED") {
      className += " published";
      const votes = Object.entries(stream.votes || {}).sort((a,b) => Number(b[1]) - Number(a[1]));
      const leader = votes[0];
      const colour = candidateMap.get(leader?.[0])?.colour || "#3FA76B";
      style = `background:${colour};opacity:.85`;
    } else if (stream.state === "OCR_REVIEW") className += " ocr-review";
    else if (stream.state === "ARCHIVED") className += " archived";
    else className += " reference-only";
    // Locally-confirmed overrides the server-reported visual state (never
    // PUBLISHED, which stays candidate-coloured) -- a distinct flat green so
    // it's never mistaken for an actually-imported, verified result.
    if (stream.state !== "PUBLISHED" && isConfirmed(draft)) {
      className += " locally-confirmed";
      style = "";
    }
    return `<button type="button" class="${className}" style="${style}" data-stream-key="${escapeHtml(stream.stream_key)}" title="${escapeHtml(stream.station_name)} · ${escapeHtml(stream.state)}" aria-label="${escapeHtml(stream.station_name)} stream ${stream.stream_no}: ${escapeHtml(stream.state)}"></button>`;
  }

  function renderGapNote(archive, coverage) {
    const note = $("archiveGapNote");
    const expected = archive.forms_expected || coverage.streams_total || 0;
    const archived = Number(archive.forms_archived || 0);
    const rowsLoaded = Number(coverage.stream_rows_loaded ?? (payload.streams || []).length);
    const syncState = String(archive.portal_sync?.state || "NEVER_RUN");
    if (payload.reference?.benchmark_only && rowsLoaded === 0 && syncState === "NEVER_RUN") {
      note.hidden = false;
      note.innerHTML = `<strong>Malava setup is waiting for its first portal run.</strong> IEBC currently reports ${number(expected)} of ${number(expected)} Form 35As. The page is showing ${number(expected)} disabled placeholders so the expected coverage is visible; the scheduled sync will replace them with real polling-centre identities, archived PDFs and OCR review rows.`;
      return;
    }
    if (archived >= expected) { note.hidden = true; return; }

    const downloaded = Number(archive.portal_downloaded || 0);
    const unmatchedPortal = Number(archive.portal_unmatched || 0);
    const ocr = archive.ocr || {};
    const documentsTotal = Number(ocr.documents_total || 0);
    const uniqueFiles = Number(archive.portal_unique_files ?? documentsTotal);
    const duplicateAssignments = Number(archive.portal_duplicate_assignments ?? Math.max(0, downloaded - uniqueFiles));
    const failedDownloads = Number(archive.portal_failed_downloads || 0);
    const streamsMatched = Number(ocr.streams_matched || 0);
    const funnel = [
      ["IEBC portal", expected],
      ["Downloaded", downloaded],
      ["Unique source PDFs", uniqueFiles],
      ["Matched to a stream", Math.max(streamsMatched, archived)],
    ].map(([label, value]) => `${escapeHtml(label)} ${number(value)}`).join(" → ");

    note.hidden = false;
    note.innerHTML = `<strong>Why this isn't 100% yet even though IEBC's portal is:</strong> ${funnel} (of ${number(expected)} expected).` +
      (duplicateAssignments ? ` ${number(duplicateAssignments)} portal assignment${duplicateAssignments === 1 ? "" : "s"} ${duplicateAssignments === 1 ? "points" : "point"} to duplicate PDF content, so assignment count and unique-document count differ.` : "") +
      (failedDownloads ? ` ${number(failedDownloads)} form download${failedDownloads === 1 ? " is" : "s are"} still missing and will be retried even when the portal index is unchanged.` : "") +
      (unmatchedPortal ? ` ${number(unmatchedPortal)} downloaded file${unmatchedPortal === 1 ? "" : "s"} could not be matched to a specific stream at the portal stage.` : "") +
      ` Re-running the sync (Update now, above) retries missing files automatically; unmatched or duplicate forms still need human inspection.`;
  }

  function renderReadiness() {
    const archive = payload.archive || {};
    const total = payload.coverage?.streams_total || 0;
    const expected = archive.forms_expected || total;
    const ocr = archive.ocr || {};
    const sync = archive.portal_sync || {};
    const documentsTotal = Number(ocr.documents_total || 0);
    const streamsMatched = Number(ocr.streams_matched || 0);
    const checks = [
      ["Scheduled portal sync", sync.state && sync.state !== "NEVER_RUN" ? 1 : 0, 1],
      ["Portal links discovered", archive.portal_discovered || 0, expected],
      ["Portal form assignments downloaded", archive.portal_downloaded || 0, expected],
      ["Unique source PDFs", archive.portal_unique_files ?? documentsTotal, expected],
      ["Duplicate portal assignments", archive.portal_duplicate_assignments ?? Math.max(0, Number(archive.portal_downloaded || 0) - documentsTotal), 0],
      ["Failed or missing downloads", archive.portal_failed_downloads || 0, 0],
      ["Portal downloads unmatched to a stream", archive.portal_unmatched || 0, 0],
      ["Certified stream register", payload.reference?.complete ? total : 0, total],
      ["Source documents inventoried", documentsTotal, expected],
      ["OCR pages processed", ocr.pages_processed || 0, ocr.pages_total || 0],
      ["Form 35A streams matched", streamsMatched, expected],
      ["OCR-read but unmatched to a stream", Math.max(0, documentsTotal - streamsMatched), 0],
      ["OCR rows ready for review", ocr.review_rows || 0, total],
      ["IEBC forms archived", archive.forms_archived || 0, expected],
      ["Independent transcription", archive.stream_results_transcribed || 0, total],
      ["Replay timestamps", archive.replay_available ? total : 0, total],
    ];
    // The two "unmatched" rows show a raw count, not a fraction -- max=0
    // signals renderReadiness to print "N" instead of "N / 0", which would
    // otherwise misleadingly look like every unmatched item is itself a
    // shortfall against a target of zero.
    $("archiveReadiness").innerHTML = checks.map(([label,value,max]) =>
      `<div class="metric"><span>${escapeHtml(label)}</span><strong>${max === 0 ? number(value) : `${number(value)} / ${number(max)}`}</strong></div>`
    ).join("");
  }

  function populateFilters() {
    const streams = payload.streams || [];
    const ward = $("archiveWard");
    const state = $("archiveState");
    ward.innerHTML = `<option value="">All wards</option>` + [...new Set(streams.map(row => row.ward))].sort().map(value => `<option>${escapeHtml(value)}</option>`).join("");
    state.innerHTML = `<option value="">All states</option>` + [...new Set(streams.map(row => row.state))].sort().map(value => `<option>${escapeHtml(value)}</option>`).join("");
  }

  function renderTable(streams = currentSnapshot().streams || []) {
    const ward = $("archiveWard").value;
    const state = $("archiveState").value;
    const search = $("archiveSearch").value.trim().toLowerCase();
    const filtered = streams.filter(row => (!ward || row.ward === ward) && (!state || row.state === state) && (!search || `${row.stream_key} ${row.station_name}`.toLowerCase().includes(search)));
    const drafts = payload ? loadAllDrafts(payload.election_id) : {};
    if (!filtered.length && payload.reference?.benchmark_only && !(payload.streams || []).length) {
      $("archiveTable").innerHTML = `<tr><td colspan="6" class="muted">Malava's ${number(payload.coverage?.streams_total || 0)} stream rows are awaiting the first IEBC portal sync. Placeholder boxes above are intentionally not clickable until a source Form 35A identity exists.</td></tr>`;
      return;
    }
    $("archiveTable").innerHTML = filtered.map(stream => `<tr>
      <td><button type="button" class="text-button archive-table-open" data-stream-key="${escapeHtml(stream.stream_key)}">${escapeHtml(stream.stream_key)}</button><br><span class="muted">${escapeHtml(stream.station_name)}</span></td>
      <td>${escapeHtml(stream.ward)}</td>
      <td><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span>${isConfirmed(drafts[stream.stream_key]) && stream.state !== "PUBLISHED" ? `<br><span class="state-badge local-reviewed-badge">HUMAN REVIEWED ✓</span>` : ""}${stream.ocr?.route ? `<br><span class="muted">${escapeHtml(stream.ocr.route)}</span>` : ""}</td>
      <td>${number(stream.registered)}</td><td>${number(stream.valid)}</td>
      <td>${stream.form_url ? `<a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Form 35A ↗</a>` : "—"}</td>
    </tr>`).join("");
    document.querySelectorAll(".archive-table-open").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function openStream(streamKey) {
    const stream = currentSnapshot().streams.find(row => row.stream_key === streamKey);
    if (!stream) return;
    const candidateList = payload.candidates || [];
    const candidateIds = candidateList.map(c => c.id);
    const candidateMap = new Map(candidateList.map(c => [c.id, c]));

    if (stream.state === "PUBLISHED") {
      // Already independently verified -- nothing to review or draft, just show it.
      const rows = Object.entries(stream.votes || {}).map(([id, value]) =>
        `<tr><td>${escapeHtml(candidateMap.get(id)?.name || id)}</td><td class="numeric">${number(value)}</td></tr>`).join("");
      $("archiveDialogBody").innerHTML = `<p class="eyebrow">${escapeHtml(stream.stream_key)} · ${escapeHtml(stream.ward)}</p><h2>${escapeHtml(stream.station_name)}</h2>
        <p><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span></p>
        <table class="detail-table"><tbody><tr><td>Registered</td><td class="numeric">${number(stream.registered)}</td></tr>${rows}</tbody></table>
        ${stream.form_url ? `<p><a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Open archived Form 35A ↗</a></p>` : ""}`;
      $("archiveStreamDialog").showModal();
      return;
    }

    const ocr = stream.ocr || null;
    const prefill = ocr?.prefill || null;
    const savedDraft = loadAllDrafts(payload.election_id)[streamKey] || null;
    const draft = draftOrPrefill(stream, prefill, savedDraft);
    const benchmark = Boolean(payload.reference?.benchmark_only);

    const checkBadges = ocr?.checks && Object.keys(ocr.checks).length
      ? `<p class="check-label">Raw OCR checks</p><div class="ocr-checks">${Object.entries(ocr.checks).map(([code, status]) =>
          `<span class="${status === "PASS" ? "pass" : status === "FAIL" ? "fail" : "unknown"}">${escapeHtml(code)} ${escapeHtml(status)}</span>`).join("")}</div>`
      : "";

    const candidateRows = candidateList.map(c => `
      <div class="review-field-row">
        <label for="rf-vote-${escapeHtml(c.id)}">${escapeHtml(c.name)}<span class="party-chip">${escapeHtml(c.abbr)}</span></label>
        <input id="rf-vote-${escapeHtml(c.id)}" data-candidate="${escapeHtml(c.id)}" type="number" min="0" inputmode="numeric" value="${draft.votes?.[c.id] ?? ""}">
      </div>`).join("");

    $("archiveDialogBody").innerHTML = `<p class="eyebrow">${escapeHtml(stream.stream_key)} · ${escapeHtml(stream.ward)}</p><h2>${escapeHtml(stream.station_name)}</h2>
      <p><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span></p>
      <div class="dialog-grid">
        <div>
          ${stream.form_url
            ? `<iframe class="form-frame" src="${escapeHtml(stream.form_url)}" title="Scanned Form 35A for ${escapeHtml(stream.station_name)}"></iframe><p><a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Open in a new tab ↗</a></p>`
            : `<p class="muted">The form has not yet been archived by this repository.</p>`}
        </div>
        <div>
          ${benchmark ? `<div class="ocr-prefill-banner"><span><strong>OCR VALIDATION BENCHMARK.</strong> The configured candidate list is provisional. Review the named fields and the PO control totals against the scan; V01 is intentionally not run and nothing here can publish a constituency result.</span></div>` : ""}
          ${ocr ? `<div class="ocr-prefill-banner"><span>OCR prefill: <strong>${escapeHtml(ocr.route || "REVIEW")}</strong> · confidence ${ocr.confidence == null ? "—" : percent(ocr.confidence)}. ${prefill ? "Figures below are the raw OCR reading -- check them against the form on the left before saving." : "No numeric fields were read from this page -- fill in from the form yourself."}</span></div>${checkBadges}`
            : `<p class="muted">No OCR reading exists for this stream yet.</p>`}
          <div class="review-field-row control"><label for="rf-registered">Registered (on form)</label><input id="rf-registered" type="number" min="0" value="${draft.registered_form ?? ""}"></div>
          ${candidateRows}
          <div class="review-field-row control"><label for="rf-rejected">Rejected ballots</label><input id="rf-rejected" type="number" min="0" value="${draft.rejected ?? ""}"></div>
          <div class="review-field-row control"><label for="rf-valid">PO stated total valid</label><input id="rf-valid" type="number" min="0" value="${draft.po_total_valid ?? ""}"></div>
          <div class="review-field-row control"><label for="rf-cast">PO stated total cast</label><input id="rf-cast" type="number" min="0" value="${draft.total_cast_form ?? ""}"></div>
          <div class="review-arithmetic" id="rfArithmetic"></div>
          <p class="check-label">Human entry checks</p><div class="ocr-checks human-checks" id="rfHumanChecks"></div>
          <div class="review-field-row"><label for="rf-reviewer">Your name (reviewer_a)</label><input id="rf-reviewer" type="text" value="${escapeHtml(draft.reviewer_a || "")}"></div>
          <div class="review-actions">
            <button id="rfConfirm" class="primary" type="button">${benchmark ? "Save OCR benchmark review" : "Save &amp; mark reviewed"}</button>
            <button id="rfCopyRow" type="button">Copy this row as CSV</button>
            <button id="rfClear" type="button">Clear this draft</button>
          </div>
          <p class="confirm-status" id="rfConfirmStatus">${draft.confirmed_at ? `Confirmed ✓ at ${escapeHtml(new Date(draft.confirmed_at).toLocaleString("en-KE"))}. Any edit requires confirmation again.` : ""}</p>
          <p class="review-saved-note" id="rfSavedNote">${benchmark
            ? `Typing auto-saves a local draft. "Save OCR benchmark review" marks the grid cell green and adds this checked row to the benchmark tally. Download the confirmed truth CSV and run <code>measure_historical_ocr_accuracy.py</code>; this benchmark never publishes an election result.`
            : `Typing auto-saves a draft as you go. "Save &amp; mark reviewed" additionally marks this stream's grid cell green and adds it to the tally above -- neither ever publishes anything by itself. Use "Download review draft CSV" above, then <code>archive-import</code>, to actually verify and publish.`}</p>
        </div>
      </div>`;
    $("archiveStreamDialog").showModal();
    wireReviewInputs(stream, candidateIds);
  }

  function nextUnconfirmedStreamKey(afterStreamKey) {
    const drafts = loadAllDrafts(payload.election_id);
    const streams = currentSnapshot().streams || [];
    const startIndex = streams.findIndex((s) => s.stream_key === afterStreamKey);
    const ordered = [...streams.slice(startIndex + 1), ...streams.slice(0, startIndex + 1)];
    const next = ordered.find((s) => s.state !== "PUBLISHED" && !isConfirmed(drafts[s.stream_key]) && s.stream_key !== afterStreamKey);
    return next ? next.stream_key : null;
  }

  function readReviewInputs(stream, candidateIds) {
    const votes = {};
    candidateIds.forEach((id) => {
      const el = $(`rf-vote-${id}`);
      if (el && el.value !== "") votes[id] = Number(el.value);
    });
    return {
      stream_key: stream.stream_key,
      form_url: stream.form_url || "",
      registered_form: $("rf-registered")?.value ?? "",
      votes,
      rejected: $("rf-rejected")?.value ?? "",
      po_total_valid: $("rf-valid")?.value ?? "",
      total_cast_form: $("rf-cast")?.value ?? "",
      verification: "HUMAN",
      reviewer_a: $("rf-reviewer")?.value ?? "",
      reviewer_b: "",
      notes: "",
    };
  }

  function nonNegativeInteger(value) {
    if (value === "" || value === null || value === undefined) return null;
    const numeric = Number(value);
    return Number.isInteger(numeric) && numeric >= 0 ? numeric : null;
  }

  function humanReviewState(stream, candidateIds, draft) {
    const candidateListComplete = payload?.reference?.candidate_list_complete !== false;
    const voteValues = candidateIds.map((id) => nonNegativeInteger(draft.votes?.[id]));
    const registeredForm = nonNegativeInteger(draft.registered_form);
    const rejected = nonNegativeInteger(draft.rejected);
    const statedValid = nonNegativeInteger(draft.po_total_valid);
    const statedCast = nonNegativeInteger(draft.total_cast_form);
    const candidateComplete = voteValues.every((value) => value !== null);
    const candidateSum = candidateComplete ? voteValues.reduce((sum, value) => sum + value, 0) : null;
    const computedCastBase = candidateListComplete ? candidateSum : statedValid;
    const computedCast = computedCastBase !== null && rejected !== null ? computedCastBase + rejected : null;
    const checks = {
      V01: candidateListComplete && candidateSum !== null && statedValid !== null ? (candidateSum === statedValid ? "PASS" : "FAIL") : "NOT_RUN",
      V02: statedValid !== null && rejected !== null && statedCast !== null ? (statedValid + rejected === statedCast ? "PASS" : "FAIL") : "NOT_RUN",
      V03: statedCast !== null && registeredForm !== null ? (statedCast <= registeredForm ? "PASS" : "FAIL") : "NOT_RUN",
      V07: stream.registered == null || registeredForm === null ? "NOT_RUN" : (registeredForm === Number(stream.registered) ? "PASS" : "FAIL"),
    };
    const complete = candidateComplete
      && [registeredForm, rejected, statedValid, statedCast].every((value) => value !== null)
      && Boolean(String(draft.reviewer_a || "").trim());
    const valid = complete
      && (!candidateListComplete || checks.V01 === "PASS")
      && checks.V02 === "PASS"
      && checks.V03 === "PASS"
      && ["PASS", "NOT_RUN"].includes(checks.V07);
    return { checks, complete, valid, candidateSum, computedCast };
  }

  function renderHumanReviewState(stream, candidateIds) {
    const current = readReviewInputs(stream, candidateIds);
    const state = humanReviewState(stream, candidateIds, current);
    const checkBox = $("rfHumanChecks");
    if (checkBox) {
      checkBox.innerHTML = Object.entries(state.checks).map(([code, status]) =>
        `<span class="${status === "PASS" ? "pass" : status === "FAIL" ? "fail" : "unknown"}">${escapeHtml(code)} ${escapeHtml(status)}</span>`
      ).join("");
    }
    const arithmetic = $("rfArithmetic");
    if (arithmetic) {
      const subtotalLabel = payload?.reference?.candidate_list_complete === false ? "Configured candidate subtotal" : "Candidate sum";
      arithmetic.innerHTML = `<span>${subtotalLabel} <strong>${state.candidateSum == null ? "—" : number(state.candidateSum)}</strong></span><span>Computed cast <strong>${state.computedCast == null ? "—" : number(state.computedCast)}</strong></span>`;
    }
    const button = $("rfConfirm");
    if (button) {
      button.disabled = !state.valid;
      button.title = state.valid ? "Save this checked row" : "Complete all fields, reviewer name and passing checks before saving";
    }
    return state;
  }

  function wireReviewInputs(stream, candidateIds) {
    const persist = () => {
      const current = readReviewInputs(stream, candidateIds);
      // Any edit changes the reviewed evidence. Keep the draft, but require an
      // explicit re-confirmation before the cell is green or enters the tally.
      saveDraft(payload.election_id, stream.stream_key, current);
      updateDraftCount();
      renderSnapshot();
      renderHumanReviewState(stream, candidateIds);
      const status = $("rfConfirmStatus");
      if (status) status.textContent = payload?.reference?.benchmark_only
        ? "Changes saved locally — review the scan and click Save OCR benchmark review."
        : "Changes saved as a draft — review checks and click Save & mark reviewed.";
      const note = $("rfSavedNote");
      if (note) note.textContent = `Draft saved at ${new Date().toLocaleTimeString("en-KE")}. It is not included in the green reviewed tally until you explicitly confirm it.`;
    };
    document.querySelectorAll("#archiveDialogBody input").forEach((el) => {
      el.addEventListener("input", persist);
      el.addEventListener("change", persist);
    });
    renderHumanReviewState(stream, candidateIds);
    $("rfConfirm")?.addEventListener("click", () => {
      const current = readReviewInputs(stream, candidateIds);
      const review = humanReviewState(stream, candidateIds, current);
      if (!review.valid) {
        const status = $("rfConfirmStatus");
        if (status) status.textContent = "Cannot mark reviewed: complete every field and resolve all failed arithmetic checks.";
        renderHumanReviewState(stream, candidateIds);
        return;
      }
      current.confirmed_at = new Date().toISOString();
      current.human_checks = review.checks;
      saveDraft(payload.election_id, stream.stream_key, current);
      updateDraftCount();
      renderSnapshot();
      const status = $("rfConfirmStatus");
      if (status) status.textContent = payload?.reference?.benchmark_only
        ? "Benchmark confirmed ✓ — cell marked green and checked figures added to the validation tally above."
        : "Confirmed ✓ — cell marked green and figures added to the provisional tally above.";
      const next = nextUnconfirmedStreamKey(stream.stream_key);
      setTimeout(() => {
        if (next) openStream(next); else $("archiveStreamDialog").close();
      }, 450);
    });
    $("rfCopyRow")?.addEventListener("click", async () => {
      const row = buildCsvRow(candidateIds, readReviewInputs(stream, candidateIds));
      try {
        await navigator.clipboard.writeText(row);
        $("rfCopyRow").textContent = "Copied ✓";
        setTimeout(() => { if ($("rfCopyRow")) $("rfCopyRow").textContent = "Copy this row as CSV"; }, 1800);
      } catch {
        window.prompt("Copy this CSV row:", row);
      }
    });
    $("rfClear")?.addEventListener("click", () => {
      clearDraft(payload.election_id, stream.stream_key);
      updateDraftCount();
      renderSnapshot();
      openStream(stream.stream_key);
    });
  }

  function renderSources() {
    const official = payload.official_declaration || {};
    const reference = payload.reference || {};
    const notes = official.notes || [];
    $("archiveSources").innerHTML = `<div class="source-list">
      <article><strong>Polling-stream register</strong><p>${escapeHtml(reference.register_source || "—")}</p>${reference.register_source_url ? `<a href="${escapeHtml(reference.register_source_url)}" target="_blank" rel="noopener">Open source ↗</a>` : ""}</article>
      <article><strong>Declared winning result</strong><p>${escapeHtml(official.winner_source || "—")}</p>${official.winner_source_url ? `<a href="${escapeHtml(official.winner_source_url)}" target="_blank" rel="noopener">Open source ↗</a>` : ""}</article>
      <article><strong>Runner-up total</strong><p>${escapeHtml(official.runner_up_source || "—")}</p>${official.runner_up_source_url ? `<a href="${escapeHtml(official.runner_up_source_url)}" target="_blank" rel="noopener">Open report ↗</a>` : ""}</article>
    </div>${notes.map(note => `<p class="microcopy">${escapeHtml(note)}</p>`).join("")}`;
  }

  [$("archiveWard"), $("archiveState"), $("archiveSearch")].forEach(control => control.addEventListener("input", () => payload && renderTable()));
  $("archiveDialogClose").addEventListener("click", () => $("archiveStreamDialog").close());
  $("draftDownload").addEventListener("click", () => {
    if (!payload) return;
    const ids = (payload.candidates || []).map((c) => c.id);
    const all = loadAllDrafts(payload.election_id);
    const benchmark = Boolean(payload.reference?.benchmark_only);
    const exportRows = benchmark
      ? Object.fromEntries(Object.entries(all).filter(([, draft]) => isConfirmed(draft)))
      : all;
    const csv = buildDraftCsv(ids, exportRows);
    const blob = new Blob(["\ufeff" + csv], {type: "text/csv;charset=utf-8"});
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = benchmark
      ? `${payload.election_id || "election"}-ocr-benchmark-truth.csv`
      : `${payload.election_id || "election"}-review-draft.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  });
  $("draftClear").addEventListener("click", () => {
    if (!payload) return;
    if (!confirm("Clear every drafted stream for this election in this browser? This cannot be undone.")) return;
    clearAllDrafts(payload.election_id);
    updateDraftCount();
  });
  setInterval(() => {
    if (catalog && payload && !replayTimer && !document.hidden) {
      loadElection($("electionSelect").value, false).catch(error => console.warn("Archive refresh failed", error));
    }
  }, 60000);
  init();
})();
