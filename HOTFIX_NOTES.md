# Windows timezone hotfix

This release fixes the one-click publisher failure:

```text
zoneinfo._common.ZoneInfoNotFoundError: No time zone found with key Africa/Nairobi
```

## Changes

- Package version raised to `0.2.1`.
- `tzdata>=2025.2` added to core dependencies.
- Nairobi time now falls back to fixed `UTC+03:00`/`EAT` if the Windows IANA database is unavailable.
- The one-click PowerShell script verifies EAT before running tests and generating payloads.
- Two timezone regression tests added.

The earlier run completed GitHub CLI installation, authentication, dependency installation, and all 23 original tests. It stopped before Git initialization or pushing, so rerunning the corrected package against the same empty repository is safe.
