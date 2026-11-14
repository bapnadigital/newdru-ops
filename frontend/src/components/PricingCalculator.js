import { useMemo } from "react";
import { inr } from "@/lib/api";

/**
 * Pricing calculator matching backend logic.
 * Buy Price (incl GST) -> Base Cost = Buy/(1+g); Input GST = Buy-Base
 * Recommended = 2*Base * (1+g); Sell defaults to Recommended
 * Sell ex-GST = Sell/(1+g); Output GST = Sell-Sell_ex
 * Margin = Sell_ex - Base; Net GST payable = Output - Input
 */
export function calcPricing(buyIncl, gstRate, sellPrice) {
  const g = Number(gstRate || 0) / 100;
  const buy = Number(buyIncl || 0);
  const base = 1 + g === 0 ? 0 : buy / (1 + g);
  const inputGst = buy - base;
  const recommended = Math.round(2 * base * (1 + g) * 100) / 100;
  const sp = Number(sellPrice) > 0 ? Number(sellPrice) : recommended;
  const spEx = 1 + g === 0 ? 0 : sp / (1 + g);
  const outputGst = sp - spEx;
  const marginAmt = spEx - base;
  const marginPct = base > 0 ? (marginAmt / base) * 100 : 0;
  const netGst = outputGst - inputGst;
  return {
    base_cost: base, input_gst: inputGst, recommended_sell_price: recommended,
    sell_price: sp, sell_price_ex_gst: spEx, output_gst: outputGst,
    gst_margin_amount: marginAmt, gst_margin_pct: marginPct, net_gst_payable: netGst,
  };
}

export default function PricingCalculator({ buyIncl, gstRate, sellPrice, onChange }) {
  const p = useMemo(() => calcPricing(buyIncl, gstRate, sellPrice), [buyIncl, gstRate, sellPrice]);
  return (
    <div className="card-surface p-4" style={{ background: "#FFF9F8" }}>
      <div className="text-xs uppercase tracking-widest font-semibold mb-3" style={{ color: "#D84038" }}>
        Pricing (auto-calculated)
      </div>
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Buy Price (incl GST) ₹</label>
          <input data-testid="pricing-buy-input" type="number" step="0.01" value={buyIncl}
                 onChange={(e) => onChange({ buy_price_incl_gst: parseFloat(e.target.value || 0) })}
                 className="w-full border border-slate-300 rounded-md px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">GST Rate %</label>
          <input data-testid="pricing-gst-input" type="number" step="0.01" value={gstRate}
                 onChange={(e) => onChange({ gst_rate: parseFloat(e.target.value || 0) })}
                 className="w-full border border-slate-300 rounded-md px-2 py-1.5" />
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Sell Price ₹ (editable)</label>
          <input data-testid="pricing-sell-input" type="number" step="0.01"
                 placeholder={p.recommended_sell_price.toFixed(2)}
                 value={sellPrice || ""}
                 onChange={(e) => onChange({ sell_price: parseFloat(e.target.value || 0) })}
                 className="w-full border border-slate-300 rounded-md px-2 py-1.5" />
        </div>
      </div>
      <div className="mt-4 grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
        <Cell label="Base Cost" value={inr(p.base_cost)} />
        <Cell label="Input GST" value={inr(p.input_gst)} />
        <Cell label="Recommended Sell" value={inr(p.recommended_sell_price)} highlight />
        <Cell label="Sell ex-GST" value={inr(p.sell_price_ex_gst)} />
        <Cell label="Output GST" value={inr(p.output_gst)} />
        <Cell label="GST Margin" value={`${inr(p.gst_margin_amount)} (${p.gst_margin_pct.toFixed(1)}%)`}
              accent={p.gst_margin_pct >= 40 ? "ok" : p.gst_margin_pct >= 20 ? "warn" : "danger"} />
        <Cell label="Net GST Payable" value={inr(p.net_gst_payable)} />
      </div>
    </div>
  );
}

function Cell({ label, value, highlight, accent }) {
  const color = accent === "ok" ? "text-emerald-700" : accent === "warn" ? "text-amber-700" : accent === "danger" ? "text-red-700" : "text-slate-800";
  return (
    <div className={`bg-white rounded border border-slate-200 p-2 ${highlight ? "ring-1" : ""}`} style={highlight ? { boxShadow: "0 0 0 1px #F0544A55" } : {}}>
      <div className="text-[10px] uppercase tracking-widest text-slate-500">{label}</div>
      <div className={`font-semibold font-mono ${color}`}>{value}</div>
    </div>
  );
}
