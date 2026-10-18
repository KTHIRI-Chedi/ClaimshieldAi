// Serves the claim page. TEMPLATE is dev/form.html, inlined by dev/build.py.
const TEMPLATE = __TEMPLATE__;
const req = $input.first().json;

// The page needs absolute URLs: recent n8n versions show webhook HTML inside a sandboxed
// iframe, where relative URLs do not resolve against the n8n server.
let base = req.webhookUrl ? String(req.webhookUrl).replace(/\/claim-form\/?$/, '') : '';
if (!base) {
  const h = req.headers || {};
  base = `${h['x-forwarded-proto'] || 'http'}://${h['x-forwarded-host'] || h.host}/webhook`;
}

const config = {
  submitUrl: `${base}/claim-submit`,
  geocodeUrl: `${base}/claim-geocode`,
  mapCenter: [36.8065, 10.1815], // Tunis
  mapZoom: 12,
  maxPhotos: 8,
  maxInvoiceBytes: 8 * 1024 * 1024,
};

return [{ json: { html: TEMPLATE.replace('__CONFIG__', JSON.stringify(config)) } }];
