# Reference-data certification checklist

## Streams/register

- [ ] Source is the by-election Gazette/certified register, not a 2022 aggregator.
- [ ] Exactly 144 atomic rows.
- [ ] Every `stream_key` is unique and encodes the official station code plus stream number.
- [ ] Duplicate station names are allowed only when distinguished by code/stream.
- [ ] Every row has ward code/name and registered voters.
- [ ] Row sum equals 73,480.
- [ ] Ward row counts and registered totals reconcile to the official ward summary.
- [ ] Operator 1 transcribed; operator 2 independently checked.
- [ ] Source URL, Gazette number/date and review identities recorded.

## Candidates

- [ ] Exactly nine candidates.
- [ ] Legal names copied from the certified candidate list.
- [ ] Ballot positions/Form 35A row order 1–9 checked against the actual form.
- [ ] Party abbreviation and bloc assignment reviewed.
- [x] Every colour has ≥3:1 contrast on `#0E1116`; text use should meet ≥4.5:1. — **Verified 13 Jul 2026**, computed WCAG relative-luminance contrast for all 9 `data/reference/candidates.json` colours against `#0E1116`. Lowest is Wilson Kigwa `#E85D5D` at 5.54:1; all 9 clear both the 3:1 and 4.5:1 thresholds. Re-run this check if any colour changes.
- [ ] `source_verified` and `ballot_order_verified` set true only after review.

## 13 Jul 2026 audit note

Two items above moved from "unverified guess" to "corroborated but still
correctly gated closed": the register TOTAL (73,480) is now backed by an
on-record quote from Returning Officer Anthony Njiraini (Daily Nation), and
the candidate roster (names/parties/9-candidate count) is corroborated
across seven independent outlets. Neither of these flips `source_verified`,
`ballot_order_verified`, or `register_source_verified` to true — those still
require the actual certified documents, not press corroboration, and
`check-reference` still correctly exits 1 until they're done. See
`data/reference/streams.json` and `data/reference/candidates.json` for the
full citations, and `scripts/apply_audit_fixes_13jul.py` for exactly what
changed and why.

## Final gate

```bash
python -m olkalou_engine.cli --root . check-reference
```

Proceed only when it exits zero and reports no errors.
