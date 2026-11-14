"""GST pricing math for Newdru products.

User enters BUY PRICE inclusive of GST. All downstream figures derive from that.
"""
from typing import Dict


def compute_pricing(buy_price: float, gst_rate: float, sell_price: float | None = None) -> Dict[str, float]:
    """Return the full pricing block.

    Buy 118, GST 18 -> base 100, input_gst 18, recommended 236,
    if sell_price = 236 -> sell_ex_gst 200, output_gst 36, margin 100 (50%), net_gst_payable 18.
    """
    buy_price = float(buy_price or 0)
    gst_rate = float(gst_rate or 0)
    r = gst_rate / 100.0

    base_cost = buy_price / (1 + r) if (1 + r) > 0 else 0.0
    input_gst = buy_price - base_cost
    recommended = (2 * base_cost) * (1 + r)

    if sell_price is None or sell_price <= 0:
        sell_price = recommended

    sell_ex_gst = sell_price / (1 + r) if (1 + r) > 0 else 0.0
    output_gst = sell_price - sell_ex_gst
    gst_margin_amount = sell_ex_gst - base_cost
    # Spec: margin as a % of sell_ex_gst (i.e., gross-margin definition, not markup).
    # Worked example: buy 118 → sell 236 → margin 100, pct 50%.
    gst_margin_pct = (gst_margin_amount / sell_ex_gst * 100) if sell_ex_gst > 0 else 0.0
    net_gst_payable = output_gst - input_gst

    return {
        "buy_price": round(buy_price, 2),
        "gst_rate": gst_rate,
        "base_cost": round(base_cost, 2),
        "input_gst": round(input_gst, 2),
        "recommended_sell_price": round(recommended, 2),
        "sell_price": round(sell_price, 2),
        "sell_price_ex_gst": round(sell_ex_gst, 2),
        "output_gst": round(output_gst, 2),
        "gst_margin_amount": round(gst_margin_amount, 2),
        "gst_margin_pct": round(gst_margin_pct, 2),
        "net_gst_payable": round(net_gst_payable, 2),
    }


def redact_cost_fields(product: dict) -> dict:
    """Strip cost/margin fields from a product dict (for cashier view)."""
    hidden = {"buy_price", "base_cost", "input_gst", "recommended_sell_price",
              "gst_margin_amount", "gst_margin_pct", "net_gst_payable",
              "output_gst", "sell_price_ex_gst"}
    return {k: v for k, v in product.items() if k not in hidden}
