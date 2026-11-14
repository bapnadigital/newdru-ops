import { useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";
import { Download } from "lucide-react";

export default function Inventory() {
  const { user } = useAuth();
  const isStoreOnly = ["store_manager", "cashier"].includes(user?.role);
  const [data, setData] = useState({ locations: [], rows: [] });
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/inventory/grid", {
        params: { q: q || undefined, filter: filter || undefined },
      });
      setData(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [filter]);

  const updateThreshold = async (product_id, location_code, low_stock_threshold) => {
    try {
      await api.post("/inventory/threshold", { product_id, location_code, low_stock_threshold });
      toast.success("Threshold updated");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const download = async () => {
    try {
      const res = await api.get("/reports/inventory/csv", { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a"); a.href = url; a.download = "inventory.csv"; a.click();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">
            {isStoreOnly ? "Store Stock" : "Unified Inventory"}
          </h1>
          <p className="text-slate-500 text-sm">
            {isStoreOnly
              ? "Live stock at Newdru Store. Warehouse and Amazon/Flipkart FC visibility is limited to the warehouse team."
              : "Store, Bhiwandi, Amazon FC & Flipkart FC — live view across all locations."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input placeholder="Search SKU / name / barcode…" value={q} onChange={(e) => setQ(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && load()}
                 className="px-3 py-2 text-sm border border-slate-300 rounded-md w-full md:w-64" />
          <select data-testid="inv-filter" value={filter} onChange={(e) => setFilter(e.target.value)}
                  className="px-2 py-2 text-sm border border-slate-300 rounded-md">
            <option value="">All</option>
            <option value="low_stock">Low stock</option>
            <option value="out_of_stock">Out of stock</option>
          </select>
          <button onClick={download} className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50 flex items-center gap-1"><Download size={14} />CSV</button>
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md overflow-hidden">
        <div className="overflow-x-auto scroll-thin">
          <table className="newdru-table">
            <thead>
              <tr>
                <th>SKU</th><th>Name</th><th>Barcode</th>
                {(data.locations || []).map((l) => (
                  <th key={l.code} className="text-right">
                    <div>{l.code}</div>
                    {!l.editable && <div className="text-[10px] text-slate-400 normal-case">read-only</div>}
                  </th>
                ))}
                <th className="text-right">Total</th>
                <th>Last synced</th>
              </tr>
            </thead>
            <tbody>
              {(data.rows || []).map((row) => (
                <tr key={row.product_id}>
                  <td className="mono">{row.sku}</td>
                  <td>{row.name}</td>
                  <td className="mono text-xs">{row.barcode}</td>
                  {data.locations.map((l) => {
                    const cell = row.locations?.[l.code] || {};
                    return (
                      <td key={l.code} className="text-right mono">
                        <div className={`${cell.quantity <= (cell.threshold || 5) && cell.editable ? "text-red-600 font-semibold" : ""}`}>
                          {cell.quantity ?? 0}
                        </div>
                        {cell.editable && (
                          <input data-testid={`threshold-${row.sku}-${l.code}`} type="number" defaultValue={cell.threshold ?? 5}
                                 onBlur={(e) => updateThreshold(row.product_id, l.code, parseInt(e.target.value || 0))}
                                 className="w-14 text-xs border border-slate-200 rounded px-1 py-0.5 mt-1" title="Low-stock threshold" />
                        )}
                      </td>
                    );
                  })}
                  <td className="text-right mono font-semibold">{row.total}</td>
                  <td className="text-xs text-slate-500">
                    {(() => {
                      const cells = Object.values(row.locations || {}).filter((c) => !c.editable && c.last_synced_at);
                      const latest = cells.length ? cells.sort((a, b) => (b.last_synced_at > a.last_synced_at ? 1 : -1))[0] : null;
                      return latest ? new Date(latest.last_synced_at).toLocaleString() : "—";
                    })()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {loading && <div className="p-4 text-sm text-slate-500">Loading…</div>}
        {!loading && (data.rows || []).length === 0 && <div className="p-8 text-center text-slate-500">No inventory rows.</div>}
      </div>
    </div>
  );
}
