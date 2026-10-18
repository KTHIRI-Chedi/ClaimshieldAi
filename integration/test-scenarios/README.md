# ClaimShield test scenarios

Six claims to submit on **http://localhost:5678/webhook/claim**, one per outcome. Each folder has the photos and the invoice to upload. Copy each block below into the form.

**Run them in this order**, because scenario 4 reuses the photos of scenario 1. To run everything again from the start, empty the photo memory first: in n8n, go to Overview → Data tables → **photo hashes** and delete every row except `CLM-H001`.

Every claim waits for all the agents (Gemini, OCR, RAG on gemma2, plausibility on Ollama), so expect a few minutes each. The result page opens by itself.

| # | Folder | Expected result | Why |
|---|---|---|---|
| 1 | `1_approved_rear_end` | **Approved** | Photos, story and invoice agree; total 1,201.90 TND, under the 2,000 TND limit |
| 2 | `2_review_amount_above_limit` | **Human review** | Consistent claim, but the total is 3,736.60 TND, above the limit |
| 3 | `3_review_story_mismatch` | **Human review** | The story says rear bumper; the photo shows the side doors (DAMAGE_MISMATCH +20) |
| 4 | `4_fraud_reused_photos` | **Fraud investigation** | Same photos as scenario 1 (PHOTO_REUSED +40). The client only reads "under review" |
| 5 | `5_fraud_several_signs` | **Fraud investigation** | Story vs photo mismatch, photo taken 6 weeks before the accident, invoice that does not add up, invoiced parts not visible |
| 6 | `6_rejected_future_date` | **Rejected** | Accident date in the future, rejected at validation, before any AI call |

The photos come from the public car-damage dataset of github.com/nicolasmetallo/car-damage-detector. I added the date each photo was "taken" (EXIF), which the photo checks read. The invoices are made up, in the same format as `INV-001.pdf`.

---

## 1. Approved: rear-end at a red light
- **Full name:** Amine Ben Salah
- **Email:** your own email, to receive the client message
- **Phone:** +216 20 123 456
- **Date:** 2026-10-14 · **Time:** 17:40
- **Map:** search `Avenue Habib Bourguiba, Tunis`, pin it, click **Use this location**
- **What happened?**
  > I was stopped at the red light on Avenue Habib Bourguiba when the car behind me did not brake in time and hit my rear bumper. The bumper is dented and the paint is scratched. Nobody was hurt.
- **Photos:** `rear_bumper_1.jpg`, `rear_bumper_2_closeup.jpg`
- **Invoice:** `invoice_F-2026-2041.pdf` (rear bumper, paint, labour: 1,201.90 TND)

**Expected:** Approved. The client message says why and what the policy covers. The insurer message shows a low score.

## 2. Human review: amount above the limit
- **Full name:** Sarra Trabelsi
- **Email:** your own email
- **Date:** 2026-10-11 · **Time:** 10:15
- **Map:** search `Les Berges du Lac, Tunis`, pin a car park
- **What happened?**
  > While parking at the shopping centre car park, I misjudged the distance and hit a concrete pillar with the front of my car. The front bumper, the headlight and the wing are damaged.
- **Photos:** `front_damage.jpg`
- **Invoice:** `invoice_F-2026-2077.pdf` (front bumper, headlight, wing, support, labour: 3,736.60 TND)

**Expected:** Human review, because the amount is above the automatic approval limit. The client is told an adjuster will contact them, together with what the policy says.

## 3. Human review: story does not match the photo
- **Full name:** Youssef Gharbi
- **Email:** your own email
- **Date:** 2026-10-09 · **Time:** 08:50
- **Map:** search `Avenue de la Liberté, Tunis`, pin it
- **What happened?**
  > My car was parked in the street. When I came back, someone had hit my rear bumper and left without leaving a note.
- **Photos:** `side_damage.jpg` (it actually shows dented side doors)
- **Invoice:** `invoice_F-2026-1990.pdf` (front and rear doors, labour: 1,915.90 TND)

**Expected:** Human review with DAMAGE_MISMATCH (+20) in the insurer message: the photo shows the side doors, not the rear bumper.

## 4. Fraud: reused photos (run after scenario 1)
- **Full name:** Karim Mansouri
- **Email:** your own email
- **Date:** 2026-10-16 · **Time:** 12:30
- **Map:** search `Ariana`, pin any street
- **What happened?**
  > A van reversed out of a parking space and hit the back of my car. The rear bumper is damaged.
- **Photos:** `rear_bumper_1.jpg`, `rear_bumper_2_closeup.jpg` (the same files as scenario 1)
- **Invoice:** `invoice_F-2026-2133.pdf` (1,011.50 TND)

**Expected:** Fraud investigation with PHOTO_REUSED (+40), naming scenario 1's claim. The client message only says the claim is under review and never mentions fraud. The insurer message gives the evidence.

## 5. Fraud: several warning signs
- **Full name:** Nadia Jlassi
- **Email:** your own email
- **Date:** 2026-10-13 · **Time:** 14:00
- **Map:** search `Avenue Hédi Nouira, Ennasr`, pin it
- **What happened?**
  > I was waiting at a red light when a car hit me from behind. My rear bumper, the left rear light and the tailgate are damaged.
- **Photos:** `damage.jpg` (a crushed front end, with a photo date of 2026-09-02)
- **Invoice:** `invoice_F-2026-2150.pdf` (rear bumper, rear light, tailgate. The Total HT is 3,650 but the lines add up to 4,150)

**Expected:** Fraud investigation. Warning signs: DAMAGE_MISMATCH (+20), PHOTO_BEFORE_INCIDENT (+15), INVOICE_ARITHMETIC (+15), PART_NOT_VISIBLE (up to +15), and probably INCIDENT_IMPLAUSIBLE.

## 6. Rejected: date in the future
- **Full name:** Mehdi Bouaziz
- **Email:** your own email
- **Date:** 2026-12-20 · **Time:** 09:00
- **Map:** search `Sousse`, pin any street
- **What happened?**
  > Someone scratched the front left door of my car while it was parked.
- **Photos:** `door_scratch.jpg`
- **Invoice:** `invoice_F-2026-2201.pdf`

**Expected:** Rejected straight away, with the reason "incident_date is in the future". No AI agent runs.

---

### If a result differs
The AI agents are not deterministic. For example, Gemini may judge a photo differently, or the AI adjustment can push a borderline score over a threshold. Open the run of workflow 04 in n8n (Executions) and look at **Rule Score** and **Decide Route**: they list every warning sign with its points.
