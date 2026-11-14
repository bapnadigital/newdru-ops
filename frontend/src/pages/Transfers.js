import { useEffect, useState } from "react";
import api, { fmtDate, LOCATION_LABEL } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { Plus, ArrowRight, X, Trash2 } from "lucide-react";

const STATUS_COLORS = {
  requested: { bg: "#FEF3C7", color: "#92400E" },
  approved: { bg: "#DBEAFE", color: "#1E40AF" },
  dispatched: { bg: "#E0E7FF", color: "#3730A3" },
  received: { bg: "#DCFCE7", color: "#166534" },
  cancelled: { bg: "#FEE2E2", color: "#991B1B" },
};

function CreateTransferModal({ onClose, onCreated }) {
  const [fromLoc, setFromLoc] = useState("BHIWANDI");
  const [toLoc, setToLoc] = useState("STORE");
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [notes, setNotes] = useState("");

  const search = async (v) => {
    setQ(v);
    if (v.length < 2) { setResults([]); return; }
    const { data } = await api.get(`/products?q=${encodeURIComponent(v)}&limit=8`);
    setResults(data);
  };

  const addItem = (p) => {
    if (items.find((i) => i.product_id === p.id)) return;
    setItems([...items, { product_id: p.id, sku: p.sku, name: p.name, requested_qty: 1 }]);
    setQ(""); setResults([]);
  };

  const submit = async () => {
    if (items.length === 0) return;
    try {
      await api.post("/stock/transfers", { from_location: fromLoc, to_location: toLoc, items, notes });
      onCreated();
    } catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl w-full max-w-2xl p-6">
        <div className="flex justify-between items-center mb-4">
          <h3 className="font-brand text-lg">New transfer</h3>
          <button onClick={onClose} className="p-2 rounded hover:bg-slate-100"><X size={18} /></button>
        </div>
        <div className="grid grid-cols-2 gap-4 mb-4">
          <label className="block"><span className="text-xs uppercase text-slate-600 font-semibold">From</span>
            <select value={fromLoc} onChange={(e) => setFromLoc(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm bg-white">
              <option value="BHIWANDI">Bhiwandi Warehouse</option>
              <option value="STORE">Newdru Store</option>
            </select></label>
          <label className="block"><span className="text-xs uppercase text-slate-600 font-semibold">To</span>
            <select value={toLoc} onChange={(e) => setToLoc(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm bg-white">
              <option value="STORE">Newdru Store</option>
              <option value="BHIWANDI">Bhiwandi Warehouse</option>
            </select></label>
        </div>
        <div className="mb-3 relative">
          <input data-testid="transfer-search" value={q} onChange={(e) => search(e.target.value)} placeholder="Search a product to add…" className="w-full border border-slate-300 rounded px-3 py-2 text-sm" />
          {results.length > 0 && (
            <div className="absolute left-0 right-0 mt-1 border border-slate-200 rounded bg-white z-10 max-h-60 overflow-y-auto">
              {results.map((p) => (
                <div key={p.id} onClick={() => addItem(p)} className="p-2 hover:bg-slate-50 cursor-pointer text-sm">
                  <div className="font-medium">{p.name}</div>
                  <div className="text-xs text-slate-500 font-mono">{p.sku}</div>
                </div>
              ))}
            </div>
          )}
        </div>
        <table className="w-full text-sm mb-4">
          <thead><tr className="text-xs uppercase text-slate-500 text-left"><th className="pb-2">Item</th><th className="pb-2 text-right w-20">Qty</th><th></th></tr></thead>
          <tbody>
            {items.length === 0 && <tr><td colSpan="3" className="text-center py-4 text-slate-400">No items yet</td></tr>}
            {items.map((it, idx) => (
              <tr key={it.product_id} className="border-t border-slate-100">
                <td className="py-2"><div>{it.name}</div><div className="text-xs text-slate-500 font-mono">{it.sku}</div></td>
                <td className="py-2 text-right">
                  <input type="number" min="1" value={it.requested_qty} onChange={(e) => {
                    const next = [...items]; next[idx].requested_qty = Number(e.target.value || 1);
                    setItems(next);
                  }} className="w-16 border border-slate-300 rounded px-2 py-1 text-right text-sm" />
                </td>
                <td className="py-2"><button onClick={() => setItems(items.filter((_, i) => i !== idx))} className="p-1 text-red-500"><Trash2 size={14} /></button></td>
              </tr>
            ))}
          </tbody>
        </table>
        <label className="block mb-4"><span className="text-xs uppercase text-slate-600 font-semibold">Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm" placeholder="Optional" /></label>
        <div className="flex justify-end gap-2">
          <button onClick={onClose} className="btn-outline">Cancel</button>
          <button data-testid="transfer-create-submit" onClick={submit} disabled={items.length === 0 || fromLoc === toLoc} className="btn-brand">Create request</button>
        </div>
      </div>
    </div>
  );
}

export default function Transfers() {
  const { hasRole, user } = useAuth();
  const [rows, setRows] = useState([]);
  const [showCreate, setShowCreate] = useState(false);
  const [detail, setDetail] = useState(null);

  const load = () => api.get("/stock/transfers").then((r) => setRows(r.data));
  useEffect(() => { load(); }, []);

  const act = async (id, action, body) => {
    try {
      await api.post(`/stock/transfers/${id}/${action}`, body || {});
      load(); setDetail(null);
    } catch (e) { alert(e.response?.data?.detail || e.message); }
  };

  return (
    <div className="space-y-5" data-testid="transfers-page">
      <div className="flex justify-between items-center">
        <div>
          <h1 className="text-3xl font-brand text-slate-900">Transfers</h1>
          <p className="text-sm text-slate-500 mt-1">Move stock between Newdru Store and Bhiwandi Warehouse.</p>
        </div>
        {hasRole("owner", "store_manager", "warehouse_manager") && (
          <button data-testid="transfer-new-btn" onClick={() => setShowCreate(true)} className="btn-brand inline-flex items-center gap-2"><Plus size={16} />New transfer</button>
        )}
      </div>

      <div className="card-surface overflow-hidden">
        <table className="data-table w-full">
          <thead>
            <tr><th>ID</th><th>From → To</th><th>Items</th><th>Status</th><th>Created</th><th>By</th></tr>
          </thead>
          <tbody>
            {rows.length === 0 && <tr><td colSpan="6" className="text-center py-8 text-slate-500">No transfers yet.</td></tr>}
            {rows.map((t) => {
              const s = STATUS_COLORS[t.status] || STATUS_COLORS.requested;
              return (
                <tr key={t.id} className="cursor-pointer" onClick={() => setDetail(t)}>
                  <td className="font-mono text-[11px]">{t.id.slice(0, 8)}…</td>
                  <td>{LOCATION_LABEL[t.from_location]} <ArrowRight size={12} className="inline mx-1 text-slate-400" /> {LOCATION_LABEL[t.to_location]}</td>
                  <td>{t.items.length}</td>
                  <td><span className="text-xs px-2 py-0.5 rounded-full" style={{ background: s.bg, color: s.color }}>{t.status}</span></td>
                  <td className="text-xs">{fmtDate(t.created_at)}</td>
                  <td className="text-xs text-slate-500">{t.created_by_name || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {showCreate && <CreateTransferModal onClose={() => setShowCreate(false)} onCreated={() => { setShowCreate(false); load(); }} />}

      {detail && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl w-full max-w-2xl p-6 max-h-[90vh] overflow-y-auto">
            <div className="flex justify-between items-center mb-3">
              <h3 className="font-brand text-lg">Transfer detail</h3>
              <button onClick={() => setDetail(null)} className="p-2 rounded hover:bg-slate-100"><X size={18} /></button>
            </div>
            <div className="text-sm text-slate-600 mb-3">
              <div>{LOCATION_LABEL[detail.from_location]} → {LOCATION_LABEL[detail.to_location]}</div>
              <div className="text-xs mt-1">Status: <span className="font-semibold">{detail.status}</span></div>
            </div>
            <table className="w-full text-sm mb-4">
              <thead><tr className="text-xs uppercase text-slate-500 text-left"><th className="pb-2">Item</th><th className="text-right">Req</th><th className="text-right">Disp</th><th className="text-right">Recv</th></tr></thead>
              <tbody>
                {detail.items.map((it, idx) => (
                  <tr key={it.product_id || `item-${idx}`} className="border-t border-slate-100">
                    <td className="py-2"><div>{it.name}</div><div className="text-xs text-slate-500 font-mono">{it.sku}</div></td>
                    <td className="text-right">{it.requested_qty}</td>
                    <td className="text-right">{it.dispatched_qty}</td>
                    <td className="text-right">{it.received_qty}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2 justify-end">
              {detail.status === "requested" && hasRole("owner", "warehouse_manager", "store_manager") && (
                <button data-testid="transfer-approve" onClick={() => act(detail.id, "approve")} className="btn-outline">Approve</button>
              )}
              {(detail.status === "approved" || detail.status === "requested") && hasRole("owner", "warehouse_manager", "store_manager", "warehouse_staff") && (
                <button data-testid="transfer-dispatch" onClick={() => act(detail.id, "dispatch", {
                  items: detail.items.map((it) => ({ product_id: it.product_id, dispatched_qty: it.requested_qty })),
                })} className="btn-outline">Dispatch all</button>
              )}
              {detail.status === "dispatched" && hasRole("owner", "store_manager", "warehouse_manager", "warehouse_staff") && (
                <button data-testid="transfer-receive" onClick={() => act(detail.id, "receive", {
                  items: detail.items.map((it) => ({ product_id: it.product_id, received_qty: it.dispatched_qty })),
                })} className="btn-brand">Receive all</button>
              )}
              {!["received", "cancelled"].includes(detail.status) && hasRole("owner", "store_manager", "warehouse_manager") && (
                <button onClick={() => act(detail.id, "cancel")} className="btn-outline text-red-500">Cancel</button>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
