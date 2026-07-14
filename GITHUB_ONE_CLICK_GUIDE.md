# One-click GitHub publishing

1. Extract the ZIP into a normal folder. Do **not** upload the ZIP itself into GitHub.
2. Double-click **`PUSH_TO_GITHUB.cmd`**.
3. Sign into GitHub in the browser when prompted.
4. The updater verifies access to **`dansamuka/2_Elections_tallying_educational`**.
5. It runs the tests, replaces changed files in that repository, pushes `main`, and enables the GitHub Pages workflow.

The deployed website contains:

- `/` — Ol Kalou live tallying wall.
- `/archive.html` — past-polls module, initially seeded with Banissa 2025.
- `/methodology.html` — public methodology.


## Elections updated by the workflow

The same existing-repository workflow now checks `banissa-2025` and `ol-kalou-2026`. Use `UPDATE_IEBC_FORMS_NOW.cmd` for both targets or `UPDATE_OL_KALOU_NOW.cmd` for Ol Kalou only.

## Existing repository

The same button is safe to run again. It is locked to `dansamuka/2_Elections_tallying_educational`, reuses its existing `main` history, commits changed files, and pushes them back. It refuses to create a different repository.

## Command-line alternative

```powershell
PowerShell -ExecutionPolicy Bypass -File scripts/github/push_to_github.ps1
```

## Windows PowerShell compatibility

This package includes the July 2026 PowerShell parser hotfix. The publisher script is saved with a UTF-8 BOM, contains ASCII-only executable text, refreshes PATH after winget installations, and works with Windows PowerShell 5.1 or PowerShell 7. Do not copy the script through an editor that removes its encoding marker.

## Windows timezone compatibility

The package installs Python's `tzdata` database automatically. It also falls back to fixed East Africa Time (`UTC+03:00`) if Windows cannot provide the `Africa/Nairobi` IANA timezone. This prevents `ZoneInfoNotFoundError` during one-click validation on Python 3.13.

## Historical OCR update

Place historical PDFs/images under `data/elections/<election-id>/documents/` and double-click `RUN_HISTORICAL_OCR.cmd`. It creates a human review queue, rebuilds the archive dataset, and offers to push the changed files back to the same repository. It never creates a new repository or publishes OCR figures automatically.


## Five-minute IEBC form synchronization

After this update is pushed, GitHub Actions runs `Sync IEBC forms and OCR` every five minutes. The website's **Update now** button opens that workflow for a secure owner-initiated run. You can also double-click `UPDATE_IEBC_FORMS_NOW.cmd`, which dispatches the workflow using the already authenticated GitHub CLI.

The scheduled job only commits when it discovers new links, downloads a new/amended file, produces a new OCR extraction, or changes a pipeline error state. A no-change check is recorded in the workflow summary without creating an empty Git commit.

## Realtime deployment (separate from GitHub Pages)

GitHub Pages cannot run the Python watcher. Deploy the repository's `realtime` Docker service to an always-on container/VPS, set `REALTIME_API_TOKEN`, and optionally configure the existing `S3_*` variables for Cloudflare R2.

After the service has an HTTPS URL, run:

```bash
python scripts/configure_realtime_frontend.py --api-base https://YOUR-SYNC-URL
```

For the edge/R2 arrangement, deploy `deploy/cloudflare-worker/` and use its URL as `--api-base`. Full instructions are in `docs/REALTIME_SYNC.md`.
