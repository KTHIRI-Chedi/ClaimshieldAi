"""Generate synthetic repair invoices for the Invoice Parser Agent.

Writes to data/invoices/:
  - text      : PDF with a text layer (native extraction path)
  - scanned   : image-only PDF (LlamaParse OCR path)
  - image     : PNG photo of an invoice (OCR path)
  - mixed     : scanned page + a text footer without amounts (must still go to OCR)
  - letter    : a document that is not an invoice (needs_review)
  - expected.json: expected status / extraction method / amounts for each file

Usage: python scripts/generate_test_invoices.py
"""
import json
import random
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parent.parent / "data" / "invoices"
W, H = A4


def L(d, q, p, cat="part", disc=0, vat=19):
    return {"d": d, "q": q, "p": p, "cat": cat, "disc": disc, "vat": vat}


MANY_PARTS = [L(f"Pièce réf. {1000 + i} - clip/agrafe/vis lot {i}", 1 + i % 3, 4.5 + i) for i in range(48)]

INVOICES = [
    # --- original set (same outcomes as before) ---
    dict(id="INV-001", kind="text", garage="Garage Ennour Auto", date="2026-09-12", plate="123 TU 4567",
         claim="CLM-1001", lines=[L("Front bumper", 1, 420), L("Left headlight", 1, 310), L("Paint (front)", 1, 180, "paint")],
         labor=(6, 45), expect="ok"),
    dict(id="INV-002", kind="text", garage="Carrosserie El Amen", date="2026-09-20", plate="210 TU 8812",
         claim="CLM-1002", lines=[L("Rear bumper", 1, 380), L("Tail light right", 2, 145), L("Trunk lid", 1, 650)],
         labor=(8, 45), tamper="subtotal", expect="arithmetic_mismatch"),
    dict(id="INV-003", kind="scanned", garage="Auto Service Lac", date="2026-10-01", plate="198 TU 3321",
         claim="CLM-1003", lines=[L("Windshield", 1, 520), L("Windshield seal", 1, 35)], labor=(2, 45), expect="ok"),
    dict(id="INV-004", kind="scanned", garage="Garage Sfax Motors", date="2026-10-03", plate="175 TU 9090",
         claim="CLM-1004", lines=[L("Right door", 1, 890), L("Side mirror right", 1, 210), L("Door handle", 1, 60)],
         labor=(5, 45), tamper="line_total", expect="arithmetic_mismatch"),
    # --- realistic Tunisian invoices ---
    dict(id="INV-005", kind="text", style="fr", garage="Garage El Fejja", date="2026-10-05", plate="201 TU 1450",
         claim="CLM-1005", lines=[L("Pare-choc avant", 1, 465.5, disc=10), L("Calandre", 1, 189.9),
                                  L("Antibrouillard gauche", 1, 74.25, disc=5)],
         labor=(4, 40), charges=[("Timbre fiscal", 1.0)], expect="ok"),
    dict(id="INV-006", kind="text", style="fr", garage="Carrosserie Ben Arous", date="2026-10-06", plate="187 TU 7766",
         claim="CLM-1006", lines=[L("Capot", 1, 980), L("Phare droit", 1, 335), L("Peinture capot", 1, 260, "paint")],
         labor=(7, 40), discount=120, charges=[("Timbre fiscal", 1.0)], tamper="total", expect="arithmetic_mismatch"),
    dict(id="INV-007", kind="text", style="fr", garage="Auto Pro Sousse", date="2026-10-07", plate="222 TU 3030",
         claim="CLM-1007", tax="multi",
         lines=[L("Aile avant droite", 1, 410), L("Rétroviseur droit", 1, 165),
                L("Main d'oeuvre carrosserie", 6, 40, "labor", vat=7), L("Ingrédients peinture", 1, 85, "consumable")],
         charges=[("Timbre fiscal", 1.0)], expect="ok"),
    dict(id="INV-008", kind="text", style="fr", garage="Vitrage Express Ariana", date="2026-10-08", plate="230 TU 5512",
         claim="CLM-1008", tax="ttc", lines=[L("Pare-brise athermique", 1, 690.2), L("Joint pare-brise", 1, 42.84),
                                             L("Pose", 1, 95.2, "labor")],
         charges=[("Timbre fiscal", 1.0)], expect="ok"),
    dict(id="INV-009", kind="text", style="fr", garage="Garage Central Nabeul", date="2026-10-09", plate="199 TU 8080",
         claim="CLM-1009", lines=MANY_PARTS, labor=(12, 40), charges=[("Timbre fiscal", 1.0)], expect="ok"),
    dict(id="INV-010", kind="image", style="fr", garage="Garage Bizerte Auto", date="2026-10-10", plate="215 TU 4321",
         claim="CLM-1010", lines=[L("Porte arrière gauche", 1, 720), L("Poignée extérieure", 1, 48.5),
                                  L("Main d'oeuvre", 5, 40, "labor")],
         charges=[("Timbre fiscal", 1.0)], expect="ok"),
    dict(id="INV-011", kind="mixed", garage="Garage Monastir Service", date="2026-10-11", plate="240 TU 6006",
         claim="CLM-1011", lines=[L("Radiator", 1, 385), L("Coolant 5L", 1, 38, "consumable"), L("Fan shroud", 1, 92)],
         labor=(3, 45), expect="ok"),
    dict(id="INV-012", kind="letter", garage="Assuré: Mohamed Trabelsi", date="2026-10-12", claim="CLM-1012",
         expect="needs_review"),
]


def money(v, style):
    if style == "fr":
        return f"{v:,.3f}".replace(",", " ").replace(".", ",")
    return f"{v:,.2f}"


def compute(inv):
    """Return printed rows, summary rows, and the true figures."""
    style = inv.get("style", "en")
    fr = style == "fr"
    rows = []
    for li in inv["lines"]:
        amount = round(li["q"] * li["p"] * (1 - li["disc"] / 100), 3)
        rows.append({**li, "amount": amount})
    labor = None
    if inv.get("labor"):
        h, r = inv["labor"]
        labor = {"hours": h, "rate": r, "total": h * r}
    lines_sum = round(sum(r["amount"] for r in rows) + (labor["total"] if labor else 0), 3)
    discount = inv.get("discount", 0)
    net = round(lines_sum - discount, 3)
    charges = inv.get("charges", [])
    charges_sum = sum(a for _, a in charges)
    mode = inv.get("tax", "single")
    summary = []

    if mode == "ttc":
        total = round(net + charges_sum, 3)
        summary.append(("Total TTC", net))
        summary.append(("dont TVA 19%", round(net - net / 1.19, 3)))
    else:
        if discount:
            summary.append(("Sous-total" if fr else "Subtotal", lines_sum))
            summary.append(("Remise" if fr else "Discount", -discount))
        summary.append(("Total HT" if fr else "Subtotal", net))
        if mode == "multi":
            bases = {}
            for r in rows:
                bases[r["vat"]] = bases.get(r["vat"], 0) + r["amount"]
            tax = 0
            for rate, b in sorted(bases.items(), reverse=True):
                amt = round(b * rate / 100, 3)
                tax += amt
                summary.append((f"TVA {rate}% (base {money(b, style)})", amt))
        else:
            tax = round(net * 0.19, 3)
            summary.append(("TVA 19%" if fr else "VAT 19%", tax))
        total = round(net + tax + charges_sum, 3)
    for label, amt in charges:
        summary.append((label, amt))
    summary.append(("NET A PAYER (TND)" if fr else "TOTAL (TND)", total))

    tamper = inv.get("tamper")
    if tamper == "line_total":
        rows[0]["amount"] += 300
    elif tamper == "subtotal":
        summary = [(l, v + 450 if l in ("Subtotal", "Total HT") else v) for l, v in summary]
    elif tamper == "total":
        summary[-1] = (summary[-1][0], summary[-1][1] + 200)
    return rows, labor, summary, {"lines_sum": lines_sum, "net": net, "total": total}


def draw_invoice(c, inv, rows, labor, summary):
    style = inv.get("style", "en")
    fr = style == "fr"
    has_disc = any(r["disc"] for r in rows)
    multi = inv.get("tax") == "multi"

    def header():
        c.setFont("Helvetica-Bold", 16)
        c.drawString(40, H - 50, inv["garage"])
        c.setFont("Helvetica", 10)
        c.drawString(40, H - 68, "Facture de réparation" if fr else "Repair invoice / Facture de reparation")
        c.drawString(380, H - 50, f"{'Facture N°' if fr else 'Invoice No'}: {inv['id']}")
        c.drawString(380, H - 64, f"Date: {inv['date']}")
        c.drawString(380, H - 78, f"{'Réf. sinistre' if fr else 'Claim ref'}: {inv['claim']}")
        c.drawString(40, H - 100, f"{'Immatriculation' if fr else 'Vehicle plate'}: {inv['plate']}")
        if inv.get("tax") == "ttc":
            c.drawString(40, H - 114, "Prix unitaires TTC")

    def table_head(y):
        c.setFont("Helvetica-Bold", 9)
        cols = [(40, "Désignation" if fr else "Part"), (290, "Qté" if fr else "Qty"),
                (330, "P.U." if fr else "Unit price")]
        if has_disc:
            cols.append((400, "Remise"))
        if multi:
            cols.append((445, "TVA"))
        cols.append((490, "Montant" if fr else "Line total"))
        for x, t in cols:
            c.drawString(x, y, t)
        c.line(40, y - 4, 555, y - 4)
        c.setFont("Helvetica", 9)

    header()
    y = H - 140
    table_head(y)
    for r in rows:
        y -= 16
        if y < 70:
            c.drawString(40, 40, "Suite page suivante...")
            c.showPage()
            header()
            y = H - 140
            table_head(y)
            y -= 16
        c.drawString(40, y, r["d"])
        c.drawRightString(310, y, str(r["q"]))
        c.drawRightString(390, y, money(r["p"], style))
        if has_disc:
            c.drawRightString(435, y, f"{r['disc']}%" if r["disc"] else "")
        if multi:
            c.drawRightString(475, y, f"{r['vat']}%")
        c.drawRightString(550, y, money(r["amount"], style))
    if labor:
        y -= 16
        lab = "Main d'oeuvre" if fr else "Labor"
        c.drawString(40, y, f"{lab} ({labor['hours']} h x {money(labor['rate'], style)})")
        c.drawRightString(550, y, money(labor["total"], style))
    c.line(300, y - 8, 555, y - 8)
    for label, val in summary:
        y -= 18
        if y < 50:
            c.showPage()
            y = H - 60
        c.setFont("Helvetica-Bold" if label.startswith(("NET", "TOTAL")) else "Helvetica", 9)
        c.drawString(330, y, label)
        c.drawRightString(550, y, money(val, style))


def draw_letter(c, inv):
    c.setFont("Helvetica", 11)
    lines = [
        inv["garage"], "Rue de Marseille, Tunis", "", "A l'attention du service sinistres", "",
        f"Objet : déclaration de sinistre {inv['claim']}", "",
        "Madame, Monsieur,", "",
        "Suite à l'accident survenu le 2026-10-08, je vous adresse ma déclaration.",
        "Mon véhicule a été heurté à l'arrière alors qu'il était à l'arrêt au feu rouge.",
        "Le garage me communiquera prochainement sa facture de réparation.",
        "Je reste à votre disposition pour tout complément d'information.", "",
        "Veuillez agréer mes salutations distinguées.", "", "Mohamed Trabelsi",
    ]
    y = H - 60
    for line in lines:
        c.drawString(50, y, line)
        y -= 18


def render_pdf_bytes(inv):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    if inv["kind"] == "letter":
        draw_letter(c, inv)
        rows = labor = summary = truth = None
    else:
        rows, labor, summary, truth = compute(inv)
        draw_invoice(c, inv, rows, labor, summary)
    c.save()
    return buf.getvalue(), (rows, labor, summary, truth)


def degrade(img, seed):
    rnd = random.Random(seed)
    img = img.rotate(rnd.uniform(-1.5, 1.5), expand=False, fillcolor="white")
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    noise = Image.effect_noise(img.size, 18).convert("L")
    return Image.blend(img.convert("L"), noise, 0.08).convert("RGB")


def rasterize(pdf_bytes, dpi=150):
    doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    out = []
    for page in doc:
        pix = page.get_pixmap(dpi=dpi)
        out.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return out


def write(inv):
    pdf, (rows, labor, summary, truth) = render_pdf_bytes(inv)
    kind = inv["kind"]
    suffix = {"text": ".pdf", "letter": ".pdf", "scanned": "_scanned.pdf", "image": "_photo.png", "mixed": "_mixed.pdf"}
    path = OUT / f"{inv['id']}{suffix[kind]}"
    if kind in ("text", "letter"):
        path.write_bytes(pdf)
    elif kind == "scanned":
        pages = [degrade(p, inv["id"]) for p in rasterize(pdf)]
        pages[0].save(path, "PDF", resolution=150, save_all=True, append_images=pages[1:])
    elif kind == "image":
        degrade(rasterize(pdf)[0], inv["id"]).save(path, "PNG")
    elif kind == "mixed":
        img = degrade(rasterize(pdf)[0], inv["id"])
        c = canvas.Canvas(str(path), pagesize=A4)
        c.drawImage(ImageReader(img), 0, 0, width=W, height=H)
        c.setFont("Helvetica", 8)
        c.drawString(40, 30, f"Copie numérisée certifiée conforme - {inv['garage']} - document de réparation véhicule")
        c.save()
    expected = {"kind": kind, "expected_status": inv["expect"], "tamper": inv.get("tamper"),
                "expected_method": "native_pdf_text" if kind == "text" else
                                   None if kind == "letter" else "llamaparse_ocr"}
    if truth:
        expected.update(invoice_number=inv["id"], claim_ref=inv["claim"], n_lines=len(rows), **truth)
    return path, expected


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    expected = {}
    for inv in INVOICES:
        path, exp = write(inv)
        expected[path.name] = exp
        print("wrote", path.name)
    (OUT / "expected.json").write_text(json.dumps(expected, indent=2, ensure_ascii=False), encoding="utf-8")
    print("wrote expected.json")


if __name__ == "__main__":
    main()
