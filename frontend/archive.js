(() => {
  const config = window.OLKALOU_CONFIG || {};
  const catalogUrl = config.archiveCatalogUrl || "../data/public/elections/catalog.json";
  const $ = (id) => document.getElementById(id);
  const number = (value) => value == null ? "—" : new Intl.NumberFormat("en-KE").format(Number(value));
  const percent = (value, digits = 1) => value == null ? "—" : `${(Number(value) * 100).toFixed(digits)}%`;
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  let catalog = null;
  let payload = null;
  let replayTimer = null;
  let replayPosition = null;

  async function fetchJson(url) {
    const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, {cache: "no-store"});
    if (!response.ok) throw new Error(`${response.status} ${url}`);
    return response.json();
  }

  function resolveDataUrl(entry) {
    return entry.data_url || `../data/public/elections/${entry.id}.json`;
  }

  async function init() {
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
    $("archiveEyebrow").textContent = `${election.constituency || "ELECTION"} · CONSTITUENCY ${election.code || "—"} · ${election.date || "—"}`;
    $("archiveTitle").textContent = election.title || `${election.constituency || "Election"} archive`;
    $("archiveUpdated").textContent = new Date(payload.generated_at).toLocaleString("en-KE", {dateStyle:"medium", timeStyle:"short"});
    $("archiveSourceState").textContent = payload.reference?.complete ? "Certified register loaded" : "Reference incomplete";
    $("archiveStreams").textContent = `${coverage.streams_total || 0}/${coverage.streams_total || 0}`;
    $("archiveForms").textContent = `${archive.forms_archived || 0}/${archive.forms_expected || coverage.streams_total || 0}`;
    $("archiveTranscribed").textContent = `${archive.stream_results_transcribed || 0}/${coverage.streams_total || 0}`;
    $("archiveRegistered").textContent = number(coverage.registered_total);
    $("archiveReplayState").textContent = archive.replay_available ? "READY" : "WITHHELD";
    $("archiveValid").textContent = `${number(payload.totals?.valid_votes)} valid`;
    $("archiveStatus").textContent = archive.stream_results_complete
      ? "All stream results are source-linked and the historical count can be replayed."
      : `${archive.forms_archived || 0} of ${archive.forms_expected || coverage.streams_total || 0} forms archived; ${archive.stream_results_transcribed || 0} stream tallies independently transcribed. Declared constituency totals are shown separately from the incomplete Form 35A sum.`;
    renderCandidates(payload.candidates || []);
    renderDeclaration();
    renderReplay();
    renderSnapshot();
    renderReadiness();
    renderSources();
    populateFilters();
    renderTable();
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
      $("archiveGridCounter").textContent = `${payload.archive?.forms_archived || 0}/${payload.coverage?.streams_total || 0} forms`;
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
    const winner = (payload.candidates || []).find(candidate => candidate.id === official.winner_id);
    $("declarationNote").innerHTML = `<p class="eyebrow">OFFICIAL DECLARATION</p>
      <p><strong>${escapeHtml(winner?.name || official.winner_id || "—")}</strong> was gazetted with <span class="numeric">${number(official.winner_votes)}</span> votes.</p>
      <p class="microcopy">Dashboard tally source: <strong>${escapeHtml(payload.archive?.tally_source || "UNKNOWN")}</strong>. ${escapeHtml(payload.archive?.methodology_note || "")}</p>`;
  }

  function renderReplay() {
    const available = Boolean(payload.archive?.replay_available);
    $("replayControls").hidden = !available;
    $("replayUnavailable").hidden = available;
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
    const byWard = new Map();
    (snapshot.streams || []).forEach(stream => {
      if (!byWard.has(stream.ward)) byWard.set(stream.ward, []);
      byWard.get(stream.ward).push(stream);
    });
    const candidateMap = new Map((snapshot.candidates || []).map(candidate => [candidate.id, candidate]));
    $("archiveGridTitle").textContent = `${snapshot.coverage?.streams_total || 0}-stream grid`;
    $("archiveStreamGrid").innerHTML = [...byWard.entries()].map(([ward, streams]) => {
      const completed = streams.filter(stream => stream.state === "PUBLISHED").length;
      return `<section class="ward-block"><h3><span>${escapeHtml(ward)}</span><span>${completed}/${streams.length}</span></h3><div class="ward-cells">${streams.map(stream => archiveCell(stream, candidateMap)).join("")}</div></section>`;
    }).join("");
    document.querySelectorAll(".archive-stream-cell").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function archiveCell(stream, candidateMap) {
    let className = "stream-cell archive-stream-cell";
    let style = "";
    if (stream.state === "PUBLISHED") {
      className += " published";
      const votes = Object.entries(stream.votes || {}).sort((a,b) => Number(b[1]) - Number(a[1]));
      const leader = votes[0];
      const colour = candidateMap.get(leader?.[0])?.colour || "#3FA76B";
      style = `background:${colour};opacity:.85`;
    } else if (stream.state === "ARCHIVED") className += " archived";
    else className += " reference-only";
    return `<button type="button" class="${className}" style="${style}" data-stream-key="${escapeHtml(stream.stream_key)}" title="${escapeHtml(stream.station_name)} · ${escapeHtml(stream.state)}" aria-label="${escapeHtml(stream.station_name)} stream ${stream.stream_no}: ${escapeHtml(stream.state)}"></button>`;
  }

  function renderReadiness() {
    const archive = payload.archive || {};
    const total = payload.coverage?.streams_total || 0;
    const checks = [
      ["Certified stream register", total, total],
      ["IEBC forms archived", archive.forms_archived || 0, archive.forms_expected || total],
      ["Independent transcription", archive.stream_results_transcribed || 0, total],
      ["Replay timestamps", archive.replay_available ? total : 0, total],
    ];
    $("archiveReadiness").innerHTML = checks.map(([label,value,max]) => `<div class="metric"><span>${escapeHtml(label)}</span><strong>${number(value)} / ${number(max)}</strong></div>`).join("");
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
    $("archiveTable").innerHTML = filtered.map(stream => `<tr>
      <td><button type="button" class="text-button archive-table-open" data-stream-key="${escapeHtml(stream.stream_key)}">${escapeHtml(stream.stream_key)}</button><br><span class="muted">${escapeHtml(stream.station_name)}</span></td>
      <td>${escapeHtml(stream.ward)}</td>
      <td><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span></td>
      <td>${number(stream.registered)}</td><td>${number(stream.valid)}</td>
      <td>${stream.form_url ? `<a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Form 35A ↗</a>` : "—"}</td>
    </tr>`).join("");
    document.querySelectorAll(".archive-table-open").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function openStream(streamKey) {
    const stream = currentSnapshot().streams.find(row => row.stream_key === streamKey);
    if (!stream) return;
    const candidates = new Map((payload.candidates || []).map(candidate => [candidate.id, candidate]));
    const votes = Object.entries(stream.votes || {}).map(([id,value]) => `<tr><td>${escapeHtml(candidates.get(id)?.name || id)}</td><td class="numeric">${number(value)}</td></tr>`).join("");
    $("archiveDialogBody").innerHTML = `<p class="eyebrow">${escapeHtml(stream.stream_key)} · ${escapeHtml(stream.ward)}</p><h2>${escapeHtml(stream.station_name)}</h2>
      <p><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span></p>
      <table class="detail-table"><tbody><tr><td>Registered</td><td class="numeric">${number(stream.registered)}</td></tr>${votes || `<tr><td colspan="2" class="muted">No independently verified stream tally has been imported.</td></tr>`}</tbody></table>
      ${stream.form_url ? `<p><a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Open archived Form 35A ↗</a></p>` : `<p class="muted">The form has not yet been archived by this repository.</p>`}`;
    $("archiveStreamDialog").showModal();
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
  init();
})();
