// Local stand-in for n8n, for testing the claim page without an n8n server.
// It runs the Code nodes from the generated workflow JSON, so it tests the real artifact.
// Usage: node dev/mock_n8n.js   then open http://localhost:5679/webhook/claim-form
const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = Number(process.env.PORT || 5679);
const WORKFLOW = path.join(__dirname, '..', 'claim_form_workflow.json');
const UA = { 'User-Agent': 'ClaimShieldAI-student-project/0.1 (local test)', 'Accept-Language': 'en' };

function loadNodes() {
  const wf = JSON.parse(fs.readFileSync(WORKFLOW, 'utf8'));
  return Object.fromEntries(wf.nodes.map((n) => [n.name, n]));
}

// Runs one Code node like n8n: $input is the incoming items, $('Node') reads earlier outputs.
async function run(nodeName, items, outputs) {
  const code = loadNodes()[nodeName].parameters.jsCode;
  const $ = (name) => ({ first: () => outputs[name][0], all: () => outputs[name] });
  const $input = { first: () => items[0], all: () => items };
  const fn = new Function('$', '$input', `return (async () => {${code}\n})();`);
  const result = await fn($, $input);
  outputs[nodeName] = result;
  return result;
}

const prettySize = (n) => (n < 1e3 ? `${n} B` : n < 1e6 ? `${(n / 1e3).toFixed(1)} kB` : `${(n / 1e6).toFixed(1)} MB`);

function send(res, status, body, type = 'application/json') {
  res.writeHead(status, { 'Content-Type': type, 'Access-Control-Allow-Origin': '*' });
  res.end(typeof body === 'string' ? body : JSON.stringify(body));
}

http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://localhost:${PORT}`);
  const out = {};
  try {
    if (req.method === 'GET' && url.pathname === '/webhook/claim-form') {
      const [page] = await run('Render form page', [{ json: {
        headers: req.headers, query: {}, body: {}, webhookUrl: `http://localhost:${PORT}/webhook/claim-form`,
      } }], out);
      return send(res, 200, page.json.html, 'text/html; charset=utf-8');
    }

    if (req.method === 'GET' && url.pathname === '/webhook/claim-geocode') {
      const [reqItem] = await run('Build geocode request', [{ json: { query: Object.fromEntries(url.searchParams) } }], out);
      if (!reqItem.json.url) return send(res, 400, { error: 'Send lat and lon, or q with at least 3 characters.' });
      const r = await fetch(reqItem.json.url, { headers: UA });
      const data = r.ok ? await r.json() : { error: `HTTP ${r.status}` };
      // n8n splits an array response into items; alwaysOutputData turns "no items" into {}.
      const items = Array.isArray(data) ? (data.length ? data.map((j) => ({ json: j })) : [{ json: {} }]) : [{ json: data }];
      out.Nominatim = items;
      const [shaped] = await run('Shape geocode response', items, out);
      return send(res, 200, shaped.json);
    }

    if (req.method === 'POST' && url.pathname === '/webhook/claim-submit') {
      const form = await new Request(url, { method: 'POST', headers: req.headers, body: req, duplex: 'half' }).formData();
      const body = {};
      const files = {};
      for (const [key, value] of form.entries()) {
        if (typeof value === 'string') body[key] = value;
        else (files[key] = files[key] || []).push(value);
      }
      // Same naming as n8n's Webhook node: "photos" for one file, "photos0", "photos1"... for several.
      const binary = {};
      for (const [key, list] of Object.entries(files)) {
        list.forEach((f, i) => {
          binary[list.length > 1 ? `${key}${i}` : key] = {
            mimeType: f.type, fileName: f.name, fileSize: prettySize(f.size), data: '(omitted in mock)',
          };
        });
      }
      const [checked] = await run('Validate submission', [{ json: { headers: req.headers, body }, binary }], out);
      if (!checked.json.valid) {
        console.log('400', checked.json.errors);
        return send(res, 400, { errors: checked.json.errors });
      }
      const [created] = await run('Create claim', [checked], out);
      console.log('202', JSON.stringify(created.json.claim), 'files:',
        Object.entries(created.binary).map(([k, v]) => `${k}=${v.fileName} (${v.mimeType}, ${v.fileSize})`).join(', '));
      return send(res, 202, {
        claim_id: created.json.claim.claim_id, status: 'received',
        message: 'We have received your claim. You will get the decision by email.',
      });
    }
    return send(res, 404, { error: 'not found' });
  } catch (e) {
    console.error(e);
    return send(res, 500, { error: String(e.message || e) });
  }
}).listen(PORT, () => console.log(`Mock n8n on http://localhost:${PORT}/webhook/claim-form`));
