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
- [ ] Every colour has ≥3:1 contrast on `#0E1116`; text use should meet ≥4.5:1.
- [ ] `source_verified` and `ballot_order_verified` set true only after review.

## Final gate

```bash
python -m olkalou_engine.cli --root . check-reference
```

Proceed only when it exits zero and reports no errors.
