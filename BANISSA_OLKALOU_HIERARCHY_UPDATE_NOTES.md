# Banissa + Ol Kalou IEBC hierarchy update

This replacement package updates the existing repository `dansamuka/2_Elections_tallying_educational`.
It does not create a new repository.

## Election targets

The five-minute workflow now checks both:

- `banissa-2025` — archived election, 81 expected Form 35As.
- `ol-kalou-2026` — live/pre-poll election, 144 expected Form 35As.

## Ol Kalou route

The crawler is configured to follow only:

`KENYA → NYANDARUA → OL KALOU → ward → polling centre → polling stream → cloud download`

The current constituency row is pinned to IEBC row id `141`. The five ward expectations are:

| Ward | Expected forms |
|---|---:|
| Rurii | 33 |
| Kanjuiri Range | 32 |
| Karau | 27 |
| Kaimbaga | 27 |
| Mirangine | 25 |
| **Total** | **144** |

The crawler ignores every `Download All` control and every eye/preview link. Only the individual cloud-download action at the polling-stream leaf is accepted.

## Publication gate

Ol Kalou's constituency and ward totals are staged, but its certified 144 atomic register rows and final Form 35A candidate order remain gated. The workflow may archive and OCR forms, but OCR results remain review-only and cannot automatically alter the candidate tally.

## Website behavior

- Ol Kalou is the default entry on the election archive/explorer because it is the newest configured contest.
- The archive page displays portal-downloaded forms even when they cannot yet be matched to certified stream rows.
- The live homepage includes `Update IEBC now` and `Refresh data` controls.
- `UPDATE_OL_KALOU_NOW.cmd` triggers only the Ol Kalou workflow target.

## Validation

The package includes regression tests for:

- current Ol Kalou `0 of 144` index parsing;
- Kenya → Nyandarua selection;
- Nyandarua → Ol Kalou selection;
- all five Ol Kalou wards and the 144-form total;
- individual cloud-link selection at a polling-stream leaf;
- rejection of preview and Download All controls;
- incomplete atomic-reference publication blocking;
- Banissa behavior remaining intact.
