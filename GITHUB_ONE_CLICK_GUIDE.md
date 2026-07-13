# One-click GitHub publishing

1. Extract the ZIP into a normal folder. Do **not** upload the ZIP itself into GitHub.
2. Double-click **`PUSH_TO_GITHUB.cmd`**.
3. Sign into GitHub in the browser when prompted.
4. Accept the default repository name or type another one.
5. The script runs the tests, creates/updates the repository, pushes `main`, and enables the GitHub Pages workflow.

The deployed website contains:

- `/` — Ol Kalou live tallying wall.
- `/archive.html` — past-polls module, initially seeded with Banissa 2025.
- `/methodology.html` — public methodology.

## Existing repository

The same button is safe to run again. It reuses the existing remote, commits changed files, and pushes `main`.

## Command-line alternative

```powershell
PowerShell -ExecutionPolicy Bypass -File scripts/github/push_to_github.ps1 -RepositoryName kenya-election-tallying-wall
```

## Windows PowerShell compatibility

This package includes the July 2026 PowerShell parser hotfix. The publisher script is saved with a UTF-8 BOM, contains ASCII-only executable text, refreshes PATH after winget installations, and works with Windows PowerShell 5.1 or PowerShell 7. Do not copy the script through an editor that removes its encoding marker.

## Windows timezone compatibility

The package installs Python's `tzdata` database automatically. It also falls back to fixed East Africa Time (`UTC+03:00`) if Windows cannot provide the `Africa/Nairobi` IANA timezone. This prevents `ZoneInfoNotFoundError` during one-click validation on Python 3.13.

## Historical OCR update

Place historical PDFs/images under `data/elections/<election-id>/documents/` and double-click `RUN_HISTORICAL_OCR.cmd`. It creates a human review queue, rebuilds the archive dataset, and offers to push the changed files back to the same repository. It never creates a new repository or publishes OCR figures automatically.
