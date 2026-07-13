# Validation report

Validated on 13 July 2026 against the existing-repository update source tree.

| Check | Result |
|---|---|
| Python compile | Pass — application and scripts compile cleanly |
| Windows timezone regression | Pass — `tzdata` installed and forced missing-IANA fallback resolves to EAT/UTC+03:00 |
| Ruff static analysis | Pass — no findings |
| Unit tests | Pass — 40 tests |
| Five-minute scheduler | Pass — workflow contains `2/5 * * * *` and `workflow_dispatch` |
| Existing-repository safety | Pass — updater is locked to `dansamuka/2_Elections_tallying_educational` and contains no repository-creation command |
| PowerShell compatibility | Pass — UTF-8 BOM retained and executable text is ASCII-only for Windows PowerShell 5.1 |
| Portal parser fixtures | Pass — constituency rows, Yii data attributes, generic scoped downloads, pagination, count parsing and global-download exclusion |
| Portal completeness guard | Pass — a reported/discovered shortfall fails loudly and preserves an HTML diagnostic snapshot |
| Immutable form archive | Pass — SHA-256 versioning, ZIP extraction and no-overwrite behavior |
| Historical OCR safety | Pass — OCR creates review records only and never auto-publishes candidate totals |
| Historical reference validation | Pass — Banissa 81 streams sum exactly to 32,703 registered voters |
| Historical publication safety | Pass — official totals are separated from Form 35A sums and replay remains withheld while stream evidence is incomplete |
| Historical import gates | Pass — V01, V02, V03 and V07 failures are rejected |
| Frontend JavaScript syntax | Pass — live app, archive module and configuration |
| Review-console inline JavaScript | Pass |
| Generated live payload | Pass — `olkalou.live.v2`, 144 expected streams |
| Generated historical payload | Pass — `kenya.election.archive.v1`, Banissa 81-stream frame, OCR state and portal-sync state |
| Historical catalog | Pass — Banissa is the default website archive selection |
| GitHub Pages assembly | Pass — frontend and public datasets assemble with project-relative data paths |
| Manual update controls | Pass — website owner link and authenticated `UPDATE_IEBC_FORMS_NOW.cmd` target the same workflow |
| Ol Kalou production reference gate | Correctly closed |

## External portal test note

The public IEBC page was independently confirmed to list Banissa as 81 of 81 reported and Ol Kalou as 0 of 144 at validation time. The execution container itself could not resolve the external IEBC hostname, so it could not download the live files during packaging. This limitation is not hidden: the scheduled workflow runs on GitHub's internet-connected runner, and the parser refuses success when the portal's reported count exceeds the number of discovered Form 35A links.
