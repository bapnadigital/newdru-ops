"""Warranty certificate PDF (A4, single page)."""
from io import BytesIO
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm
from reportlab.pdfgen import canvas


BRAND = colors.HexColor("#F0544A")
BRAND_LIGHT = colors.HexColor("#FDECEA")
INK = colors.HexColor("#0F172A")
MUTED = colors.HexColor("#64748B")


def _iso_to_date_str(iso: str) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d %b %Y")
    except Exception:
        return iso[:10]


def render_certificate(reg: dict, product: dict) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4

    # Top brand band
    c.setFillColor(BRAND_LIGHT)
    c.rect(0, H - 5.2 * cm, W, 5.2 * cm, stroke=0, fill=1)
    c.setFillColor(BRAND)
    c.setFont("Helvetica-Bold", 28)
    c.drawString(2 * cm, H - 2.6 * cm, "Newdru")
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(2 * cm, H - 3.7 * cm, "Warranty Certificate")
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 10)
    c.drawString(2 * cm, H - 4.4 * cm, "6-month manufacturing-defect warranty · Newdru Retail Pvt Ltd")

    # Warranty ID pill (right)
    wid = reg.get("warranty_id", "—")
    c.setFillColor(BRAND)
    c.roundRect(W - 6.5 * cm, H - 3.4 * cm, 4.5 * cm, 1.1 * cm, 0.3 * cm, stroke=0, fill=1)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(W - 4.25 * cm, H - 2.75 * cm, f"#{wid}")

    # Product block
    y = H - 7 * cm
    c.setFillColor(INK)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(2 * cm, y, "Product")
    c.setFont("Helvetica", 11)
    c.setFillColor(INK)
    c.drawString(2 * cm, y - 0.7 * cm, product.get("name", "—")[:70])
    c.setFillColor(MUTED)
    c.setFont("Helvetica", 9)
    c.drawString(2 * cm, y - 1.2 * cm, f"SKU: {product.get('sku','—')}")

    def kv(x, y0, label, value):
        c.setFillColor(MUTED); c.setFont("Helvetica", 9)
        c.drawString(x, y0, label.upper())
        c.setFillColor(INK); c.setFont("Helvetica-Bold", 11)
        c.drawString(x, y0 - 0.55 * cm, str(value or "—")[:40])

    y2 = H - 10 * cm
    kv(2 * cm,  y2, "Customer",       reg.get("name"))
    kv(9 * cm,  y2, "Email",          reg.get("email"))
    kv(2 * cm,  y2 - 1.8 * cm, "Phone",          reg.get("phone"))
    kv(9 * cm,  y2 - 1.8 * cm, "Date of Purchase", _iso_to_date_str(reg.get("purchase_date")))
    kv(2 * cm,  y2 - 3.6 * cm, "Purchase Channel", reg.get("purchase_source"))
    kv(9 * cm,  y2 - 3.6 * cm, "Registered On",  _iso_to_date_str(reg.get("created_at")))

    # Coverage band
    y3 = H - 18 * cm
    c.setFillColor(colors.HexColor("#F1F5F9"))
    c.rect(2 * cm, y3, W - 4 * cm, 3 * cm, stroke=0, fill=1)
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 12)
    c.drawString(2.4 * cm, y3 + 2.2 * cm, "Coverage")
    c.setFillColor(MUTED); c.setFont("Helvetica", 10)
    c.drawString(2.4 * cm, y3 + 1.5 * cm, "Manufacturing defects only. Excludes physical damage, water/liquid damage,")
    c.drawString(2.4 * cm, y3 + 1.0 * cm, "unauthorised repair, wear-and-tear, or missing invoice.")
    c.setFillColor(INK); c.setFont("Helvetica-Bold", 11)
    c.drawString(2.4 * cm, y3 + 0.35 * cm,
                 f"Valid: {_iso_to_date_str(reg.get('warranty_start'))}  →  {_iso_to_date_str(reg.get('warranty_end'))}")

    # Footer
    c.setFillColor(MUTED); c.setFont("Helvetica", 8)
    c.drawString(2 * cm, 1.5 * cm, "To raise a claim visit newdru.com/pages/warranty-registration or email hello@newdru.com")
    c.drawRightString(W - 2 * cm, 1.5 * cm, f"Issued {datetime.utcnow().strftime('%d %b %Y')}")

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()
