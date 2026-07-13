window.OLKALOU_CONFIG = {
  liveUrls: [
    "../data/public/live.json"
    // Production redundancy example:
    // "https://cdn.example.org/ol-kalou/workers/worker-a/live.json",
    // "https://cdn.example.org/ol-kalou/workers/worker-b/live.json"
  ],
  refreshMs: 30000,
  archiveCatalogUrl: "../data/public/elections/catalog.json",
  archiveUpdateWorkflowUrl: "https://github.com/dansamuka/2_Elections_tallying_educational/actions/workflows/sync-historical-forms.yml",
  archiveSyncMinutes: 5
};
