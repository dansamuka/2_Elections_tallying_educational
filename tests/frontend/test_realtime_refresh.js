"use strict";
const { JSDOM } = require("jsdom");
const fs = require("fs");
const path = require("path");
const assert = require("node:assert/strict");

const FRONTEND = path.resolve(__dirname, "..", "..", "frontend");
const CATALOG = {
  schema: "kenya.election.catalog.v1",
  default: "ol-kalou-2026",
  elections: [{id:"ol-kalou-2026", label:"Ol Kalou"}],
};
const payload = (seq) => ({
  schema:"kenya.election.archive.v1", seq, generated_at:"2026-07-14T10:00:00Z",
  election_id:"ol-kalou-2026", election:{constituency:"OL KALOU", code:"091", date:"2026-07-16", title:"Ol Kalou"},
  reference:{complete:false, errors:["test"]}, coverage:{streams_total:1, stream_rows_loaded:1, registered_total:0},
  archive:{forms_expected:1, forms_archived:0, stream_results_transcribed:0, replay_available:false, replay_events:[], ocr:{review_rows:0}, portal_sync:{}},
  totals:{valid_votes:0}, candidates:[], streams:[{stream_key:"S1", station_name:"Station", ward:"W", state:"AWAITING", registered:null}], wards:[], official_declaration:{notes:[]},
});

async function main() {
  const html = fs.readFileSync(path.join(FRONTEND, "archive.html"), "utf8");
  const dom = new JSDOM(html, {url:"https://example.org/archive.html", runScripts:"dangerously", pretendToBeVisual:true});
  const {window} = dom;
  let dataSeq = 1;
  let statusCalls = 0;
  let triggerCalls = 0;
  window.prompt = () => "owner-secret";
  window.confirm = () => true;
  window.open = () => {};
  window.HTMLDialogElement.prototype.showModal = function(){ this.setAttribute("open", ""); };
  window.HTMLDialogElement.prototype.close = function(){ this.removeAttribute("open"); };
  window.fetch = async (url, options={}) => {
    const clean = String(url).split("?")[0];
    if (clean.endsWith("/sync")) {
      triggerCalls += 1;
      assert.equal(options.headers.Authorization, "Bearer owner-secret");
      return {ok:true, status:202, json:async()=>({state:"RUNNING",stage:"DISCOVERING",seq:1,message:"checking"})};
    }
    if (clean.endsWith("/status")) {
      statusCalls += 1;
      if (statusCalls > 1) dataSeq = 2;
      return {ok:true,status:200,json:async()=> statusCalls > 1
        ? {state:"COMPLETE",stage:"COMPLETE",seq:2,message:"updated"}
        : {state:"RUNNING",stage:"OCR",seq:1,message:"processing"}};
    }
    if (clean.includes("catalog")) return {ok:true,status:200,json:async()=>CATALOG};
    return {ok:true,status:200,json:async()=>payload(dataSeq)};
  };
  window.eval(fs.readFileSync(path.join(FRONTEND, "config.js"), "utf8"));
  window.OLKALOU_CONFIG.realtimeApiBase = "https://sync.example.org";
  window.OLKALOU_CONFIG.refreshWatchMs = 5;
  window.OLKALOU_CONFIG.refreshWatchTimeoutMs = 100;
  window.eval(fs.readFileSync(path.join(FRONTEND, "archive.js"), "utf8"));
  await new Promise(r=>setTimeout(r,30));
  window.document.getElementById("archiveUpdateNow").click();
  await new Promise(r=>setTimeout(r,60));
  assert.equal(triggerCalls,1,"owner button triggers the realtime endpoint once");
  assert.match(window.document.getElementById("archiveLiveSyncStatus").textContent,/updated|Latest election JSON/i);
  assert.ok(statusCalls >= 2,"browser watches the job until completion");
  console.log("Realtime refresh UI test passed.");
  process.exit(0);
}
main().catch(error=>{console.error(error);process.exit(1);});
