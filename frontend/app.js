(() => {
  const config = window.OLKALOU_CONFIG || { liveUrls: ["../data/public/live.json"], refreshMs: 30000 };
  const cacheKey = "olkalou.live.v2.lastKnownGood";
  let current = null;
  let previousStates = new Map();

  const $ = (id) => document.getElementById(id);
  const pct = (value, digits = 1) => `${((Number(value) || 0) * 100).toFixed(digits)}%`;
  const num = (value) => new Intl.NumberFormat("en-KE").format(Number(value) || 0);
  const ageMs = (iso) => Date.now() - Date.parse(iso || 0);
  const relative = (iso) => {
    const seconds = Math.max(0, Math.round(ageMs(iso) / 1000));
    if (seconds < 60) return `${seconds}s ago`;
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    return `${Math.round(minutes / 60)}h ago`;
  };
  const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

  async function fetchBestPayload() {
    const attempts = await Promise.allSettled(config.liveUrls.map(async url => {
      const response = await fetch(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`${response.status} ${url}`);
      const payload = await response.json();
      if (payload.schema !== "olkalou.live.v2") throw new Error(`Unexpected schema from ${url}`);
      return payload;
    }));
    const valid = attempts.filter(item => item.status === "fulfilled").map(item => item.value);
    if (!valid.length) throw new Error("No live endpoint returned a valid payload");
    return valid.sort((a, b) => Number(b.seq || 0) - Number(a.seq || 0))[0];
  }

  async function refresh() {
    try {
      const payload = await fetchBestPayload();
      if (current && Number(payload.seq) <= Number(current.seq)) {
        updateStaleness(current, false);
        return;
      }
      current = payload;
      localStorage.setItem(cacheKey, JSON.stringify(payload));
      render(payload);
    } catch (error) {
      console.error(error);
      if (!current) {
        const cached = localStorage.getItem(cacheKey);
        if (cached) {
          current = JSON.parse(cached);
          render(current);
        } else {
          $("statusLine").textContent = "The live feed is unavailable and no last-known-good ledger is cached on this device.";
        }
      }
      if (current) updateStaleness(current, true);
    }
  }

  function render(data) {
    const coverage = data.coverage || {};
    $("publishedCount").textContent = num(coverage.published);
    $("reviewCount").textContent = num(coverage.in_review);
    $("awaitingCount").textContent = num(coverage.awaiting);
    $("registeredPct").textContent = pct(coverage.registered_pct);
    $("turnout").textContent = pct(data.totals?.turnout_of_reported);
    $("validVotes").textContent = `${num(data.totals?.valid_votes)} valid`;
    $("updatedAt").textContent = relative(data.generated_at);
    $("pipelineHealth").textContent = `Watcher ${data.pipeline_health?.watcher || "UNKNOWN"} · ${data.pipeline_health?.worker_id || "worker"}`;
    $("statusLine").textContent = statusSentence(data);
    updateStaleness(data, false);
    renderReferenceBanner(data);
    renderCandidates(data);
    renderGrid(data);
    renderProjection(data);
    renderAnomalies(data.anomaly_feed || []);
    populateFilters(data.streams || []);
    renderTable(data.streams || []);
    renderCorrections(data.corrections || []);
    previousStates = new Map((data.streams || []).map(stream => [stream.stream_key, stream.state]));
  }

  function statusSentence(data) {
    const c = data.coverage || {};
    const candidates = data.candidates || [];
    const ranked = [...candidates].sort((a,b) => b.votes - a.votes);
    if (!c.published) return `IEBC has published no verified stream result counted by this ledger. ${c.in_review || 0} forms are in review.`;
    const leader = ranked[0];
    const runner = ranked[1];
    const margin = (leader?.votes || 0) - (runner?.votes || 0);
    return `${leader?.name || "The leader"} leads by ${num(margin)} votes with ${num(c.awaiting + c.in_review)} streams not yet counted.`;
  }

  function updateStaleness(data, fetchFailed) {
    const banner = $("staleBanner");
    const age = ageMs(data.generated_at);
    $("updatedAt").textContent = relative(data.generated_at);
    if (age > 10 * 60 * 1000) {
      banner.hidden = false; banner.className = "stale-banner red";
      banner.textContent = `FEED STALE — WE ARE NOT RECEIVING UPDATES. Last verified payload ${relative(data.generated_at)}.${fetchFailed ? " Showing last-known-good data." : ""}`;
    } else if (age > 3 * 60 * 1000 || fetchFailed) {
      banner.hidden = false; banner.className = "stale-banner amber";
      banner.textContent = `LAST VERIFIED UPDATE ${relative(data.generated_at)}${fetchFailed ? " — current fetch failed; showing last-known-good data." : ""}`;
    } else {
      banner.hidden = true;
    }
  }

  function renderReferenceBanner(data) {
    const banner = $("referenceBanner");
    if (data.reference?.complete) { banner.hidden = true; return; }
    banner.hidden = false;
    banner.textContent = `PRE-PRODUCTION REFERENCE GATE: ${data.reference?.errors?.join(" · ") || "official stream register incomplete"}. No incomplete register may drive a production tally.`;
  }

  function renderCandidates(data) {
    const maxVotes = Math.max(1, ...(data.candidates || []).map(c => c.votes || 0));
    $("candidateList").innerHTML = (data.candidates || []).map((candidate, index) => `
      <article class="candidate-row">
        <div class="candidate-meta"><span class="candidate-name">${index + 1}. ${escapeHtml(candidate.name)}</span><span class="party-chip">${escapeHtml(candidate.abbr)}</span></div>
        <div><span class="candidate-votes">${num(candidate.votes)}</span><span class="candidate-share">${pct(candidate.share)}</span></div>
        <div class="candidate-track"><div class="candidate-fill" style="width:${(candidate.votes / maxVotes) * 100}%;background:${candidate.colour}"></div></div>
      </article>`).join("");

    const gov = data.blocs?.GOVERNMENT || {votes:0,share:0};
    const opp = data.blocs?.OPPOSITION || {votes:0,share:0};
    $("blocPanel").innerHTML = `
      <p class="eyebrow">BLOC ARITHMETIC</p>
      <div class="bloc-row"><span>Government (UDA)</span><strong class="numeric">${num(gov.votes)} · ${pct(gov.share)}</strong><div class="bloc-bar"><span style="width:${gov.share*100}%"></span></div></div>
      <div class="bloc-row"><span>Other eight combined</span><strong class="numeric">${num(opp.votes)} · ${pct(opp.share)}</strong><div class="bloc-bar"><span style="width:${opp.share*100}%"></span></div></div>
      <p class="bloc-note">${escapeHtml(data.blocs?.note || "Arithmetic aggregation only; votes are not transferable between parties.")}</p>`;
  }

  function renderGrid(data) {
    const byWard = new Map();
    (data.streams || []).forEach(stream => {
      if (!byWard.has(stream.ward)) byWard.set(stream.ward, []);
      byWard.get(stream.ward).push(stream);
    });
    const candidateMap = new Map((data.candidates || []).map(c => [c.id, c]));
    $("streamGrid").innerHTML = [...byWard.entries()].map(([ward, streams]) => {
      const published = streams.filter(s => s.state === "PUBLISHED").length;
      return `<section class="ward-block"><h3><span>${escapeHtml(ward)}</span><span>${published}/${streams.length}</span></h3><div class="ward-cells">${streams.map(stream => cellHtml(stream, candidateMap)).join("")}</div></section>`;
    }).join("");
    document.querySelectorAll(".stream-cell").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function cellHtml(stream, candidateMap) {
    let className = "stream-cell";
    let style = "";
    if (stream.state === "PUBLISHED") {
      className += " published";
      const votes = Object.entries(stream.votes || {}).sort((a,b) => b[1]-a[1]);
      const leader = votes[0]; const runner = votes[1];
      const valid = Math.max(1, votes.reduce((sum, item) => sum + Number(item[1]), 0));
      const margin = Math.max(0, Number(leader?.[1] || 0) - Number(runner?.[1] || 0));
      const opacity = Math.min(.95, .28 + (margin / valid) * 1.8);
      const colour = candidateMap.get(leader?.[0])?.colour || "#3FA76B";
      style = `background:${colour};opacity:${opacity}`;
    } else if (["QUARANTINED","ARCHIVED","EXTRACTED","AUTO_VERIFIED"].includes(stream.state)) className += " review";
    else if (stream.state === "CONFLICTED") className += " conflicted";
    if (previousStates.get(stream.stream_key) && previousStates.get(stream.stream_key) !== "PUBLISHED" && stream.state === "PUBLISHED") className += " new";
    return `<button type="button" class="${className}" style="${style}" data-stream-key="${escapeHtml(stream.stream_key)}" aria-label="${escapeHtml(stream.station_name)} stream ${stream.stream_no}: ${stream.state}" title="${escapeHtml(stream.station_name)} · ${stream.state}"></button>`;
  }

  function renderProjection(data) {
    const p = data.projection || {};
    const leader = (data.candidates || []).find(c => c.id === p.leader);
    const model = p.t3_model;
    const probability = leader && model?.win_probability ? model.win_probability[leader.id] : null;
    $("projectionPanel").innerHTML = `<div class="metric-stack">
      <div class="metric"><span>Current leader</span><strong>${escapeHtml(leader?.name || "No verified leader")}</strong><p>Margin: ${num(p.margin || 0)} valid votes.</p></div>
      <div class="metric"><span>T1 · hard bound</span><strong class="${p.t1_hard_bound?.mathematically_decided ? "decided" : ""}">${p.t1_hard_bound?.mathematically_decided ? "MATHEMATICALLY DECIDED" : "NOT DECIDED"}</strong><p>${num(p.t1_hard_bound?.remaining_registered || 0)} registered voters remain outside the published tally. No turnout assumption.</p></div>
      <div class="metric"><span>T2 · turnout-capped</span><strong>${p.t2_capped_bound?.decided ? "DECIDED UNDER CAP" : "OPEN UNDER CAP"}</strong><p>Maximum remaining votes under observed 95th-percentile turnout: ${num(p.t2_capped_bound?.max_remaining_votes || 0)}.</p></div>
      <div class="metric"><span>T3 · ward-stratified model</span><strong>${probability == null ? "WITHHELD" : pct(probability,0)}</strong><p>${model ? `${escapeHtml(model.method)} · margin 90% interval ${num(model.margin_ci90?.[0])} to ${num(model.margin_ci90?.[1])}.` : "Model is withheld until enough verified streams and complete register weights are available."}</p></div>
    </div>`;
  }

  function renderAnomalies(items) {
    $("anomalyFeed").innerHTML = items.length ? items.slice(0,30).map(item => `<article class="feed-item"><strong>${escapeHtml(item.severity)} · ${escapeHtml(item.code)} · ${escapeHtml(item.stream_key)}</strong><span>${escapeHtml(item.message)}</span>${item.form_url ? ` <a href="${escapeHtml(item.form_url)}" target="_blank" rel="noopener">Open form</a>` : ""}</article>`).join("") : `<p class="feed-empty">No anomalies logged.</p>`;
  }

  function populateFilters(streams) {
    const ward = $("wardFilter"), state = $("stateFilter");
    if (ward.options.length === 1) [...new Set(streams.map(s => s.ward))].sort().forEach(value => ward.add(new Option(value, value)));
    if (state.options.length === 1) [...new Set(streams.map(s => s.state))].sort().forEach(value => state.add(new Option(value, value)));
  }

  function renderTable(streams) {
    const ward = $("wardFilter").value, state = $("stateFilter").value, search = $("streamSearch").value.trim().toLowerCase();
    const filtered = streams.filter(s => (!ward || s.ward === ward) && (!state || s.state === state) && (!search || `${s.stream_key} ${s.station_name}`.toLowerCase().includes(search)));
    $("streamTable").innerHTML = filtered.map(stream => `<tr>
      <td><button class="text-button table-open" data-stream-key="${escapeHtml(stream.stream_key)}">${escapeHtml(stream.stream_key)}</button><br><span class="muted">${escapeHtml(stream.station_name)}</span></td>
      <td>${escapeHtml(stream.ward)}</td><td><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span></td>
      <td><span class="verify-badge verify-${escapeHtml(stream.verification)}">${escapeHtml(stream.verification || "NONE")}</span></td>
      <td>${stream.registered == null ? "—" : num(stream.registered)}</td><td>${stream.cast == null ? "—" : num(stream.cast)}</td><td>${stream.turnout == null ? "—" : pct(stream.turnout)}</td>
      <td>${stream.form_url ? `<a class="source-link" href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Form 35A ↗</a>` : "—"}</td></tr>`).join("");
    document.querySelectorAll(".table-open").forEach(button => button.addEventListener("click", () => openStream(button.dataset.streamKey)));
  }

  function renderCorrections(items) {
    $("correctionsLog").innerHTML = items.length ? items.map(item => `<article class="feed-item"><strong>${escapeHtml(item.at)} · ${escapeHtml(item.stream_key)} · ${escapeHtml(item.field)}</strong><span>${escapeHtml(item.from)} → ${escapeHtml(item.to)}. ${escapeHtml(item.reason)}</span></article>`).join("") : `<p class="feed-empty">No corrections have been published. This log is append-only.</p>`;
  }

  function openStream(streamKey) {
    const stream = current?.streams?.find(s => s.stream_key === streamKey);
    if (!stream) return;
    const candidateMap = new Map((current.candidates || []).map(c => [c.id,c]));
    const votes = Object.entries(stream.votes || {}).sort((a,b) => (candidateMap.get(a[0])?.ballot_no || 99) - (candidateMap.get(b[0])?.ballot_no || 99));
    const checkRows = Object.entries(stream.checks || {}).map(([code,status]) => `<div class="check"><span>${escapeHtml(code)}</span><strong>${escapeHtml(status)}</strong></div>`).join("") || `<p class="muted">Checks are not available until extraction or review.</p>`;
    const sourceEmbed = stream.form_url ? (stream.form_url.toLowerCase().includes(".pdf") ? `<iframe class="form-frame" src="${escapeHtml(stream.form_url)}" title="Scanned Form 35A"></iframe>` : `<img class="form-frame" src="${escapeHtml(stream.form_url)}" alt="Scanned Form 35A">`) : `<div class="form-frame" style="display:grid;place-items:center;color:#222">IEBC form not yet available</div>`;
    $("streamDialogBody").innerHTML = `<p class="eyebrow">${escapeHtml(stream.stream_key)} · ${escapeHtml(stream.ward)}</p><h2>${escapeHtml(stream.station_name)}</h2><div class="dialog-grid"><div>${sourceEmbed}</div><div><p><span class="state-badge state-${escapeHtml(stream.state)}">${escapeHtml(stream.state)}</span> <span class="verify-badge verify-${escapeHtml(stream.verification)}">${escapeHtml(stream.verification || "NONE")}</span></p><table class="detail-table"><tbody>${votes.map(([id,value]) => `<tr><td>${escapeHtml(candidateMap.get(id)?.name || id)}</td><td class="numeric">${num(value)}</td></tr>`).join("")}<tr><td>Rejected</td><td class="numeric">${stream.rejected == null ? "—" : num(stream.rejected)}</td></tr><tr><td>Valid</td><td class="numeric">${stream.valid == null ? "—" : num(stream.valid)}</td></tr></tbody></table><h3>Validation checks</h3><div class="checks">${checkRows}</div>${stream.form_url ? `<p><a href="${escapeHtml(stream.form_url)}" target="_blank" rel="noopener">Open immutable source form ↗</a></p>` : ""}</div></div>`;
    $("streamDialog").showModal();
  }

  [$("wardFilter"), $("stateFilter"), $("streamSearch")].forEach(control => control.addEventListener("input", () => current && renderTable(current.streams || [])));
  $("closeDialog").addEventListener("click", () => $("streamDialog").close());
  $("gridHelp").addEventListener("click", () => $("legendDialog").showModal());
  document.querySelectorAll("[data-close-dialog]").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
  setInterval(() => current && updateStaleness(current, false), 15000);
  setInterval(refresh, config.refreshMs || 30000);
  refresh();
})();
