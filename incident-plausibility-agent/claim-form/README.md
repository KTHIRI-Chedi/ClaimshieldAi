# Claim Intake Form

The page where a claimant files a claim, served entirely by n8n. No other server or hosting is needed.

The claimant fills in their policy, describes the incident, **taps the map where it happened** (or uses their phone's GPS), and uploads 1–8 photos and the invoice PDF. n8n checks everything, answers with a claim number, and hands the claim to the main ClaimShield workflow.

## How it works

One n8n workflow (`claim_form_workflow.json`) with three webhooks:

| Webhook | What it does |
|---|---|
| `GET /webhook/claim-form` | Serves the claim page (HTML, built by **Render form page**) |
| `GET /webhook/claim-geocode` | Address search and pin-to-address lookup for the page, through Nominatim. The browser never calls an outside geocoding service. |
| `POST /webhook/claim-submit` | Validates the claim again on the server, creates the claim ID, answers **202** with it (as in design section 4.3), then runs the orchestrator |

```
Claimant's browser                         n8n
───────────────────                        ───────────────────────────────────────────
open /claim-form  ───────────────────────▶ Render form page → Send page
search or tap the map ──────────────────▶ Build geocode request → Nominatim → Send address
submit (fields + photos + PDF) ─────────▶ Validate submission → Valid?
                                              ├─ no  → Send errors (400)
                                              └─ yes → Create claim → Send claim ID (202) → Run orchestrator
```

### The map
- It uses **Leaflet** (a free map library) with **OpenStreetMap** tiles, the same map data the Incident Plausibility agent checks against. The claimant's browser loads both from public CDNs; n8n serves everything else.
- Search shows up to 5 matches, because a street name often exists in several places. A search for "Avenue Habib Bourguiba, Tunis" returned 5 different avenues. The claimant picks the right one, then can drag the pin to the exact spot.
- When the pin moves, the address is looked up and shown under the map, so the claimant can confirm it.
- **"Use my current location"** reads the phone's GPS. It only works over **HTTPS** (see Demo on a phone). Otherwise the page asks the claimant to tap the map instead.

### Photos
The page **resizes photos in the browser** (longest side 1600 px, JPEG) before uploading. That keeps the upload under n8n's request size limit (16 MB by default), and it lowers the vision model's cost, as the design asks.

## Set it up in n8n (about 10 minutes)

1. **Import.** Go to *Workflows → Import from File* and choose `claim_form_workflow.json`.
2. **Set the Nominatim User-Agent.** In the **Nominatim** node, replace `(replace with your team contact)` with a team email. Nominatim's rules require it.
3. **Activate the workflow** (the toggle at the top right). Each test URL only listens for one request at a time, and the page needs all three webhooks, so use the production URLs.
4. **Open the page:** `http://localhost:5678/webhook/claim-form`, with your n8n host and port.
5. **Connect the orchestrator.** Open **Run orchestrator**, pick the main ClaimShield workflow, and enable the node (it's disabled so the form works on its own first).

### What the orchestrator receives
One item with `$json.claim`:

```json
{
  "claim_id": "CLM-2026-JZ6ON8JS",
  "status": "processing",
  "received_at": "2026-10-17T15:30:10.967Z",
  "policy_id": "POL-104233",
  "contact_email": "claimant@example.com",
  "claim_type": "collision",
  "incident_datetime": "2026-03-14T18:40:00",
  "incident_lat": 36.8004,
  "incident_lon": 10.1866,
  "incident_location": "Avenue Habib Bourguiba, Tunis, 1151, Tunisia",
  "description": "I was stopped at the traffic light when the car behind me hit…",
  "claimed_amount": 1850.5,
  "currency": "TND",
  "photo_count": 3
}
```

It also receives these binary files: `photo_1` … `photo_n` (JPEG) and `invoice` (PDF). Pass the photos to the Visual Inspection agent, the invoice to the Invoice Parser, and `incident_lat`, `incident_lon`, `incident_datetime`, `incident_location` and `description` to the Incident Plausibility agent. Its input already accepts these fields.

## Demo on a phone
- The phone and the computer running n8n must be on the same Wi-Fi. Open `http://<computer's IP>:5678/webhook/claim-form`.
- **GPS needs HTTPS.** Browsers only share location with secure pages. For the demo, put n8n behind a free HTTPS tunnel (for example `cloudflared tunnel --url http://localhost:5678` or ngrok), and set n8n's `WEBHOOK_URL` environment variable to the tunnel URL. Tapping the map works without HTTPS.
- **If the GPS button or the map doesn't work:** recent n8n versions display HTML returned by a webhook inside a sandboxed frame. The page already uses absolute URLs to work inside it. If the GPS is still blocked, set `N8N_INSECURE_DISABLE_WEBHOOK_IFRAME_SANDBOX=true` on your self-hosted n8n container. That's fine for a demo, but mention it in the report.

## Security (for design section 4.8)
- **Everything is checked again on the server.** The page's checks only help the claimant; anyone can post to the webhook directly. In the test, a request that skipped the page was rejected with 10 specific errors.
- **Limits:** 1–8 photos, JPG or PNG, 5 MB each; exactly one PDF of up to 8 MB; description of 20–4000 characters; amount up to 1,000,000 TND; pin coordinates required; consent required; no future dates and nothing more than a year old.
- **The form is a public endpoint without the authentication header.** A web page can't keep a secret, so a header key would be visible to anyone. The API endpoint in design section 4.8 keeps its header authentication for other systems. For production: customer login or a CAPTCHA, plus rate limiting.
- **Customer messages stay neutral.** The page only ever says "received", and the decision goes out by email (the design's rule that customers never see fraud wording).
- The policy check (does the policy exist and is it active) stays in the orchestrator, as in the design.

## Tested so far
The generated workflow's own Code nodes were run behind a local stand-in for n8n (`dev/mock_n8n.js`), using the built-in browser and the live Nominatim service:

| Test | Result |
|---|---|
| Page loads, map and tiles render | ✅ No console errors |
| Search "Avenue Habib Bourguiba, Tunis" | ✅ 5 matches in different districts listed |
| Tap the map | ✅ Pin placed, coordinates filled, address looked up |
| Submit empty form | ✅ 9 clear field errors, nothing sent |
| Valid claim with 3 photos (3000×2000 PNG and others) and a PDF | ✅ 202 with claim ID; photos resized and converted to JPEG; record includes the pin coordinates |
| Bad data sent straight to the webhook | ✅ 400 with 10 specific errors |
| Phone width (375 px) | ✅ No sideways scrolling, light and dark mode |

**Not tested yet:** inside a real running n8n, and the GPS button (it needs HTTPS and a real device). Run setup steps 1–4 to check the first.

## The `dev/` folder
- `form.html` is the page. Edit it here, then rebuild.
- `src/*.js` holds the Code nodes.
- `build.py` packs both into the workflow: `python dev/build.py claim_form_workflow.json`
- `mock_n8n.js` is a local stand-in that runs the workflow's Code nodes: `node dev/mock_n8n.js`, then open `http://localhost:5679/webhook/claim-form` (Node 18+).

If you edit the workflow in the n8n editor instead, the exported JSON becomes the source of truth. Pick one place to edit.
