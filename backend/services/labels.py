"""Barcode + label + invoice PDF generation."""
import io
from typing import List, Dict
from barcode import Code128
from barcode.writer import ImageWriter, SVGWriter
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from PIL import Image


def _barcode_png(value: str) -> Image.Image:
    buf = io.BytesIO()
    Code128(str(value), writer=ImageWriter()).write(
        buf, options={"write_text": False, "module_height": 12.0, "quiet_zone": 2.0}
    )
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def generate_code128_svg(code: str) -> str:
    buf = io.BytesIO()
    Code128(str(code), writer=SVGWriter()).write(
        buf, options={"module_height": 10.0, "quiet_zone": 2.0}
    )
    return buf.getvalue().decode("utf-8")


def generate_labels_pdf(items: List[Dict], label_width_mm: float = 50, label_height_mm: float = 30) -> bytes:
    """items: [{name, mrp, sell_price, barcode, qty}, ...]"""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    margin = 8 * mm
    lw = label_width_mm * mm
    lh = label_height_mm * mm
    cols = max(1, int((page_w - 2 * margin) / lw))
    rows = max(1, int((page_h - 2 * margin) / lh))
    per_page = cols * rows

    flat = []
    for l in items:
        cnt = int(l.get("qty") or l.get("count") or 1)
        for _ in range(cnt):
            flat.append(l)

    if not flat:
        c.setFont("Helvetica", 12)
        c.drawString(20 * mm, page_h - 20 * mm, "No labels selected.")
        c.save()
        return buf.getvalue()

    for idx, lbl in enumerate(flat):
        pos = idx % per_page
        if idx > 0 and pos == 0:
            c.showPage()
        col = pos % cols
        row = pos // cols
        x = margin + col * lw
        y = page_h - margin - (row + 1) * lh

        c.setLineWidth(0.3)
        c.rect(x, y, lw, lh)

        c.setFont("Helvetica-Bold", 7)
        name = (lbl.get("name") or "")[:32]
        c.drawString(x + 2 * mm, y + lh - 4 * mm, name)

        c.setFont("Helvetica", 6)
        mrp = float(lbl.get("mrp") or 0)
        sp = float(lbl.get("sell_price") or 0)
        c.drawString(x + 2 * mm, y + lh - 7 * mm, f"MRP Rs.{mrp:.2f}")
        c.setFont("Helvetica-Bold", 8)
        c.drawRightString(x + lw - 2 * mm, y + lh - 7 * mm, f"Rs.{sp:.2f}")

        code = lbl.get("barcode") or lbl.get("sku") or "0000"
        try:
            img = _barcode_png(code)
            ir = ImageReader(img)
            c.drawImage(ir, x + 2 * mm, y + 3 * mm, width=lw - 4 * mm, height=lh - 12 * mm,
                        preserveAspectRatio=True, anchor="c")
        except Exception:
            pass

        c.setFont("Helvetica", 5)
        c.drawCentredString(x + lw / 2, y + 1.5 * mm, str(code))

    c.save()
    return buf.getvalue()


# Backward-compat alias for any existing callers
build_labels_pdf = generate_labels_pdf


def generate_invoice_pdf(sale: dict, business: dict) -> bytes:
    """GST-compliant tax invoice."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4
    y = page_h - 20 * mm

    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, y, business.get("name", "Newdru"))
    y -= 6 * mm
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, y, f"GSTIN: {business.get('gstin', '')}")
    y -= 5 * mm
    c.drawString(20 * mm, y, "Tax Invoice")
    y -= 8 * mm

    c.setFont("Helvetica-Bold", 10)
    c.drawString(20 * mm, y, f"Invoice #: {sale.get('invoice_no')}")
    c.drawString(120 * mm, y, f"Date: {(sale.get('created_at') or '')[:19].replace('T', ' ')}")
    y -= 6 * mm

    c.setFont("Helvetica", 9)
    if sale.get("customer_name"):
        c.drawString(20 * mm, y, f"Customer: {sale.get('customer_name', '')}  {sale.get('customer_phone', '') or ''}")
        y -= 6 * mm

    c.setFont("Helvetica-Bold", 8)
    headers = ["#", "Item", "HSN", "Qty", "Rate", "GST%", "Amount"]
    xs = [20, 30, 90, 108, 120, 140, 160]
    for h, xi in zip(headers, xs):
        c.drawString(xi * mm, y, h)
    y -= 2 * mm
    c.line(20 * mm, y, 195 * mm, y)
    y -= 4 * mm

    c.setFont("Helvetica", 8)
    for i, line in enumerate(sale.get("lines", []), 1):
        qty = line["quantity"]
        rate = line["unit_price"]
        gst_rate = line["gst_rate"]
        amount = qty * rate - line.get("line_discount", 0)
        c.drawString(20 * mm, y, str(i))
        c.drawString(30 * mm, y, line["name"][:32])
        c.drawString(90 * mm, y, line.get("hsn_code") or "")
        c.drawRightString(118 * mm, y, str(qty))
        c.drawRightString(138 * mm, y, f"{rate:.2f}")
        c.drawRightString(155 * mm, y, f"{gst_rate:.0f}%")
        c.drawRightString(195 * mm, y, f"{amount:.2f}")
        y -= 5 * mm

    y -= 3 * mm
    c.line(20 * mm, y, 195 * mm, y)
    y -= 5 * mm

    c.setFont("Helvetica-Bold", 9)
    c.drawString(20 * mm, y, "GST Breakup:")
    y -= 5 * mm
    c.setFont("Helvetica", 8)
    for rate, agg in (sale.get("gst_breakup") or {}).items():
        c.drawString(25 * mm, y, f"@ {rate}% - Taxable Rs.{agg['taxable']:.2f}  GST Rs.{agg['gst']:.2f}")
        y -= 4 * mm

    y -= 3 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawRightString(155 * mm, y, "Subtotal (ex-GST):")
    c.drawRightString(195 * mm, y, f"Rs.{sale['subtotal_ex_gst']:.2f}")
    y -= 5 * mm
    c.drawRightString(155 * mm, y, "Total GST:")
    c.drawRightString(195 * mm, y, f"Rs.{sale['total_gst']:.2f}")
    y -= 5 * mm
    if sale.get("cart_discount"):
        c.drawRightString(155 * mm, y, "Cart Discount:")
        c.drawRightString(195 * mm, y, f"-Rs.{sale['cart_discount']:.2f}")
        y -= 5 * mm
    c.setFont("Helvetica-Bold", 12)
    c.drawRightString(155 * mm, y, "Grand Total:")
    c.drawRightString(195 * mm, y, f"Rs.{sale['grand_total']:.2f}")
    y -= 8 * mm

    c.setFont("Helvetica", 8)
    for pay in sale.get("payments", []):
        c.drawString(20 * mm, y, f"Payment: {pay['method'].upper()} Rs.{pay['amount']:.2f}")
        y -= 4 * mm

    y -= 8 * mm
    c.setFont("Helvetica-Oblique", 8)
    c.drawString(20 * mm, y, "Thank you for shopping with Newdru.")

    c.showPage()
    c.save()
    return buf.getvalue()
