# Validation report

Validated on 13 July 2026 against the GitHub-ready source tree.

| Check | Result |
|---|---|
| Python compile | Pass — application and scripts compile cleanly |
| Ruff static analysis | Pass — no findings |
| Unit tests | Pass — 23 tests |
| Historical reference validation | Pass — Banissa 81 streams sum exactly to 32,703 registered voters |
| Historical publication safety | Pass — official totals are separated from Form 35A sums and replay remains withheld while stream evidence is incomplete |
| Historical import gates | Pass — V01, V02, V03 and V07 failures are rejected |
| Frontend JavaScript syntax | Pass — live app, archive module and configuration |
| Review-console inline JavaScript | Pass |
| Generated live payload | Pass — `olkalou.live.v2`, 144 expected streams |
| Generated historical payload | Pass — `kenya.election.archive.v1`, Banissa 81-stream frame and declared result |
| Historical catalog | Pass — Banissa is discoverable by the website selector |
| Local static HTTP smoke test | Pass — live page, archive page, catalog and Banissa payload return HTTP 200 |
| GitHub Pages assembly logic | Pass — copies all public datasets and rewrites local data paths for repository Pages hosting |
| One-click package structure | Pass — `PUSH_TO_GITHUB.cmd` is at ZIP root |
| Ol Kalou production reference gate | Correctly closed |

## External portal test note

The Banissa portal command is implemented and returns a clean actionable error when internet or DNS access is unavailable. The execution sandbox could not reach the external IEBC host directly, so the 81 historical scans are not falsely represented as already archived. Run `archive-run banissa-2025` from the extracted package on an internet-connected machine, then review its match report before transcription.
