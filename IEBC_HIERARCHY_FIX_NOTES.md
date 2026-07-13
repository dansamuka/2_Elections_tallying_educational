# IEBC hierarchy sync fix

## Evidence from the live portal

The IEBC form portal does not expose Banissa's 81 Form 35As as one reliable bulk URL. The visible route is hierarchical:

`KENYA > MANDERA > BANISSA > WARD > POLLING CENTRE > POLLING STREAM`

At the leaf level, each reported polling stream has its own preview and cloud-download controls. The safe ingestion route is therefore to walk the hierarchy and download each individual form, not to call a higher-level `Download All` URL.

## Changes

- Walks the exact configured county and constituency route.
- Once the Banissa breadcrumb is reached, descends all ward, polling-centre and station rows.
- Supports IEBC's JavaScript `location.href` table rows and session-dependent repeated row URLs.
- Ignores every `Download All` control during discovery.
- Selects the cloud/download action and ignores the eye/HTML preview action.
- Refuses to crawl unrelated counties or constituencies.
- Requires the final discovery count to reconcile to IEBC's reported Form 35A count before the archive run succeeds.
- Keeps OCR output review-only.

## Validation

- 49 tests passed.
- Ruff passed.
- Python compilation passed.
- Frontend JavaScript syntax checks passed.
- A live portal run could not be completed in the packaging environment because outbound DNS was unavailable. The regression fixture reproduces the portal hierarchy and leaf layout supplied from the live IEBC page.

## Existing repository only

`PUSH_TO_GITHUB.cmd` is locked to `dansamuka/2_Elections_tallying_educational`. It fetches and updates that repository's `main` branch and has no repository-creation path.
