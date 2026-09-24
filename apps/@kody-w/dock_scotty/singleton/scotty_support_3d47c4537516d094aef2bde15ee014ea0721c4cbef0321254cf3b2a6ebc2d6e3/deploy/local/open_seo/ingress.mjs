// OpenSEO's no-auth native server is never directly published.
import http from "node:http";
import { timingSafeEqual } from "node:crypto";
import { pathToFileURL } from "node:url";

const MAX_BODY = 65536;
const MAX_RESPONSE = 2 * 1024 * 1024;
const METHODS = new Set(["initialize", "notifications/initialized", "tools/list", "tools/call"]);
const DROP = new Set([
  "host", "origin", "authorization", "connection", "proxy-connection",
  "proxy-authorization", "transfer-encoding", "content-length", "cookie",
]);

export function allowedRPC(value) {
  if (!value || Array.isArray(value) || value.jsonrpc !== "2.0" || !METHODS.has(value.method)) return false;
  if (value.method !== "tools/call") return true;
  const { name, arguments: args = {} } = value.params || {};
  if (!args || typeof args !== "object" || Array.isArray(args)) return false;
  if (name === "list_projects") return Object.keys(args).length === 0;
  return name === "create_project"
    && Object.keys(args).sort().join(",") === "domain,name"
    && typeof args.domain === "string" && args.domain.length <= 253
    && /^[a-z0-9.-]+$/.test(args.domain)
    && typeof args.name === "string" && args.name.trim().length > 0 && args.name.length <= 200
    && !/[\x00-\x1f\x7f]/.test(args.name);
}

export function createIngress({ port, token, upstreamHost = "open-seo", upstreamPort = 3001 }) {
  if (!token || token.length < 24) throw new Error("A private ingress token is required.");
  const authority = `127.0.0.1:${port}`;
  const authorized = (header) => {
    const actual = Buffer.from(header || "");
    const expected = Buffer.from(`Bearer ${token}`);
    return actual.length === expected.length && timingSafeEqual(actual, expected);
  };
  return http.createServer({ maxHeaderSize: 16384, requestTimeout: 45000 }, async (request, response) => {
    const fail = (status, code) => {
      if (!response.headersSent) response.writeHead(status, { "content-type": "application/json", connection: "close" });
      response.end(JSON.stringify({ error: code }));
    };
    if (request.headers.host !== authority
        || (request.headers.origin !== undefined && request.headers.origin !== `http://${authority}`)) {
      fail(403, "origin-not-allowed");
      return;
    }
    const health = request.method === "GET" && request.url === "/api/health";
    const mcp = request.url === "/mcp" && ["POST", "DELETE"].includes(request.method);
    if (!health && !mcp) { fail(404, "not-found"); return; }
    if (!health && !authorized(request.headers.authorization)) { fail(401, "unauthorized"); return; }
    if (request.headers["transfer-encoding"] || Number(request.headers["content-length"] || 0) > MAX_BODY) {
      fail(413, "invalid-body");
      return;
    }
    const chunks = [];
    let size = 0;
    try {
      for await (const chunk of request) {
        size += chunk.length;
        if (size > MAX_BODY) { fail(413, "invalid-body"); return; }
        chunks.push(chunk);
      }
    } catch { fail(400, "invalid-body"); return; }
    const body = Buffer.concat(chunks);
    if (request.method === "POST") {
      try {
        if (!allowedRPC(JSON.parse(body.toString("utf8")))) { fail(403, "operation-not-allowed"); return; }
      } catch { fail(400, "invalid-json"); return; }
    }
    const headers = Object.fromEntries(
      Object.entries(request.headers).filter(([key]) => !DROP.has(key.toLowerCase())),
    );
    headers.host = "localhost:3001";
    headers["content-length"] = body.length;
    const upstream = http.request({
      hostname: upstreamHost, port: upstreamPort, path: health ? "/api/health" : "/mcp",
      method: request.method, headers, timeout: 35000,
    }, (native) => {
      const output = [];
      let total = 0;
      native.on("data", (chunk) => {
        total += chunk.length;
        if (total > MAX_RESPONSE) {
          native.destroy();
          fail(502, "response-too-large");
        } else output.push(chunk);
      });
      native.on("end", () => {
        if (response.writableEnded) return;
        const reply = Buffer.concat(output);
        const replyHeaders = Object.fromEntries(
          Object.entries(native.headers).filter(([key]) =>
            !["transfer-encoding", "connection", "content-length", "set-cookie"].includes(key)),
        );
        response.writeHead(native.statusCode, { ...replyHeaders, "content-length": reply.length, connection: "close" });
        response.end(reply);
      });
      native.on("error", () => { if (!response.writableEnded) fail(502, "app-not-ready"); });
    });
    upstream.on("timeout", () => upstream.destroy());
    upstream.on("error", () => { if (!response.writableEnded) fail(502, "app-not-ready"); });
    upstream.end(body);
  });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  createIngress({
    port: process.env.RAPP_DOCK_PORT,
    token: process.env.RAPP_DOCK_OPENSEO_TOKEN,
  }).listen(3001, "0.0.0.0");
}
