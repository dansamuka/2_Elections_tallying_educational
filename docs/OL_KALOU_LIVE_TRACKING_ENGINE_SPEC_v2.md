# Ol Kalou By-Election Live Tracking Engine — Specification v2

**Election:** Member of National Assembly, Ol Kalou Constituency (Code 091), Nyandarua County
**Polling day:** Thursday, 16 July 2026 · Polls 06:00–17:00 EAT
**Spec date:** 13 July 2026 (T-3 days)
**Status:** Supersedes v1. Reframes the product thesis, adds the trust layer, adds the analytical layer, adds an executable build plan.

---

## 0. What changed from v1, and why

| v1 assumption | v2 position |
|---|---|
| The product is **speed** (1-minute refresh) | The product is **provenance**. Speed is table stakes. See §1. |
| The unit is a **polling station** (144) | The unit is a **polling stream**. 2022 register: 142 stations / 72,997 voters. Portal shows 144. That delta must be resolved. See §2.3. |
| OCR is a solved input | OCR of handwritten Form 35A is the **single largest project risk**. Treat it as a pre-fill, never as a source of truth. See §7. |
| No validation layer | 12-check statutory validation engine with a hard publication gate. See §8. |
| Only Form 35A | 35A **and 35B**. The 35B is the legally operative declaration; reconciling Σ35A against 35B is the highest-value output of the entire project. See §3.2. |
| "anomalies" undefined | Formal anomaly taxonomy with severity and routing. See §8. |
| Frontend unspecified | Full design system + signature component. See §13. |
| No legal posture | Explicit editorial and legal posture. See §14. |
| No failure model | Risk register + election-night runbook. See §15–16. |

**The one-line verdict on v1:** the architecture is sound, the data model is one level too coarse, and the trust model is missing entirely. A dashboard that publishes an unverified number during a contested by-election is worse than no dashboard.

---

## 1. Product thesis and non-goals

### 1.1 Thesis

> **Every number on this dashboard is one click from the scanned form it came from.**

You will not beat Citizen TV, NTV, or the UDA and DCP war rooms to a raw number. Party agents receive a signed copy of Form 35A **at the polling station**, hours before IEBC uploads a scan. Optimising for latency is optimising for a race you have already lost.

What nobody else will publish is a tally where:
- every station's figure links to its source image,
- every figure carries a verification state (machine / human / disputed),
- every statutory check is shown, passing or failing,
- the unreported remainder is quantified, not hidden,
- and corrections are logged in public, permanently.

That is the product. It is consistent with the verification ledger already built for the Kenya Election Intelligence Engine, and it is the only defensible position for an independent publisher.

### 1.2 Explicit non-goals

- **Not** declaring a winner. Only the Returning Officer may declare (§14).
- **Not** a party parallel tally. No agent-submitted forms, no phone-reported figures. IEBC-published forms only. One source, auditable.
- **Not** real-time in the sub-minute sense. Publish cadence is bounded by IEBC's upload cadence, not by your cron.

---

## 2. Ground truth — verified as of 13 July 2026

### 2.1 The contest

Seat vacated by the death of Hon. David Njuguna Kiaraho (Jubilee, MP since 2013) on 29 March 2026. Speaker Wetang'ula declared the vacancy on 22 April 2026 under Articles 101(1)(a) and 103(1)(a) of the Constitution and s.16(3) of the Elections Act, 2011. IEBC gazetted 16 July 2026 as polling day. Campaigns closed **18:00, Monday 13 July 2026** (48-hour silence period).

**Nine candidates cleared.** Eight are aligned against the government; one — Muchina Nyagah (UDA) — is the sole government-backed candidate.

| # | Candidate | Party |
|---|---|---|
| 1 | Samuel Muchina Nyagah | United Democratic Alliance (UDA) |
| 2 | Kamau Ngotho *(see note)* | Democracy for the Citizens Party (DCP) |
| 3 | Wilson Kigwa | Jubilee Party |
| 4 | Edwin Muchiri | Party of National Unity |
| 5 | Rachel Wangui | People's Democratic Party |
| 6 | Mathenge Mwaniki | Kenya Moja Movement |
| 7 | Abdifatah Hussein | Federal Party of Kenya |
| 8 | Timothy Kamau | People's Renaissance Party |
| 9 | Stephen Wanyoike | National Liberal Party |

> ⚠️ **Note on candidate 2.** Media reporting is inconsistent — the *Nation* has published both "Sammy Kamau Ngotho" and "Douglas Waweru" as the DCP candidate in separate July pieces. **Do not take a candidate name or ballot order from a newspaper.** The authoritative source is the IEBC gazette notice / the Returning Officer's certified candidate list. Ballot order and exact legal names determine the row order on Form 35A, which determines your OCR template. **Resolve this today.**

This is, in miniature, the whole argument for the project: the press cannot keep nine names straight three days out.

### 2.2 Why this election is analytically interesting

Kenya elects MPs by **simple plurality (first-past-the-post)**. There is no 50%+1 threshold — that applies only to the presidency (Art. 138(4)). With one government candidate and eight opposition candidates on a single ballot, **the vote-splitting arithmetic is the story.**

Precedent: in the Mbeere North by-election (Nov 2025), multiple opposition candidates split the anti-government vote and UDA won despite the combined opposition vote exceeding UDA's. Commentators have explicitly flagged the same dynamic here.

That gives the dashboard its analytical hook (§11.3): **a live bloc-arithmetic panel** — UDA vs. the sum of the other eight — that no broadcast chyron will show.

### 2.3 The 142 / 144 problem — resolve before Thursday

- **2022 certified register:** Ol Kalou = **72,997 registered voters**, **142 polling stations**, **5 wards** (Karau, Kanjuiri Ridge, Mirangine, Kaimbaga, Rurii).
- **IEBC results portal (per v1 spec):** "OL KALOU (0 of **144** reported)".

Two voters short of an explanation. The most likely cause: **the portal counts polling *streams*, not polling *stations*.** A station exceeding the statutory maximum voters is split into streams, and **each stream files its own Form 35A**. 142 stations + 2 second streams = 144 forms.

Consequences if you get this wrong:
- Your denominator never reaches 144/144 and the dashboard sits at "142 of 144" forever.
- Two forms will fail your "duplicate station" check because they share a station name.
- Your registered-voter denominator will be wrong.

**Therefore: the atomic key of this system is `(station_code, stream_no)`, not `station_name`.**

Also note: IEBC **suspended** voter registration and register revision in Ol Kalou for the whole by-election period. So the register in force is the certified register carried forward — get the gazetted figure from IEBC, not from a 2022 aggregator site.

### 2.4 Turnout prior

Emurua Dikirr by-election (14 May 2026): 29,538 cast of 44,353 registered = **66.6% turnout**. High for a mini-poll, but this is a high-salience proxy contest. Use 50–70% as the prior band for the projection model (§11.2), and recalibrate live from reported streams.

---

## 3. Domain model

### 3.1 Entities

```
Constituency (091, Ol Kalou)
 └── Ward (×5)
      └── PollingStation (×142)
           └── PollingStream (×144)   ← THE ATOMIC UNIT. One Form 35A each.
                └── FormVersion (×n)  ← immutable; IEBC may re-upload an amended form
                     └── FieldExtraction (per candidate, per control total)
```

`stream_key = f"{station_code}-{stream_no:02d}"` — e.g. `091-0451-01`.

### 3.2 The forms

| Form | Level | Signed by | Role in this system |
|---|---|---|---|
| **35A** | Polling stream | Presiding Officer | Primary evidence. 144 expected. |
| **35B** | Constituency | Returning Officer | **The legal declaration.** Ingest it. Reconcile Σ35A against it. |

**The 35B reconciliation is the deliverable that outlives election night.** If Σ(your 144 verified 35As) ≠ the RO's declared 35B total, you have found something genuinely newsworthy and you have the receipts. If it reconciles exactly, you have publicly certified the result — which is itself a valuable public good. Either way you win. Build for this.

### 3.3 Statutory arithmetic (define once, compute everywhere)

```
valid_votes(stream)      = Σ candidate_votes
total_cast(stream)       = valid_votes + rejected_votes
turnout(stream)          = total_cast / registered_voters
share(candidate, scope)  = candidate_votes / valid_votes         # of VALID votes, not cast
margin(scope)            = votes(leader) - votes(runner_up)
```

- Winner = **plurality of valid votes**. No threshold. Never render a 50% line.
- Vote share denominators are **valid votes**, not votes cast. Getting this wrong shifts every share by the rejected rate.
- Turnout denominators are **registered voters from the certified register** — not the figure OCR'd off the form. The form's registered figure is a *check*, not a source (see V07).

---

## 4. Architecture (revised)

```
                        ┌──────────────────────────┐
                        │  forms.iebc.or.ke        │
                        │  (Form 35A / 35B scans)  │
                        └────────────┬─────────────┘
                                     │ 60s conditional GET (ETag)
                        ┌────────────▼─────────────┐
      ┌─────────────────│  1. WATCHER              │  detects new/changed forms
      │   ALERT         │     (delta vs manifest)  │
      │   on failure    └────────────┬─────────────┘
      │                              │
      │                 ┌────────────▼─────────────┐
      │                 │  2. ARCHIVER             │  ← DO THIS FIRST, ALWAYS
      │                 │     immutable raw store  │     (sha256, never overwrite)
      │                 └────────────┬─────────────┘
      │                              │
      │                 ┌────────────▼─────────────┐
      │                 │  3. EXTRACTOR            │  ROI crop → dual OCR → consensus
      │                 │     (pre-fill only)      │     numerals ⟷ words cross-check
      │                 └────────────┬─────────────┘
      │                              │
      │                 ┌────────────▼─────────────┐
      │                 │  4. VALIDATOR            │  V01–V12. Assigns trust state.
      │                 └──────┬──────────┬────────┘
      │                        │          │
      │            auto-publish│          │quarantine
      │            (all green) │          │
      │                        │   ┌──────▼─────────────┐
      │                        │   │  5. REVIEW CONSOLE │  ← THE PRODUCT
      │                        │   │  double-entry, 2   │     humans confirm
      │                        │   │  independent keys  │
      │                        │   └──────┬─────────────┘
      │                        │          │
      │                 ┌──────▼──────────▼────────┐
      │                 │  6. PUBLISHER            │  writes live.json + delta log
      │                 │     monotonic seq no.    │
      │                 └────────────┬─────────────┘
      │                              │
      │                 ┌────────────▼─────────────┐
      └─────────────────│  CDN / object storage    │  public read, TTL 20s, CORS *
                        │  (R2 / S3 / Firebase)    │
                        └────────────┬─────────────┘
                                     │ fetch every 30s
                        ┌────────────▼─────────────┐
                        │  STATIC DASHBOARD        │
                        │  GitHub Pages            │
                        │  last-known-good cache   │
                        └──────────────────────────┘
```

### 4.1 Runtime decision — read this carefully

**GitHub Actions is the wrong ingestion runtime for election night.** Scheduled workflows have a 5-minute minimum, are routinely delayed 10–30+ minutes under platform load, and committing every cycle for 18 hours produces ~1,000 commits with Pages rebuild latency measured in minutes. It works fine for the weekly poll refresh on the Election Intelligence Engine. It will not work here.

**Recommended (Option A):** one always-on Python worker on a cheap VPS or Fly/Railway/Render instance → writes `live.json` to Cloudflare R2 (or S3) with public read, CORS, `Cache-Control: max-age=20`. Frontend stays on GitHub Pages and fetches the CDN URL. Cost: <$10. Latency: seconds.

**Redundancy is mandatory.** Run **two workers in different places**. Both write to the same object with a monotonically increasing `seq`; the publisher refuses to write a `seq` lower than the one currently live. You get one shot at Thursday night and you will not be debugging a dead container at 23:40.

**Fallback (Option C):** GitHub Actions at 5-minute cadence. Acceptable degradation if budget is zero — but then label the site "updated approximately every 5 minutes" and mean it. Never advertise a cadence you cannot hold.

### 4.2 Politeness and portal etiquette

1,080 requests over 18 hours against one HTML index is nothing. The ban risk is negligible; the *availability* risk is not. Therefore:
- Conditional GET (`If-None-Match` / `If-Modified-Since`). Exit early on `304`.
- Exponential backoff with jitter on `429`/`5xx`. Cap at 5 min.
- Single-threaded image downloads, 1 concurrent connection.
- Honest `User-Agent` with a contact URL. You are a civic verifier, not a scraper. Act like it.
- **Archive first, process later.** IEBC has taken results portals offline after past elections. If you archive every scan the moment you see it, you become a permanent system of record for this by-election. That alone justifies the project.

---

## 5. Reference data — build this BEFORE Thursday

This is the highest-leverage work in the entire project and it is all doable today and tomorrow. Without it, everything downstream is guesswork.

### 5.1 `streams.json` — the register (144 rows)

```json
{
  "constituency": { "code": "091", "name": "OL KALOU", "county": "NYANDARUA" },
  "register_source": "IEBC Certified Register, Gazette Notice <no.> of <date>",
  "register_total": 72997,
  "streams": [
    {
      "stream_key": "091-0451-01",
      "station_code": "0451",
      "station_name": "OL KALOU PRIMARY SCHOOL",
      "stream_no": 1,
      "ward_code": "0453",
      "ward_name": "KARAU",
      "registered": 512,
      "baseline_2022": { "JUBILEE": 301, "UDA": 88, "OTHER": 44, "rejected": 6, "cast": 439 }
    }
  ]
}
```

**Why this file is everything:**
- The dashboard renders all 144 streams from **minute zero** as `AWAITING` — it looks like a real instrument from the moment polls close, not an empty page slowly filling.
- The denominator is known in advance → you can report **"% of registered voters accounted for"**, which is far more meaningful than "% of stations."
- V07 (registered-voters cross-check) becomes possible — the single strongest anti-OCR-error check.
- The projection model (§11) has a weighting frame.
- `baseline_2022` gives you **live swing analysis**, which is genuine intelligence rather than a scoreboard.

**Sources, in priority order:** (1) IEBC Returning Officer / gazetted register for the by-election; (2) the IEBC RoV-per-polling-station PDF; (3) the 2022 Form 35A/35B set for Ol Kalou on `forms.iebc.or.ke` (which also gives you `baseline_2022` *and* a template sample — see §5.3).

### 5.2 `candidates.json` — ballot order matters

```json
{
  "source": "IEBC certified candidate list, Ol Kalou by-election, 26 May 2026",
  "candidates": [
    { "ballot_no": 1, "name": "...", "party": "UDA", "abbr": "UDA",
      "colour": "#RRGGBB", "bloc": "GOVERNMENT" }
  ],
  "blocs": { "GOVERNMENT": ["UDA"], "OPPOSITION": ["DCP","JUBILEE","PNU","PDP","KMM","FPK","PRP","NLP"] }
}
```

Ballot order fixes the **row order on Form 35A**, which fixes your OCR ROI map. Get it from the certified list, not the press.

Party colours: derive from party branding, then **contrast-check every one against the dark ground at AA (4.5:1 for text, 3:1 for graphical objects)**. Same discipline as the Kazi Sasa v4 token work. Store the checked hex in the file; never pick colours in the component.

### 5.3 The dress-rehearsal corpus — you have labelled ground truth available *today*

This is the most useful thing in this document.

**Emurua Dikirr by-election, 14 May 2026** — same portal, same era, same Form 35A layout, same scan quality, same PO handwriting conditions. And the official result is already public:

> Keter (UDA) 18,266 · Rotich (DCP) 10,760 · 29,538 cast of 44,353 registered · 66.6% turnout.

So: pull the Emurua Dikirr 35As now, run your entire pipeline over them, and **compare your computed total to the declared total.** If you reproduce 18,266 and 10,760 from the scans, your pipeline works. If you don't, you know precisely where it breaks — *before* Thursday, not during.

Also available: **Mbeere North, Kasipul, Malava, Magarini** (27 Nov 2025) — four more MP by-elections with published 35As and declared results.

Five constituencies of labelled test data. Use them. This converts OCR from an act of faith into an engineering problem with a measurable error rate.

**Deliverable:** `accuracy_report.md` with per-field precision/recall measured on ≥100 real 35As. If per-field accuracy on candidate vote counts is below ~97%, **OCR is a pre-fill and nothing more** — go to double-entry (§10).

---

## 6. Ingestion & archival

### 6.1 Watcher loop (60s)

```
manifest = load("manifest.json")           # stream_key -> [{sha256, url, seen_at, version}]
index    = conditional_get(PORTAL_URL)     # 304 -> sleep, return
listed   = parse_olkalou_rows(index)       # only rows scoped to constituency 091

new      = [f for f in listed if f.url not in manifest.urls]
changed  = [f for f in listed if f.url in manifest.urls and f.etag != manifest[f.url].etag]

if not new and not changed: return         # cheap exit, most ticks
for f in new + changed: enqueue(f)
```

Handle `changed` seriously: **IEBC re-uploads amended forms.** An amended form is a new `FormVersion`, never an overwrite. If the figures differ, the stream enters `CONFLICTED` and is surfaced loudly (§9). Silently swallowing an amendment is how you lose credibility permanently.

### 6.2 Archiver

For every discovered form, **before any processing**:

```
raw/{stream_key}/v{n}_{sha256[:12]}.{ext}
raw/{stream_key}/v{n}_meta.json   # url, etag, content-length, discovered_at, http headers
```

Immutable. Append-only. Backed up to a second bucket. This runs even if the OCR container is on fire.

### 6.3 Canary

The scraper's most dangerous failure is **silent success**: the portal changes its HTML and your parser returns zero rows forever while your dashboard cheerfully shows "0 of 144 reported" and you assume IEBC is slow.

Guard: if `now > 19:00 EAT` and `stations_reported == 0` for 3 consecutive ticks → **fire an alert to your phone** (Telegram bot / Slack webhook). Also assert on structure: if the index page no longer contains the expected constituency row, alert immediately regardless of time.

---

## 7. Extraction (OCR) — treat as untrusted pre-fill

### 7.1 Why this is the highest risk

Form 35A is **handwritten**. Numerals in boxes, filled under pressure, at night, photographed or scanned at variable quality with skew and glare. Generic full-page OCR on Kenyan result forms performs poorly enough that several 2022 civic-tech efforts foundered here. Do not budget optimism.

### 7.2 The four accuracy levers, in order of impact

**1. Template ROI cropping (largest single win).**
All 144 forms share one printed template with a fixed row count (= 9 candidates + control totals). So:
- Take a reference 35A (from the 2022 Ol Kalou set or the by-election blank).
- On each incoming scan: feature-match the *printed* elements → estimate homography → warp to the reference frame.
- Crop each known cell ROI: `candidate[1..9].numeral`, `candidate[1..9].words`, `registered`, `rejected`, `total_valid`, `station_name`.
- OCR **each cell independently**, constrained to a numeric charset.

Per-cell OCR against a fixed template is dramatically more accurate than whole-page OCR plus regex. Build the ROI map on Tuesday.

**2. Numerals ⟷ words cross-check (free redundancy).**
Form 35A requires the PO to write each figure **in numbers and in words**. OCR both. If they agree → confidence soars. If they disagree → quarantine immediately. Almost nobody does this. It is nearly free and it catches the exact class of error that matters most (a transposed or misread digit).

**3. Dual-engine consensus.**
- Primary: **Google Cloud Vision `DOCUMENT_TEXT_DETECTION`** — best-in-class handwriting, gives per-symbol confidence and bounding boxes.
- Secondary: **AWS Textract Queries** — you can literally ask *"How many votes did <candidate> receive?"* and it handles handwriting well.
- Agreement on a field → high confidence. Disagreement → quarantine.
- Cost: 144 forms × 2 engines ≈ **under $3 total.** There is no reason not to.

**4. Preprocessing.** Deskew, denoise, adaptive threshold, 2× upscale. OpenCV. Cheap, meaningful.

### 7.3 Output contract

```json
{
  "stream_key": "091-0451-01",
  "form_version": 1,
  "engine_results": {
    "gcv":      { "c1": 201, "c2": 154, "...": "...", "rejected": 5, "po_total_valid": 355 },
    "textract": { "c1": 201, "c2": 154, "...": "...", "rejected": 5, "po_total_valid": 355 }
  },
  "words_check": { "c1": "TWO HUNDRED AND ONE -> 201 ✓", "c2": "MISMATCH ✗" },
  "field_confidence": { "c1": 0.99, "c2": 0.61 },
  "consensus": "PARTIAL",
  "route": "QUARANTINE"
}
```

**No field with `field_confidence < 0.95`, or with any engine disagreement, or with a numeral/words mismatch, ever reaches the published tally without a human.** Full stop.

---

## 8. Validation engine — the anomaly taxonomy

Every stream is scored against these on every version. This replaces v1's undefined `"anomalies": 1`.

| Code | Check | Rule | Severity | Routing |
|---|---|---|---|---|
| **V01** | Candidate sum = PO stated valid | `Σ candidates == po_total_valid` | CRITICAL | Quarantine |
| **V02** | Valid + rejected = total cast | `po_total_valid + rejected == total_cast` | CRITICAL | Quarantine |
| **V03** | Turnout ≤ 100% | `total_cast <= registered` | CRITICAL | Quarantine + **publish the flag** |
| **V04** | Turnout plausibility | `turnout > 95%` → flag | WARN | Human review |
| **V05** | Rejected-ballot rate | `rejected / total_cast` outside calibrated band | WARN | Human review |
| **V06** | Zero-vote candidate | any candidate == 0 | WARN | Human review (usually an OCR miss) |
| **V07** | **Register cross-check** | `ocr.registered == streams.json.registered` | CRITICAL | Quarantine |
| **V08** | Duplicate stream | stream already published with different figures | CRITICAL | → `CONFLICTED` |
| **V09** | Legibility | mean field confidence < 0.95 | WARN | Human review |
| **V10** | Ward roll-up integrity | `Σ stream.registered == ward.registered` (official) | INFO | Log |
| **V11** | Vote-share outlier | stream share > 3σ from ward mean (min 10 reported) | INFO | Anomaly feed |
| **V12** | Last-digit uniformity | digit distribution across ≥50 streams | INFO | Post-election only |

**Calibrate V05's band from the Emurua Dikirr 35As.** Don't guess a threshold; measure the real rejected-rate distribution in a comparable Kenyan by-election and set the band from it. That is a two-hour job that makes the check defensible.

**V07 is the workhorse.** Because you pre-loaded the certified register, any 35A whose OCR'd registered-voter count doesn't match the official figure for that stream is either an OCR error or a genuine form error. Either way you want to know before publishing. This one check catches most of what the others miss.

**V11/V12 caveat:** these are weak signals. Never present a Benford-style test as evidence of fraud. Label them *"statistical curiosities — for human attention, not conclusions."* Overclaiming here would destroy the project's credibility faster than any OCR error.

---

## 9. Trust state machine & publication gate

```
DISCOVERED ──► ARCHIVED ──► EXTRACTED ──┬──► AUTO_VERIFIED ──► PUBLISHED
                                        │         (all CRITICAL pass,
                                        │          all confidence ≥0.95,
                                        │          numerals==words,
                                        │          both engines agree)
                                        │
                                        ├──► QUARANTINED ──► HUMAN_VERIFIED ──► PUBLISHED
                                        │                          │
                                        │                          └──► DISPUTED (published,
                                        │                                flagged, figures shown
                                        │                                with a warning)
                                        └──► CONFLICTED (amended form disagrees with published)

Terminal side-states: AWAITING (not yet uploaded), DISRUPTED, POSTPONED, VOIDED
```

### Publication rules — non-negotiable

1. Only `PUBLISHED` streams count toward the headline tally.
2. `QUARANTINED` streams are **visible on the dashboard as a count**, not hidden. "127 published · 6 in review · 11 awaiting" is honest and is itself the trust signal.
3. Every published figure carries a badge: **machine-verified** or **human-verified**. Both are shown. Users decide how much to trust each.
4. `PUBLISHED` figures are **immutable**. An amendment creates a new version and a **public delta entry**. Never silently overwrite a number a member of the public has already seen.
5. `DISRUPTED` / `POSTPONED` streams are removed from the denominator and the removal is stated on the face of the dashboard. (Given IEBC's stated concerns about violence in the constituency, budget for this — it is not hypothetical.)

---

## 10. Human review console — this is the product, build it first

144 forms. A well-designed review screen lets one person confirm a form in **~10 seconds**. That is **24 minutes of work for all 144.**

### 10.1 Design

Two panes, keyboard-driven, no mouse required:

```
┌─────────────────────────────┬──────────────────────────────┐
│                             │  091-0451-01                 │
│                             │  OL KALOU PRIMARY, Karau     │
│    [ Scanned Form 35A ]     │                              │
│                             │  Registered  [  512 ] ✓ reg  │
│    pan / zoom / rotate      │  1 Nyagah    [  201 ]        │
│                             │  2 Ngotho    [  154 ]  ⚠ .61 │
│    ← auto-zoom to the       │  ...                         │
│      field under cursor     │  9 Wanyoike  [    3 ]        │
│                             │  Rejected    [    5 ]        │
│                             │  PO Total    [  355 ]        │
│                             │  ─────────────────────────   │
│                             │  Σ = 355  ✓ V01  ✓ V02  ✓V07 │
│                             │                              │
│                             │  [Enter] CONFIRM  [R] REJECT │
└─────────────────────────────┴──────────────────────────────┘
```

Auto-zoom the scan to the ROI of whichever field has focus. That single interaction is what turns 60 seconds per form into 10.

### 10.2 Double-entry — the fallback that makes OCR optional

Professional Parallel Vote Tabulation operations do not trust a single keystroke, let alone a single OCR pass. **Two reviewers independently key each form; a script diffs them; mismatches go to a third pair of eyes.**

144 forms × 2 = 288 entries at ~30s each = **2.4 person-hours**. Entirely feasible with two volunteers on a rota.

**This is the design insight that de-risks the whole project:**

> **The review console is the product. OCR is an optimisation.**
> If OCR is ready, it pre-fills the boxes and reviewers just press Enter.
> If OCR isn't ready, reviewers type. The dashboard still works.

Build the console first. Then OCR failing on Thursday becomes a *speed* problem, not a *correctness* problem. With three days on the clock, that is the only sane risk posture.

### 10.3 Operations

- Forms will land over roughly 19:00 → 02:00. Two reviewers on a rota, one relief.
- Auto-publish handles the clean forms so humans only touch the hard ones; the human then confirms asynchronously and the badge upgrades from machine to human.
- Reviewer identity is logged per confirmation. Publish the reviewer count on the methodology page.

---

## 11. Intelligence layer — what makes it "world class"

A scoreboard is a commodity. These four things are not.

### 11.1 Reported-station bias correction

Urban streams report first — better network, closer to the tallying centre. Ol Kalou town does not vote like the Mirangine highlands. **Naive extrapolation from early returns is biased and will make you look foolish at 21:00.**

Correction: because `streams.json` gives you the full register up front, project **within ward strata**, weighting unreported streams by their registered voters. State this on the face of the dashboard: *"Projection is ward-stratified to correct for urban stations reporting first."* Say the quiet part out loud — it is exactly the kind of methodological transparency that earns trust.

### 11.2 Three-tier outstanding-vote model

Present all three. Never present only the model.

| Tier | Method | Claim strength |
|---|---|---|
| **T1 — Hard bound** | Every remaining registered voter turns out and votes for the runner-up. If `leader_margin > remaining_registered` → the race is **mathematically decided**. | Unassailable. No assumptions. |
| **T2 — Turnout-capped bound** | Cap remaining turnout at the 95th percentile of observed turnout. Same logic, tighter. | Very strong. |
| **T3 — Ward-stratified Monte Carlo** | Project each unreported stream from its ward's observed vote shares; sample from the observed station-level variance; 10k draws → credible interval on final margin + win probability. | A model. Label it as one. |

T3 reuses the Monte Carlo machinery already in the Kenya Election Intelligence Engine. Show the T1 hard bound **beside** the T3 probability, always. If they ever tell different stories, the hard bound wins.

**Plain-English output, not just a number:**

> *"Nyagah leads by 4,210 votes. 26 streams (18,900 registered voters) are outstanding. For Ngotho to overtake, he would need 62% of every remaining vote cast — he is currently averaging 34%. Estimated win probability: <1% (ward-stratified model, 10,000 simulations)."*

### 11.3 Bloc arithmetic — the signature analytical panel

Nine candidates. One government, eight opposition. FPTP. **The whole political question is whether the opposition splits itself out of a win**, exactly as it did in Mbeere North.

Panel: `UDA` vs `Σ(other eight)`, live, per ward and constituency-wide.

**Caveat, rendered directly in the UI, not buried:**

> *Bloc totals are arithmetic aggregations, not predictions. Voters are not transferable between parties; a consolidated opposition would not necessarily have received these votes. This panel shows what the sum is — not what would have happened.*

That caveat is not a weakness. It is the reason a serious reader will believe the rest of your dashboard.

### 11.4 Swing vs 2022

With `baseline_2022` in `streams.json`, render per-ward and per-stream swing against the 2022 result (Kiaraho / Jubilee). This is the only place anyone will be able to see *where* the political ground actually moved. That is intelligence, not reporting.

---

## 12. API contract — `live.json`

```json
{
  "schema": "olkalou.live.v2",
  "seq": 1287,
  "generated_at": "2026-07-16T21:05:12Z",
  "election": { "constituency": "OL KALOU", "code": "091", "date": "2026-07-16" },

  "status": "COUNTING",
  "pipeline_health": { "watcher": "OK", "extractor": "OK", "last_portal_ok": "2026-07-16T21:05:02Z" },

  "coverage": {
    "streams_total": 144,
    "published": 127,
    "in_review": 6,
    "conflicted": 0,
    "awaiting": 11,
    "excluded": { "count": 0, "reason": null },
    "registered_total": 72997,
    "registered_reported": 64120,
    "registered_pct": 0.8784
  },

  "totals": {
    "valid_votes": 41230,
    "rejected_votes": 512,
    "total_cast": 41742,
    "turnout_of_reported": 0.6510
  },

  "candidates": [
    { "ballot_no": 1, "name": "...", "party": "UDA", "bloc": "GOVERNMENT",
      "votes": 17204, "share": 0.4172, "swing_2022": 0.0810 }
  ],

  "blocs": {
    "GOVERNMENT": { "votes": 17204, "share": 0.4172 },
    "OPPOSITION": { "votes": 24026, "share": 0.5828 },
    "note": "Arithmetic aggregation only. Not a prediction of transfer behaviour."
  },

  "projection": {
    "leader": "UDA", "margin": 4210,
    "t1_hard_bound": { "remaining_registered": 8877, "mathematically_decided": false },
    "t2_capped_bound": { "max_remaining_votes": 6214, "decided": false },
    "t3_model": { "win_probability": { "UDA": 0.87, "DCP": 0.13 },
                  "margin_ci90": [1850, 6900],
                  "method": "ward-stratified MC, n=10000",
                  "assumptions_url": "/methodology#projection" }
  },

  "wards": [
    { "code": "0453", "name": "KARAU", "streams_total": 31, "published": 28,
      "registered": 15220, "registered_reported": 14010,
      "turnout": 0.6612, "candidates": { "UDA": 3901, "DCP": 4402 } }
  ],

  "streams": [
    {
      "stream_key": "091-0451-01",
      "station_name": "OL KALOU PRIMARY SCHOOL", "stream_no": 1, "ward": "KARAU",
      "state": "PUBLISHED",
      "verification": "HUMAN",
      "registered": 512,
      "votes": { "1": 201, "2": 154, "3": 0, "4": 0, "5": 0, "6": 0, "7": 0, "8": 0, "9": 3 },
      "rejected": 5, "valid": 358, "cast": 363, "turnout": 0.7090,
      "checks": { "V01": "PASS", "V02": "PASS", "V03": "PASS", "V05": "PASS", "V07": "PASS" },
      "form_url": "https://cdn.../raw/091-0451-01/v1_a3f9c1e2b0d4.jpg",
      "form_version": 1,
      "published_at": "2026-07-16T20:41:09Z"
    }
  ],

  "anomaly_feed": [
    { "at": "2026-07-16T20:58:03Z", "stream_key": "091-0472-01",
      "code": "V01", "severity": "CRITICAL",
      "message": "Candidate sum (402) ≠ PO stated valid votes (420). Held for review.",
      "form_url": "https://cdn.../raw/091-0472-01/v1_...jpg" }
  ],

  "corrections": [
    { "at": "2026-07-16T22:14:00Z", "stream_key": "091-0488-02",
      "field": "candidate_2", "from": 88, "to": 188,
      "reason": "IEBC uploaded amended Form 35A (v2).",
      "prior_form_url": "...", "new_form_url": "..." }
  ]
}
```

**Design notes on the schema:**
- `seq` is monotonic — the frontend rejects any payload with `seq` ≤ its current, which makes the dual-worker setup safe.
- `coverage` exposes the *whole* denominator picture, including what you're holding back. This is the honesty surface.
- `corrections[]` is append-only and **rendered publicly**. Never delete an entry.
- Every stream carries `form_url`. This is the promise in §1.1, made structural.

---

## 13. Frontend specification

### 13.1 Design thesis

**"The tallying wall."**

The physical reality of this election is a room in Ol Kalou where 144 paper forms arrive, get pinned up, and get added together. The dashboard should be that room — legible, forensic, made of paper and ink, with nothing decorative on it.

Reject the generic dashboard look: no KPI cards with gradient accents, no donut charts, no chart library. Hand-built SVG, as in your existing work.

### 13.2 Tokens

```css
:root{
  /* Ground: election night. Watched in the dark, on a phone. */
  --ground:    #0E1116;   /* deep slate, not pure black */
  --surface:   #171C24;   /* raised panel */
  --rule:      #2A323D;   /* hairline — the printed grid of the form */

  --ink:       #E8EAED;   /* primary text        — 14.2:1 on ground ✓AAA */
  --ink-dim:   #98A2B0;   /* secondary           —  6.1:1 ✓AA   */
  --carbon:    #5F6A78;   /* AWAITING / empty box — 3.4:1 ✓AA-large / graphical */

  /* Verification states — the semantic core of the product */
  --verified:  #3FA76B;   /* human-verified   */
  --machine:   #5C8FC7;   /* machine-verified — biro blue */
  --review:    #D9873A;   /* in review        */
  --breach:    #D9534F;   /* CRITICAL failed  */

  /* Candidate colours live in candidates.json, contrast-checked at build. */
}
```

Every token contrast-verified against `--ground` at WCAG AA. Same discipline as the Kazi Sasa v4 token pass. Never introduce a colour in a component.

### 13.3 Type

Three roles, deliberately chosen — an *instrument*, not a magazine:

- **Display:** `Space Grotesk 700` — geometric grotesque with enough character to carry the hero tally without reading as editorial-generic.
- **UI / body:** `IBM Plex Sans` — civic, institutional, excellent at small sizes.
- **Data:** `IBM Plex Mono` — the ledger. **Every number in the interface is set in tabular figures.** Non-negotiable: figures change in place all night, and non-tabular numerals make them jitter, which reads as instability. `font-variant-numeric: tabular-nums;` on every numeric element.

### 13.4 Signature element — **the Stream Grid**

144 cells, grouped into five ward blocks. Each cell is a small square with a hairline border — visually, an unfilled box on a form.

- `AWAITING` → hollow, `--carbon` hairline.
- `PUBLISHED` → filled with the leading candidate's colour; **opacity encodes margin** (a knife-edge stream is pale; a landslide is saturated).
- `IN REVIEW` → `--review` diagonal hatch.
- `CONFLICTED` → `--breach` border, pulsing once.
- **Click any cell → the scanned Form 35A opens beside the extracted figures and the check results.**

The grid *is* the tallying wall. It fills up over the night. It is the one thing people will screenshot, and it makes the product's thesis visible in a single glance: 144 boxes, and you can open every one.

Spend your boldness here. Everything else stays quiet.

### 13.5 Layout

Mobile-first — assume the majority of Kenyan traffic is on a phone at 360px, on patchy data, in the dark.

```
MOBILE (360px)                    DESKTOP (≥1024px)
┌──────────────────┐              ┌─────────────┬────────────────┬──────────────┐
│ ⚠ UNOFFICIAL     │              │ ⚠ UNOFFICIAL — parallel tally. Not a declaration.│
├──────────────────┤              ├─────────────┼────────────────┼──────────────┤
│  RESULT BAR      │              │  RESULT BAR │  STREAM GRID   │  PROJECTION  │
│  (9 candidates,  │              │  9 cands,   │  144 cells,    │  T1 bound    │
│   ranked, live)  │              │  ranked     │  5 ward blocks │  T3 model    │
├──────────────────┤              │             │                │  Bloc panel  │
│  COVERAGE STRIP  │              │  Coverage   │  ← signature   │              │
│  127 · 6 · 11    │              │  Turnout    │                │  Anomaly     │
├──────────────────┤              │  Swing '22  │                │  feed        │
│  STREAM GRID     │              ├─────────────┴────────────────┴──────────────┤
├──────────────────┤              │  STREAM TABLE — sortable, filterable,       │
│  PROJECTION      │              │  every row → the scanned form               │
├──────────────────┤              ├─────────────────────────────────────────────┤
│  STREAM TABLE    │              │  CORRECTIONS LOG (append-only, public)      │
└──────────────────┘              └─────────────────────────────────────────────┘
```

### 13.6 Non-negotiable behaviours

- **Staleness is visible.** If `generated_at` is >3 min old: banner turns amber, `LAST UPDATED 4m ago`. >10 min: red, `FEED STALE — WE ARE NOT RECEIVING UPDATES`. **Never show a stale number as if it were fresh.** This is the most common failure of live dashboards and it is unforgivable.
- **Last-known-good.** On fetch failure, keep rendering the last payload with the stale banner. Never blank the screen.
- **Reject stale payloads.** Ignore any `seq` ≤ current.
- **Motion, used once.** A newly published stream "stamps" into the grid (120ms scale + colour bloom). The anomaly feed slides. Nothing else moves. Respect `prefers-reduced-motion`.
- **Numbers animate by counting, never by fading.** A tally that fades between values looks like it is guessing.
- Keyboard focus visible. Grid cells are real buttons. The stream table is a real `<table>`.

### 13.7 Copy

Plain, active, never triumphal.

- ✅ "Nyagah leads by 4,210 votes with 11 streams outstanding."
- ✅ "6 forms held for review — figures excluded from the total until verified."
- ✅ "This form failed the candidate-sum check. It is not counted. Open it and see for yourself."
- ❌ "WINNER" · ❌ "PROJECTED WINNER" · ❌ "TOO CLOSE TO CALL"
- The permitted strong statement is: **"MATHEMATICALLY DECIDED"** — and only when T1 (the hard bound, zero assumptions) says so.

---

## 14. Legal, ethical and editorial posture

Kenya prosecutes election offences. Publishing a wrong number on a contested by-election night, in a constituency where IEBC has already raised concerns about violence, is a real risk to real people. Take it seriously.

### Rules

1. **Persistent header on every page:**
   > **UNOFFICIAL — Independent parallel tally compiled from IEBC-published Form 35A scans. Only the Returning Officer may declare the result of this election.**
2. **Never declare.** The words *winner*, *declared*, and *elected* do not appear on the site until the Returning Officer declares. Use *leads* and *mathematically decided*.
3. **Publish the methodology page before polls close**, not after. Check definitions, projection assumptions, OCR accuracy figures from the dress rehearsal, and the names/count of the human reviewers.
4. **Corrections are loud and permanent.** A visible, append-only corrections log is the only thing that survives getting one wrong — and over 144 handwritten forms, you will get one wrong.
5. **Cite IEBC as the source of every figure**, and link to the source scan. You are a verifier, not an originator.
6. Consider whether Presiding Officers' names on the scans need redaction on your mirror. They appear on a public official document, but you are re-publishing at scale; think about it before Thursday rather than after.
7. Confirm the precise citations (Elections Act, 2011 §39; Elections (General) Regulations, 2012) with someone who knows before you print a section number on a public page. Get the principle right in the copy; get the citation right in the footnotes.

---

## 15. Observability & election-night runbook

### 15.1 Alerts (to your phone, not a log file)

| Trigger | Action |
|---|---|
| Portal returns non-200 for 3 consecutive ticks | Page |
| Parser finds 0 Ol Kalou rows after 19:00 | Page (this is the silent-failure canary) |
| Worker heartbeat missing >3 min | Page — failover to worker B |
| Any CRITICAL check fails | Notify reviewer channel |
| Review queue depth >10 | Notify reviewer channel |
| `seq` not advancing for >5 min while forms are pending | Page |

### 15.2 Election-night timeline

| Time (EAT) | Expected |
|---|---|
| 06:00 | Polls open. Dashboard live in `PRE-POLL` state, showing the register, candidates, 2022 baseline, and 144 hollow cells. |
| 17:00 | Polls close. State → `COUNTING`. Queued voters still voting. |
| 18:00–20:00 | Counting at stations. **Expect zero forms.** Show "IEBC has published 0 of 144 forms" — that is information, not a bug. |
| 20:00–02:00 | Forms arrive in bursts. Reviewers on rota. Peak load. |
| 02:00–08:00 | Long tail. Rural streams. Possible amendments. |
| Post-declaration | RO declares. Ingest **Form 35B**. Run the reconciliation (§18). |

### 15.3 Freeze

**Code freeze: 12:00 EAT, Thursday 16 July.** After that, config changes only. You will want to ship one more feature at 19:30. Do not.

---

## 16. Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | OCR accuracy insufficient | **High** | High | Review console with double-entry works with zero OCR. Build it first. |
| R2 | Silent scraper failure after portal HTML change | Medium | **Critical** | Structural assertion + 19:00 canary + page alert. |
| R3 | IEBC uploads slowly or not at all | Medium | Medium | Report it honestly on the face of the dashboard. IEBC's upload rate *is* a story. |
| R4 | Station disruption / postponement (IEBC has flagged violence concerns) | Medium | Medium | `DISRUPTED`/`POSTPONED` states; denominator adjusts visibly. |
| R5 | Worker dies at 23:00 | Medium | **Critical** | Two workers, two regions, monotonic `seq`, heartbeat alerting. |
| R6 | Traffic spike | Medium | Medium | Static JSON on CDN. Nothing dynamic on the critical path. |
| R7 | IEBC publishes an amended form contradicting a published figure | Medium | High | Immutable versions + public corrections log + `CONFLICTED` state. |
| R8 | You are asleep at 02:00 | **High** | Medium | Auto-publish clean forms; two-person reviewer rota; queue drains in the morning with badges upgrading. |
| R9 | 142/144 stream-vs-station confusion | **High** | High | Resolve today. Key on `(station_code, stream_no)`. §2.3. |
| R10 | Publishing a wrong number | Medium | **Critical** | The entire §8–§10 apparatus exists for this. Plus a loud corrections log. |
| R11 | Legal/reputational exposure | Low | High | §14. Never declare. Never claim fraud. Always link the source. |

---

## 17. Build plan — T-3

You have a day job at Nithio. Be ruthless.

### If you only do three things

1. **Build `streams.json` from the certified register.** Everything — the denominator, V07, the projection frame, the grid — depends on it. Nothing works without it.
2. **Archive every form image the instant you see it.** You become the permanent system of record for this by-election. This alone is worth doing.
3. **Human-confirm every form before it hits the headline number.** Never publish a figure no person has looked at.

Do those three and the project is a credible public good. Skip any one and it is a liability.

### Day plan

**Mon 13 Jul (today)**
- Obtain the certified candidate list + ballot order from IEBC. Resolve the DCP candidate-name conflict. → `candidates.json`
- Obtain the by-election register per polling stream. Resolve 142 vs 144. → `streams.json`
- Pull the **2022 Ol Kalou 35A set** from the portal → gives you `baseline_2022` *and* your OCR reference template.
- Ship the **pre-poll page**: candidates, wards, register, 2022 baseline, 144 hollow cells, methodology stub. Public today. It builds the audience and de-risks everything — even total pipeline failure leaves a useful public artifact standing.

**Tue 14 Jul**
- Watcher + archiver against the live portal (currently 0 of 144). Conditional GET, backoff, manifest.
- Pull the **Emurua Dikirr** 35A corpus (§5.3).
- Build the Form 35A ROI template. Wire Google Cloud Vision. Per-cell crop + numeric charset constraint.
- **Measure per-field accuracy on the Emurua Dikirr forms against the declared result. Write `accuracy_report.md`.** This number decides your Thursday posture.

**Wed 15 Jul**
- **Review console + double-entry.** Non-negotiable. If Tuesday's accuracy was poor, this is the whole pipeline.
- Validation engine V01–V07. Calibrate V05's rejected-rate band from the Emurua Dikirr data.
- Publisher + `live.json` + dual-worker `seq` guard.
- **Full dress rehearsal:** replay all Emurua Dikirr forms through watcher → archive → extract → validate → publish → dashboard. Confirm you reproduce the declared totals. Fix what breaks.
- Alerting: Telegram/Slack webhook wired to your phone. Test it by killing the worker.

**Thu 16 Jul**
- **12:00 — code freeze.** Final rehearsal. Brief the reviewers. Sleep in the afternoon.
- 17:00 — polls close. 20:00 — the night begins.

**Fri 17 Jul**
- Ingest Form 35B. Publish the reconciliation report (§18).

### MoSCoW

| | |
|---|---|
| **MUST** | `streams.json` · `candidates.json` · watcher · archiver · review console w/ double-entry · V01–V05, V07 · static dashboard (result bar, stream grid, coverage, stream table w/ form links) · disclaimers · methodology page · stale indicator · last-known-good |
| **SHOULD** | OCR pre-fill (GCV + ROI crops) · T1 hard bound · bloc arithmetic panel · anomaly feed · 2022 swing |
| **COULD** | Dual-engine consensus · T3 Monte Carlo + win probability · ward cartogram · V11/V12 |
| **WON'T** | Sub-minute refresh guarantee · WebSockets · auth · any database migration · a mobile app |

---

## 18. The post-election deliverable — the thing that actually lasts

By Friday, publish **`RECONCILIATION.md`**:

1. Σ of all 144 verified Form 35As, per candidate.
2. The Returning Officer's declared Form 35B figures, per candidate.
3. **The delta.** Zero, or not zero.
4. Every check that failed, with a link to the scan.
5. Measured OCR accuracy, honestly reported.
6. The complete archive of all 144 forms, permanently hosted.
7. Every correction made during the night.

If it reconciles: you have independently verified a Kenyan by-election, in public, with receipts. If it doesn't: you have found a discrepancy and you can prove it.

Election-night dashboards are forgotten by Friday. **A permanent, verifiable, public archive of every result form in a contested by-election is not.** That is the artifact. Build the dashboard, but build it as a means to that end.

---

## Appendix A — Open items to close before Thursday

- [ ] Certified candidate list + ballot order (resolve DCP name conflict)
- [ ] Certified register per polling stream — and the 142/144 answer
- [ ] Exact Form 35A layout for this by-election (row count = 9 candidates)
- [ ] IEBC portal URL pattern for Ol Kalou 35A / 35B
- [ ] Rejected-ballot rate band, calibrated from Emurua Dikirr
- [ ] Party colours, contrast-checked at AA against `--ground`
- [ ] Reviewers recruited and briefed (2 + 1 relief)
- [ ] Alerting tested by deliberately killing the worker
- [ ] Legal citations verified before they appear on a public page

## Appendix B — Dress-rehearsal corpora with known ground truth

| Election | Date | Portal | Declared result (for validation) |
|---|---|---|---|
| **Emurua Dikirr** (MP) | 14 May 2026 | forms.iebc.or.ke | Keter (UDA) 18,266 · Rotich (DCP) 10,760 · 29,538 of 44,353 · 66.6% |
| Mbeere North (MP) | 27 Nov 2025 | forms.iebc.or.ke | Published |
| Kasipul (MP) | 27 Nov 2025 | forms.iebc.or.ke | Published |
| Malava (MP) | 27 Nov 2025 | forms.iebc.or.ke | Published |
| Magarini (MP) | 27 Nov 2025 | forms.iebc.or.ke | Published |
| **Ol Kalou 2022** (MP) | 9 Aug 2022 | forms.iebc.or.ke | Kiaraho (Jubilee) — also yields `baseline_2022` |

Six labelled datasets. Use them. Any OCR accuracy claim you cannot measure against these is a guess.
