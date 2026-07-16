# Ol Kalou Election-Day Public Conversation Observatory

**Status:** GitHub-ready educational specification  
**Election:** Ol Kalou Parliamentary By-Election  
**Election day:** 16 July 2026  
**Deployment target:** Existing `dansamuka/2_Elections_tallying_educational` repository, under `/sentiment/`  
**Purpose:** Educational analysis of public conversation, news framing, candidate mentions, and the election environment. It is **not** an opinion poll, vote forecast, official results service, or campaign tool.

## 1. Executive summary

The observatory collects election-related material from:

1. **X public search**, using an app bearer token.
2. **The authenticated account's reverse-chronological home timeline**, using user-context authentication when the user chooses to connect their private X account.
3. **News articles**, initially through the GDELT DOC 2 API and optional curated RSS feeds.
4. **Manual verified incident notes**, if enabled, for events such as polling delays, violence, accessibility problems, misinformation, or official announcements.

The pipeline removes or hashes direct identifiers, deduplicates content, classifies language and topic, estimates sentiment, calculates confidence, and publishes only aggregated JSON to GitHub Pages. Each scheduled run requests the new time interval after the last public collection cursor and merges aggregate counts, allowing an election-day cumulative view without committing raw source content. Protected-post text, usernames, account IDs, access tokens, and raw private timeline exports are never published.

## 2. Current election context

IEBC scheduled the Ol Kalou Parliamentary By-Election for 16 July 2026. Contemporary reporting identifies nine cleared candidates and five wards. The configuration supplied with this package includes the following candidate aliases:

| Candidate | Party |
|---|---|
| Samuel Muchina Nyagah | UDA |
| Sammy Kamau Ngotho | DCP |
| Wilson Kigwa | Jubilee Party |
| Timothy Kamau | People's Renaissance Movement |
| Edwin Muchiri | PNU |
| Stephen Wanyoike Waithaka | National Liberal Party |
| Rachael Wangui Njoroge | People's Democratic Party |
| Edward Mathenge / Edward Mwaniki | Kenya Moja Movement |
| Abdifatah Hussein Abdullahi | Federal Party of Kenya |

Names and aliases must remain configuration-driven because news outlets may use shortened or inconsistent forms.

## 3. Ethical and legal guardrails

### 3.1 Required public notice

Every dashboard page must state:

> This dashboard measures online discussion, not voter intention. X users and news coverage are not representative of Ol Kalou voters. Sentiment models can misread sarcasm, Kikuyu, Kiswahili, Sheng, names, quotations, and political slogans. Official election information and results come from IEBC.

### 3.2 Protected-content rules

- Protected posts may only be processed for the authenticated account that is authorised to view them.
- Do not publish protected-post text, screenshots, usernames, profile images, post IDs, or links.
- Do not create a public archive of a private timeline.
- Publish only aggregates after minimum-group thresholds are met.
- Default threshold: do not display a candidate-topic cell containing fewer than five independent items.

### 3.3 Election-integrity rules

- No “predicted winner” indicator.
- No conversion of sentiment share into projected vote share.
- No microtargeting, ward-level persuasion, or demographic inference.
- No automated allegations against named individuals.
- Potential violence, bribery, intimidation, or fraud content is labelled **unverified claim** until a credible source or human reviewer confirms it.
- The dashboard must visually distinguish `reported`, `corroborated`, and `officially confirmed` events.

## 4. User experience and dashboard modules

### 4.1 Header and freshness

- Election-day clock in East Africa Time.
- Last successful X refresh, news refresh, and analysis build.
- Data-source health indicators.
- Prominent methodology and limitations link.

### 4.2 Core scorecards

- Total relevant items processed.
- X items and news items.
- Unique source estimate.
- Share of duplicated/reposted content.
- Overall conversation balance: positive, neutral, negative, and unscored.
- Model confidence and language coverage.

### 4.3 Candidate conversation panel

For each candidate:

- Mention share.
- Positive/neutral/negative composition.
- Net sentiment index, from -100 to +100.
- Source mix: X versus news.
- Momentum over time.
- Confidence badge.

Mention share and sentiment must be presented independently. High visibility is not equivalent to support.

### 4.4 Election environment panel

Topics:

- Polling process and IEBC administration.
- Turnout and queues.
- Peace, security, violence, and intimidation.
- Bribery, inducements, and misuse of public resources.
- Accessibility and voter assistance.
- Misinformation and disputed claims.
- Results, tallying, and transparency.
- Roads, transport, electricity, and polling logistics.
- Local economy, farming, dairy, potatoes, markets, jobs, and development.
- Weather and physical polling conditions.

### 4.5 News framing panel

- Article count by outlet.
- Candidate prominence by outlet.
- Topic prominence.
- Headline sentiment, separate from article-body sentiment.
- Recent article list containing title, source, timestamp, and link only; no republishing of full articles.

### 4.6 Coordination and quality panel

- Exact-duplicate rate.
- Near-duplicate cluster count.
- Repost share.
- Source concentration.
- Sudden-volume anomaly flags.
- Unsupported language share.
- Sampling and API-limit warnings.

These indicators detect unusual activity; they do not prove bots or coordinated manipulation.

## 5. System architecture

```text
X API / GDELT / RSS / manual notes
              │
              ▼
      private raw ingestion
 data/private/sentiment/*.jsonl
              │
              ▼
 normalise → deduplicate → redact → classify
              │
              ▼
  aggregate + confidence + quality checks
              │
              ▼
 data/public/sentiment/latest.json
              │
              ▼
 docs/sentiment/index.html on GitHub Pages
```

### 5.1 Separation from the tallying engine

This module is an add-on to the existing election repository. It must not:

- modify provisional or verified vote totals;
- write to the OCR review database;
- infer results from sentiment;
- delay the realtime tallying pipeline.

The only integration should be navigation links and a shared election identifier: `ol-kalou-2026`.

## 6. X account connection

### Option A — Public-search mode

Use `X_BEARER_TOKEN` and the recent search endpoint. This is the simplest mode and accesses public X data only.

### Option B — Authenticated private-account mode

For the account owner’s own project, configure OAuth user-context credentials as GitHub repository secrets:

- `X_API_KEY`
- `X_API_SECRET`
- `X_ACCESS_TOKEN`
- `X_ACCESS_TOKEN_SECRET`
- `X_USER_ID`

The collector calls the reverse-chronological home timeline and filters locally for Ol Kalou terms. This allows the app to act as the authorised account, subject to the account’s permissions and X developer access. It reads the home timeline available to that account; it does not provide access to direct messages or to protected accounts the user is not authorised to view. X API usage should be given a conservative page limit and spending cap because current access is credit-based.

**Important:** A static GitHub Pages page cannot safely perform OAuth or hold tokens. Authentication and collection must happen inside GitHub Actions or another private backend. Only aggregate JSON reaches Pages.

### Search query design

The default query includes:

```text
("Ol Kalou" OR OlKalou OR #OlKalou OR #OlKalouByElection)
AND election-related terms
NOT obvious spam terms
```

Candidate aliases and local place names are added from `config/sentiment_config.json`.

## 7. Analysis methodology

### 7.1 Relevance

An item is relevant when it contains:

- an Ol Kalou place or election phrase; and
- at least one election, candidate, polling, IEBC, turnout, security, bribery, tallying, or local-development term.

### 7.2 Deduplication

- Normalise URLs, case, whitespace, mentions, and repeated punctuation.
- Hash normalised text.
- Group exact duplicates.
- Use token-set similarity for near duplicates.
- Keep one canonical item and a frequency count.

### 7.3 Language

Initial labels: English, Kiswahili, mixed, Kikuyu/other, and unknown. The lightweight GitHub version uses pattern-based detection. A future server-backed version may add a multilingual model, but unsupported content must be reported rather than silently forced into a score.

### 7.4 Sentiment

The default pipeline combines:

- VADER for English polarity;
- a small election-specific Kiswahili and Kenyan-English lexicon;
- negation handling;
- quotation and headline cautions;
- an `unscored` state for low-confidence language.

Output labels:

- positive: score ≥ +0.20
- neutral: -0.20 < score < +0.20
- negative: score ≤ -0.20
- unscored: insufficient language/model confidence

### 7.5 Candidate attribution

A post may mention multiple candidates. Each candidate receives a mention, but the system must avoid assigning one sentence’s sentiment to every person named in a list. The lightweight version assigns document sentiment; the enhanced version performs sentence-level target sentiment.

### 7.6 Confidence

Candidate confidence is calculated from:

- item volume;
- unique-source estimate;
- source diversity;
- duplicate penalty;
- language coverage;
- X/news balance;
- recency.

Confidence labels are `low`, `moderate`, or `higher`, never “certain”. The cumulative unique-source metric is an upper-bound estimate because the public payload intentionally does not retain author-level identifiers needed to reconcile the same author across separate refresh windows.

## 8. Public JSON contract

`data/public/sentiment/latest.json` contains:

```json
{
  "meta": {
    "election_id": "ol-kalou-2026",
    "generated_at": "ISO-8601",
    "collection_cursor": "ISO-8601",
    "mode": "live|demo|partial",
    "disclaimer": "..."
  },
  "summary": {},
  "timeline": [],
  "candidates": [],
  "topics": [],
  "sources": [],
  "articles": [],
  "quality": {},
  "alerts": []
}
```

Raw post text and user identifiers are prohibited in the public contract.

## 9. GitHub Actions operation

- `workflow_dispatch` enables manual refresh.
- Scheduled refresh runs every 15 minutes at offset minutes to reduce top-of-hour congestion.
- The previous public `collection_cursor` becomes the next X/news start time, and only aggregate deltas are merged into the cumulative payload.
- If a configured collector fails, the run does not advance the cursor, reducing the risk of a silent data gap.
- Scheduled collection exits outside the configured observation window; a manual workflow run may override the window for testing or post-election research.
- Secrets are read only by the ingestion job.
- Generated public JSON is committed with `[skip ci]` to prevent loops.
- Pages serves static files from the existing repository’s configured publishing source.

## 10. Secrets and setup

Required for public X search:

```text
X_BEARER_TOKEN
```

Additional secrets for authenticated account mode:

```text
X_API_KEY
X_API_SECRET
X_ACCESS_TOKEN
X_ACCESS_TOKEN_SECRET
X_USER_ID
```

Optional repository variables:

```text
SENTIMENT_X_MODE=public_search|private_home|hybrid
```

## 11. Validation and tests

Minimum acceptance tests:

1. No secret value appears in logs, generated files, or HTML.
2. Public JSON contains no raw X post text, username, user ID, post ID, or protected-post URL.
3. Candidate aliases resolve correctly.
4. Multi-candidate list posts do not create false candidate-specific polarity in enhanced mode.
5. Duplicate waves affect volume but not unique-source metrics.
6. Unsupported language is labelled unscored.
7. Fewer than five independent items suppress a granular cell.
8. Dashboard loads in demo mode when the live JSON is unavailable.
9. GitHub Pages path works under a repository subdirectory.
10. The module does not modify tallying outputs.

## 12. Implementation phases

### Phase 0 — Safe shell

Dashboard, demo payload, configuration, disclaimers, public schema, and push scripts.

### Phase 1 — Public X and news

Recent public X search, GDELT articles, deduplication, lightweight sentiment, topic classification, and scheduled aggregate publishing.

### Phase 2 — Private account connection

User-context home timeline, private-data retention rules, protected-content suppression tests, and secret rotation guide.

### Phase 3 — Accuracy uplift

Human-labelled Ol Kalou sample, multilingual target sentiment, sarcasm review, better candidate disambiguation, and calibration report.

### Phase 4 — Incident verification

Reviewer console for election-environment claims, corroboration workflow, source audit trail, and official-confirmation tags.

### Phase 5 — Historical research

Post-election frozen dataset of aggregates, methodology report, model-error analysis, and comparison with official results without claiming causation.

## 13. References

- IEBC election preparedness and election date: https://www.iebc.or.ke/news/
- X API authentication overview: https://docs.x.com/fundamentals/authentication/overview
- X OAuth 2.0 PKCE: https://docs.x.com/fundamentals/authentication/oauth-2-0/user-access-token
- X app-only authentication: https://docs.x.com/fundamentals/authentication/oauth-2-0/application-only
- X recent search: https://docs.x.com/x-api/posts/search-recent-posts
- X developer policy: https://docs.x.com/developer-terms/policy
- GitHub Actions secrets: https://docs.github.com/actions/security-guides/using-secrets-in-github-actions
- GitHub scheduled workflows: https://docs.github.com/actions/using-workflows/events-that-trigger-workflows
- GitHub Pages custom workflows: https://docs.github.com/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- GDELT DOC 2 API: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
