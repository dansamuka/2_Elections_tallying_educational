const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store, max-age=0",
  "x-content-type-options": "nosniff",
};

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = String(env.CORS_ORIGINS || "https://dansamuka.github.io")
    .split(",").map(value => value.trim()).filter(Boolean);
  const selected = allowed.includes("*") ? "*" : (allowed.includes(origin) ? origin : allowed[0]);
  return {
    "access-control-allow-origin": selected || "https://dansamuka.github.io",
    "access-control-allow-methods": "GET,POST,OPTIONS",
    "access-control-allow-headers": "Authorization,Content-Type",
    "vary": "Origin",
  };
}

function response(body, request, env, status = 200, headers = {}) {
  return new Response(body, {
    status,
    headers: {...JSON_HEADERS, ...corsHeaders(request, env), ...headers},
  });
}

async function objectJson(env, key, request) {
  const object = await env.ELECTION_DATA.get(`${String(env.DATA_PREFIX || "ol-kalou").replace(/\/$/, "")}/${key}`);
  if (!object) return response(JSON.stringify({detail:"Not found"}), request, env, 404);
  return response(await object.text(), request, env, 200, {etag: object.httpEtag || ""});
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return response("", request, env, 204);
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "GET" && path === "/api/health") {
      return response(JSON.stringify({status:"OK", edge:"cloudflare", origin_configured:Boolean(env.ORIGIN_API)}), request, env);
    }
    if (request.method === "GET" && path === "/api/live") return objectJson(env, "live.json", request);
    if (request.method === "GET" && path === "/api/catalog") return objectJson(env, "elections/catalog.json", request);

    let match = path.match(/^\/api\/elections\/([^/]+)\/(data|status)$/);
    if (request.method === "GET" && match) {
      const electionId = decodeURIComponent(match[1]);
      const key = match[2] === "data"
        ? `elections/${electionId}.json`
        : `realtime/status/${electionId}.json`;
      return objectJson(env, key, request);
    }

    match = path.match(/^\/api\/elections\/([^/]+)\/(sync|wait)$/);
    if (match) {
      if (!env.ORIGIN_API) return response(JSON.stringify({detail:"Origin API not configured"}), request, env, 503);
      const electionId = encodeURIComponent(decodeURIComponent(match[1]));
      if (match[2] === "sync") {
        if (request.method !== "POST") return response(JSON.stringify({detail:"Method not allowed"}), request, env, 405);
        if (request.headers.get("Authorization") !== `Bearer ${env.OWNER_TOKEN}`) {
          return response(JSON.stringify({detail:"Invalid realtime API token"}), request, env, 401);
        }
        const upstream = await fetch(`${String(env.ORIGIN_API).replace(/\/$/, "")}/api/elections/${electionId}/sync`, {
          method:"POST",
          headers:{"Authorization":`Bearer ${env.ORIGIN_TOKEN}`, "Content-Type":"application/json"},
          body: await request.text(),
        });
        return response(await upstream.text(), request, env, upstream.status);
      }
      if (request.method === "GET") {
        const upstream = await fetch(`${String(env.ORIGIN_API).replace(/\/$/, "")}/api/elections/${electionId}/wait${url.search}`, {headers:{"Accept":"application/json"}});
        return response(await upstream.text(), request, env, upstream.status);
      }
    }

    return response(JSON.stringify({detail:"Not found"}), request, env, 404);
  },
};
