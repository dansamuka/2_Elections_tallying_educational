# Addendum: Early Alert Capability
**Applies to:** `SPECIFICATION.md` (Ol Kalou Election-Day Public Conversation Observatory)
**Adds to sections:** 3.3, 4.4, 4.6, 8, 9, 11
**Does not change:** Section 5.1 separation-of-concerns rules (still no writes to tallying/OCR pipeline, still no vote-share inference)

## Why an addendum, not a new module

The base spec already has almost everything an alert system needs — it just doesn't fire yet:

- The `reported / corroborated / officially confirmed` distinction (3.3) is a severity ladder waiting to be used.
- The `alerts: []` array already exists in the public JSON contract (Section 8) but has no schema.
- Section 4.4's environment topics (security, bribery, misinformation, logistics) are the natural alert categories.
- Section 4.6's anomaly detection (duplicate rate, sudden-volume flags) is the natural trigger signal.

So this addendum specifies **trigger logic, corroboration rules, a minimal human-review hook, and a delivery path** — without touching the ingestion/dedup/sentiment pipeline itself.

## A. New alert typology (extends 4.4)

| Category | Source topics | Example |
|---|---|---|
| `admin` | polling process, IEBC administration, turnout/queues | Reports of a station opening late |
| `security` | peace/security/violence/intimidation | Reports of a scuffle at a polling station |
| `integrity` | bribery, inducements, misuse of resources | Reports of vote-buying |
| `misinformation` | misinformation and disputed claims | A viral false claim about results or eligibility |
| `logistics` | roads, transport, electricity, polling logistics | Power outage affecting a tallying centre |

Alerts should **never** carry a `results`/`tallying` category — that stays strictly out of scope per Section 5.1.

## B. Severity ladder (formalizes 3.3's status distinction)

1. **`watch`** — a single-source signal crosses the volume/anomaly threshold. Internal only; not shown on the public dashboard.
2. **`reported`** — promoted from `watch` once corroboration criteria (below) are met. Shown publicly, clearly labelled unverified.
3. **`corroborated`** — a second independent source type or a credible outlet confirms. Still not "true", just less isolated.
4. **`officially_confirmed`** — IEBC, police, or another named authority statement is logged against it (manually, by a human reviewer — never auto-inferred).
5. **`retracted`** — later evidence contradicts it. The item stays visible with its history rather than silently disappearing (this matters for your own credibility — a disappearing alert looks like a cover-up more than a wrong one).

**Promotion `watch → reported` requires all of:**
- Item count over rolling window exceeds a category-specific floor (higher than the generic Section 3.2 five-item display floor — recommend a separate, larger constant for `security`/`integrity`, since false alarms in those categories carry higher cost)
- Items originate from ≥2 independent sources (two different X accounts + one outlet, or similar) — this is the actual corroboration test, not just count
- Topic-classifier confidence for `security`/`integrity` categories cleared at a stricter threshold than the default topic threshold, precisely to keep a single sarcastic or joking post from tripping a "violence" alert

No fully-automated path exists to `officially_confirmed` — that transition is manual only.

## C. Human-in-the-loop hook (pulls a slice of Phase 4 forward)

Waiting for the full Phase 4 reviewer console before any alert goes live on election day is risky. Recommend a minimal stopgap shippable in Phase 1:

- `config/incident_overrides.json` — a small, hand-edited file a trusted human (you, or someone you designate) can update to force-promote, demote, retract, or annotate any alert `id`, independent of the automated pipeline.
- The build step reads this file last and it always wins over the automated status. This gives you a manual kill-switch/override without building the full console under time pressure.

## D. Delivery (new subsection, 4.7 "Early Alert Panel")

- **Public dashboard:** a dedicated panel, always showing the severity label and a fixed disclaimer distinct from the general one:
  > "Alerts reflect volume and repetition in public conversation, not confirmed events. Only entries marked 'officially confirmed' have been verified by an authority."
- **No public push/amplification.** The dashboard should be pull-only (loads on refresh). Do not auto-post alerts to any public social account — that would make the tool itself a vector for spreading an unverified claim.
- **Private notification (optional, for your own monitoring):** a GitHub Actions step can post `reported`+ severity alerts to a private channel (e.g., a webhook to a Slack/Telegram channel only you or your reviewers are in). This is for *your* situational awareness, not public broadcast.
- **Refresh cadence:** Section 9 currently sets a flat 15-minute cycle. Recommend tightening to 5 minutes during the observation window on election day itself, reverting to 15 minutes outside active voting hours — since alert latency matters more than dashboard latency in general.

## E. JSON contract detail (fills in Section 8's empty `alerts: []`)

```json
"alerts": [
  {
    "id": "string",
    "category": "admin|security|integrity|misinformation|logistics",
    "status": "reported|corroborated|officially_confirmed|retracted",
    "first_seen": "ISO-8601",
    "last_updated": "ISO-8601",
    "item_count": 0,
    "independent_source_count": 0,
    "confidence": "low|moderate|higher",
    "summary": "neutral, non-accusatory, no named individuals unless already named by a credible public source",
    "override_applied": false
  }
]
```
No `ward` or geolocation field unless a source explicitly states it — never inferred, per the existing no-microtargeting rule in 3.3.

## F. Test additions (extends Section 11)

11. An alert does not reach `reported` on single-source volume alone (corroboration-count test).
12. `security`/`integrity` alerts respect the stricter topic-confidence threshold.
13. An alert's public JSON contains no named individual unless that name already appears in a credible public source cited in the item.
14. A `retracted` alert remains visible with status history rather than being deleted.
15. `config/incident_overrides.json` correctly overrides the automated status on the next build.
16. No alert of any category ever contains a `results`/`tallying`-adjacent field.

## G. One open decision for you

Given today is election day itself, the two things worth deciding now rather than mid-build:
- Who besides you (if anyone) can edit `incident_overrides.json` during the live window?
- Do you want the private webhook notification wired up today, or is the public panel with manual override enough for this election?
