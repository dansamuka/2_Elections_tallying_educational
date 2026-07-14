window.OLKALOU_CONFIG = {
  // The realtime API/R2 endpoints are optional at build time. Set these to the
  // deployed HTTPS origins after the always-on service is online. The browser
  // always retains the GitHub Pages JSON as a last-known-good fallback.
  realtimeApiBase: "",
  liveDataBaseUrls: [
    // "https://data.example.org/ol-kalou"
  ],
  archiveDataBaseUrls: [
    // "https://data.example.org/ol-kalou"
  ],
  liveUrls: [
    "../data/public/live.json"
  ],
  refreshMs: 5000,
  refreshWatchMs: 2000,
  refreshWatchTimeoutMs: 90000,
  refreshTriggersSyncWhenAuthorized: true,
  ownerTokenSessionKey: "olkalou.realtime.ownerToken",
  archiveCatalogUrl: "../data/public/elections/catalog.json",
  archiveUpdateWorkflowUrl: "https://github.com/dansamuka/2_Elections_tallying_educational/actions/workflows/sync-historical-forms.yml",
  archiveSyncMinutes: 5,
  liveElectionId: "ol-kalou-2026"
};
