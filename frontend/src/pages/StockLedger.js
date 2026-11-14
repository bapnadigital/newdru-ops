import { useEffect, useState } from "react";
import api, { fmtDate, LOCATION_LABEL } from "@/lib/api";
import { ArrowUpRight, ArrowDownRight } from "lucide-react";

export default function StockLedger() {
  const [rows, setRows] = useState([]);
  const [filter, setFilter] = useState({ location: "", type: "" });

  const load = () => {
    const p = {};
    if (filter.location) p.location_code = filter.location;
    if (filter.type) p.movement_type = filter.type;
    api.get("/stock/movements", { params: p }).then((r) => setRows(r.data));
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);

  return (
    <div className="space-y-5" data-testid="ledger-page">
      <div>
        <h1 className="text-3xl font-brand text-slate-900">Stock Ledger</h1>
        <p className="text-sm text-slate-500 mt-1">Immutable record of every quantity change.</p>
      </div>

      <div className="card-surface p-4 flex flex-wrap gap-3">
        <select value={filter.location} onChange={(e) => setFilter({ ...filter, location: e.target.value })} className="border border-slate-300 rounded px-3 py-2 text-sm bg-white">
          <option value="">All locations</option>
          <option value="STORE">Newdru Store</option>
          <option value="BHIWANDI">Bhiwandi Warehouse</option>
          <option value="AMAZON_FC">Amazon FC</option>
          <option value="FLIPKART_FC">Flipkart FC</option>
        </select>
        <select value={filter.type} onChange={(e) => setFilter({ ...filter, type: e.target.value })} className="border border-slate-300 rounded px-3 py-2 text-sm bg-white">
          <option value="">All movement types</option>
          <option value="sale">Sale</option>
          <option value="goods_receipt">Goods receipt</option>
          <option value="transfer_out">Transfer out</option>
          <option value="transfer_in">Transfer in</option>
          <option value="adjustment">Adjustment</option>
        </select>
      </div>

      <div className="card-surface overflow-hidden">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th>When</th><th>SKU</th><th>Location</th><th>Type</th>
              <th className="text-right">Delta</th><th>User</th><th>Reason / Ref</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan="7" className="text-center py-8 text-slate-500">No movements yet.</td></tr>}
            {rows.map((m) => (
              <tr key={m.id}>
                <td className="text-xs">{fmtDate(m.created_at)}</td>
                <td className="font-mono text-xs">{m.sku}</td>
                <td>{LOCATION_LABEL[m.location_code] || m.location_code}</td>
                <td><span className="text-xs px-2 py-0.5 rounded-full bg-slate-100 text-slate-700 capitalize">{m.movement_type.replace("_", " ")}</span></td>
                <td className="text-right font-semibold">
                  <span className={m.quantity_delta >= 0 ? "text-green-600" : "text-red-500"}>
                    {m.quantity_delta >= 0 ? <ArrowUpRight size={12} className="inline" /> : <ArrowDownRight size={12} className="inline" />}
                    {' '}{m.quantity_delta}
                  </span>
                </td>
                <td className="text-xs text-slate-500">{m.user_name || "—"}</td>
                <td className="text-xs text-slate-500">{m.reason || m.reference_id || "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
