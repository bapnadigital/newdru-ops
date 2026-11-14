import { useEffect, useRef, useState } from "react";
import api, { fmtINR, LOCATION_LABEL } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { ScanBarcode, PackagePlus, Trash2 } from "lucide-react";

export default function GoodsReceipt() {
  const { hasRole } = useAuth();
  const defaultLoc = hasRole("store_manager") ? "STORE" : "BHIWANDI";
  const [location, setLocation] = useState(defaultLoc);
  const [reference, setReference] = useState("");
  const [notes, setNotes] = useState("");
  const [scanInput, setScanInput] = useState("");
  const [lines, setLines] = useState([]); // {barcode, sku, name, cartons, units, units_per_carton}
  const [submitting, setSubmitting] = useState(false);
  const scanRef = useRef(null);

  useEffect(() => { scanRef.current?.focus(); }, []);

  const handleScan = async () => {
    const code = scanInput.trim();
    if (!code) return;
    setScanInput("");
    try {
      const { data } = await api.get(`/products/lookup?code=${encodeURIComponent(code)}`);
      setLines((ls) => {
        const idx = ls.findIndex((l) => l.product_id === data.id);
        if (idx >= 0) {
          const next = [...ls];
          next[idx] = { ...next[idx], units: (Number(next[idx].units) || 0) + 1 };
          return next;
        }
        return [...ls, {
          product_id: data.id, sku: data.sku, name: data.name, barcode: data.barcode,
          units_per_carton: data.units_per_carton || 1, cartons: 0, units: 1,
        }];
      });
    } catch {
      if (window.confirm(`Barcode "${code}" not found. Open Products to create it?`)) {
        window.location.href = "/products";
      }
    }
    scanRef.current?.focus();
  };

  const removeLine = (id) => setLines((ls) => ls.filter((l) => l.product_id !== id));
  const updateLine = (id, patch) => setLines((ls) => ls.map((l) => l.product_id === id ? { ...l, ...patch } : l));

  const totalUnits = lines.reduce((s, l) => s + (Number(l.cartons || 0) * Number(l.units_per_carton || 1) + Number(l.units || 0)), 0);

  const submit = async () => {
    if (lines.length === 0) return;
    setSubmitting(true);
    try {
      const payload = {
        location_code: location, reference, notes,
        lines: lines.map((l) => ({
          product_id: l.product_id,
          cartons: Number(l.cartons || 0),
          units: Number(l.units || 0),
        })),
      };
      const { data } = await api.post("/inventory/receive", payload);
      alert(`Received ${data.received.length} line(s).`);
      setLines([]); setReference(""); setNotes("");
    } catch (e) {
      alert(e.response?.data?.detail || e.message);
    } finally { setSubmitting(false); }
  };

  return (
    <div className="space-y-5" data-testid="receive-page">
      <div>
        <h1 className="text-3xl font-brand text-slate-900">Goods Receipt</h1>
        <p className="text-sm text-slate-500 mt-1">Scan barcodes or enter SKUs. Carton × units-per-carton auto-calculates the total.</p>
      </div>

      <div className="card-surface p-4 grid grid-cols-1 md:grid-cols-3 gap-4">
        <label className="block"><span className="text-xs font-semibold uppercase text-slate-600">Receive into</span>
          <select data-testid="receive-location" value={location} onChange={(e) => setLocation(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm bg-white">
            {hasRole("owner", "store_manager", "warehouse_manager", "warehouse_staff") && <option value="STORE">Newdru Store</option>}
            {hasRole("owner", "warehouse_manager", "warehouse_staff") && <option value="BHIWANDI">Bhiwandi Warehouse</option>}
          </select></label>
        <label className="block"><span className="text-xs font-semibold uppercase text-slate-600">Reference / PO#</span>
          <input value={reference} onChange={(e) => setReference(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm" placeholder="Optional" /></label>
        <label className="block"><span className="text-xs font-semibold uppercase text-slate-600">Notes</span>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} className="w-full mt-1 border border-slate-300 rounded px-3 py-2 text-sm" placeholder="Optional" /></label>
      </div>

      <div className="card-surface p-4">
        <div className="flex items-center gap-2">
          <ScanBarcode size={18} className="text-[#F0544A]" />
          <input
            ref={scanRef}
            data-testid="receive-scan-input"
            value={scanInput}
            onChange={(e) => setScanInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleScan()}
            placeholder="Scan or type barcode / SKU, then Enter"
            className="flex-1 border border-slate-300 rounded-lg px-3 py-2.5 text-sm font-mono"
            autoFocus
          />
          <button data-testid="receive-scan-add" onClick={handleScan} className="btn-brand"><PackagePlus size={16} /></button>
        </div>
      </div>

      <div className="card-surface overflow-hidden">
        <table className="data-table w-full">
          <thead>
            <tr>
              <th>Product</th><th>Barcode</th>
              <th className="text-right">Cartons</th>
              <th className="text-right">×</th>
              <th className="text-right">Extra Units</th>
              <th className="text-right">= Total</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {lines.length === 0 && <tr><td colSpan="7" className="text-center py-8 text-slate-500">Scan a product to begin.</td></tr>}
            {lines.map((l) => {
              const total = Number(l.cartons || 0) * Number(l.units_per_carton || 1) + Number(l.units || 0);
              return (
                <tr key={l.product_id}>
                  <td>
                    <div className="font-medium">{l.name}</div>
                    <div className="text-xs text-slate-500 font-mono">{l.sku}</div>
                  </td>
                  <td className="font-mono text-xs">{l.barcode}</td>
                  <td className="text-right">
                    <input data-testid={`receive-cartons-${l.sku}`} type="number" value={l.cartons} onChange={(e) => updateLine(l.product_id, { cartons: e.target.value })} className="w-20 border border-slate-300 rounded px-2 py-1 text-sm text-right" />
                  </td>
                  <td className="text-right text-xs text-slate-500">{l.units_per_carton}</td>
                  <td className="text-right">
                    <input data-testid={`receive-units-${l.sku}`} type="number" value={l.units} onChange={(e) => updateLine(l.product_id, { units: e.target.value })} className="w-20 border border-slate-300 rounded px-2 py-1 text-sm text-right" />
                  </td>
                  <td className="text-right font-semibold">{total}</td>
                  <td><button onClick={() => removeLine(l.product_id)} className="p-1.5 rounded hover:bg-red-50 text-red-500"><Trash2 size={14} /></button></td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between">
        <div className="text-sm text-slate-600">Total units: <span className="font-bold text-slate-900">{totalUnits}</span> into <span className="font-semibold">{LOCATION_LABEL[location]}</span></div>
        <button data-testid="receive-submit" onClick={submit} disabled={submitting || lines.length === 0} className="btn-brand">
          {submitting ? "Receiving…" : `Confirm receipt (${lines.length})`}
        </button>
      </div>
    </div>
  );
}
