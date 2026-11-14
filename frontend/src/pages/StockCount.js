import { useEffect, useMemo, useRef, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { toast } from "sonner";

// Blind physical stock count: staff scan or type what is on the shelf.
// They never see the system quantity; the owner sees the differences.
export default function StockCount() {
  const { user } = useAuth();
  const defaultLoc = ["warehouse_manager", "warehouse_staff"].includes(user?.role) ? "BHIWANDI" : "STORE";
  const [loc, setLoc] = useState(defaultLoc);
  const [products, setProducts] = useState([]);
  const [counts, setCounts] = useState({});
  const [scan, setScan] = useState("");
  const [filter, setFilter] = useState("");
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [history, setHistory] = useState([]);
  const [openId, setOpenId] = useState(null);
  const scanRef = useRef(null);
  const canSeeHistory = ["owner", "store_manager", "warehouse_manager"].includes(user?.role);

  useEffect(() => {
    api.get("/inventory/count-sheet", { params: { location_code: loc } })
      .then((r) => { setProducts(r.data.products); setCounts({}); })
      .catch((e) => toast.error(formatApiError(e.response?.data?.detail)));
    if (canSeeHistory) api.get("/inventory/counts", { params: { location_code: loc } }).then((r) => setHistory(r.data)).catch(() => {});
  }, [loc, canSeeHistory]);

  const decide = async (id, action) => {
    try {
      await api.post(`/inventory/counts/${id}/${action}`);
      toast.success(action === "approve" ? "Approved: stock updated" : "Rejected: stock unchanged");
      setHistory((await api.get("/inventory/counts", { params: { location_code: loc } })).data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const bySku = useMemo(() => {
    const m = {};
    products.forEach((p) => { m[p.sku] = p; if (p.barcode) m[p.barcode] = p; });
    return m;
  }, [products]);

  const onScan = (e) => {
    e.preventDefault();
    const p = bySku[scan.trim()];
    if (!p) { toast.error("Not found: " + scan); setScan(""); return; }
    setCounts((c) => ({ ...c, [p.sku]: (Number(c[p.sku]) || 0) + 1 }));
    toast.success(`${p.name}: ${(Number(counts[p.sku]) || 0) + 1}`);
    setScan("");
    scanRef.current?.focus();
  };

  const shown = products.filter((p) => !filter || (p.name + " " + p.sku).toLowerCase().includes(filter.toLowerCase()));
  const entered = Object.entries(counts).filter(([, v]) => v !== "" && v !== undefined);

  const submit = async () => {
    if (entered.length === 0) return toast.error("Count at least one product");
    if (!window.confirm(`Save count for ${entered.length} products at ${loc}? Products you leave blank are not changed.`)) return;
    setSaving(true);
    try {
      const { data } = await api.post("/inventory/count", {
        location_code: loc, note: note || null,
        lines: entered.map(([sku, v]) => ({ sku, counted: Math.max(0, parseInt(v, 10) || 0) })),
      });
      toast.success(data.status === "pending"
        ? `Saved. ${data.items_counted} counted. A manager will check and approve it.`
        : `Saved. ${data.items_counted} counted, ${data.items_with_difference} different from the system.`);
      setCounts({}); setNote("");
      if (canSeeHistory) setHistory((await api.get("/inventory/counts", { params: { location_code: loc } })).data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setSaving(false);
  };

  return (
    <div>
      <div className="mb-4">
        <h1 className="text-2xl md:text-3xl font-brand text-slate-900">Stock count</h1>
        <p className="text-sm text-slate-500">Count what is physically on the shelf. Scan each item, or type the number. Leave a product blank if you didn't count it.</p>
      </div>

      <div className="card-surface p-4 mb-4 flex flex-wrap gap-3 items-end">
        {user?.role === "owner" && (
          <select value={loc} onChange={(e) => setLoc(e.target.value)} className="border border-slate-300 rounded-md px-3 py-2 text-sm">
            <option value="STORE">Store</option>
            <option value="BHIWANDI">Bhiwandi warehouse</option>
          </select>
        )}
        <form onSubmit={onScan} className="flex gap-2">
          <input ref={scanRef} autoFocus value={scan} onChange={(e) => setScan(e.target.value)} placeholder="Scan barcode (adds 1)"
                 data-testid="count-scan" className="border border-slate-300 rounded-md px-3 py-2 text-sm w-56" />
        </form>
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Search product" className="border border-slate-300 rounded-md px-3 py-2 text-sm w-48" />
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note (e.g. Sunday count)" className="border border-slate-300 rounded-md px-3 py-2 text-sm w-48" />
        <button data-testid="count-submit" onClick={submit} disabled={saving} className="btn-brand disabled:opacity-50">Save count ({entered.length})</button>
      </div>

      <div className="card-surface overflow-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-left text-slate-500 border-b"><th className="p-2">Product</th><th className="p-2">SKU</th><th className="p-2 w-32">Counted</th></tr></thead>
          <tbody>
            {shown.map((p) => (
              <tr key={p.sku} className="border-b last:border-0">
                <td className="p-2">{p.name}</td>
                <td className="p-2 font-mono text-xs">{p.sku}</td>
                <td className="p-2">
                  <input type="number" min="0" inputMode="numeric" value={counts[p.sku] ?? ""}
                         onChange={(e) => setCounts((c) => ({ ...c, [p.sku]: e.target.value }))}
                         className="border border-slate-300 rounded-md px-2 py-1 w-24" />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {canSeeHistory && history.length > 0 && (
        <div className="card-surface p-4 mt-4">
          <div className="font-semibold mb-2">Recent counts</div>
          <table className="w-full text-xs">
            <thead><tr className="text-left text-slate-500"><th>When</th><th>By</th><th>Counted</th><th>Different</th><th>Missing</th><th>Extra</th><th>Status</th><th></th></tr></thead>
            <tbody>{history.map((h) => (
              <tr key={h.id} className="border-t border-slate-100 align-top">
                <td className="py-1">{new Date(h.created_at).toLocaleString("en-IN")}</td><td>{h.counted_by}</td><td>{h.items_counted}</td>
                <td className={h.items_with_difference ? "text-red-600 font-semibold" : ""}>{h.items_with_difference}</td>
                <td>{h.units_missing}</td><td>{h.units_extra}</td>
                <td>{h.status === "pending" ? <span className="text-amber-700 font-semibold">Waiting for approval</span>
                     : h.status === "rejected" ? <span className="text-slate-500">Rejected</span>
                     : <span className="text-emerald-700">Applied{h.approved_by ? ` (by ${h.approved_by})` : ""}</span>}</td>
                <td className="text-right">
                  {(h.lines || []).some((l) => l.difference) && (
                    <button className="underline mr-2" onClick={() => setOpenId(openId === h.id ? null : h.id)}>{openId === h.id ? "Hide" : "Details"}</button>
                  )}
                  {h.status === "pending" && (<>
                    <button data-testid={`count-approve-${h.id}`} className="text-emerald-700 font-semibold mr-2" onClick={() => decide(h.id, "approve")}>Approve</button>
                    <button className="text-red-600" onClick={() => decide(h.id, "reject")}>Reject</button>
                  </>)}
                  {openId === h.id && (
                    <div className="text-left mt-1 bg-slate-50 rounded p-2">
                      {(h.lines || []).filter((l) => l.difference).map((l) => (
                        <div key={l.sku}>{l.name} ({l.sku}): system {l.system}, counted {l.counted} → <b className={l.difference < 0 ? "text-red-600" : "text-emerald-700"}>{l.difference > 0 ? "+" : ""}{l.difference}</b></div>
                      ))}
                    </div>
                  )}
                </td>
              </tr>))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
