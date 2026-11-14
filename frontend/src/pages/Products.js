import { useEffect, useState } from "react";
import { api, inr, canSeeCost, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import PricingCalculator from "@/components/PricingCalculator";
import BarcodeDisplay from "@/components/BarcodeDisplay";
import { toast } from "sonner";
import { Plus, Search, Upload, Download, Printer, X, Edit3 } from "lucide-react";

const emptyProduct = {
  sku: "", name: "", brand: "", category: "", variant: "",
  mrp: 0, gst_rate: 18, hsn: "", channel_scope: "offline_only",
  status: "active", barcode: "", barcode_type: "CODE128",
  buy_price: 0, sell_price: 0,
  unit_weight_g: 0, units_per_carton: 1,
  dimensions: { length_cm: 0, width_cm: 0, height_cm: 0 },
};

export default function Products() {
  const { user } = useAuth();
  const [items, setItems] = useState([]);
  const [q, setQ] = useState("");
  const [placeholderOnly, setPlaceholderOnly] = useState(false);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(null);
  const canWrite = ["owner", "admin", "store_manager", "warehouse_manager"].includes(user.role);
  const showCost = canSeeCost(user.role);

  const load = async () => {
    setLoading(true);
    try {
      const params = { q };
      if (placeholderOnly) params.placeholder_pricing = true;
      const { data } = await api.get("/products", { params });
      setItems(data);
    }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [placeholderOnly]);

  const placeholderCount = items.filter((p) => p.placeholder_pricing).length;

  const openNew = () => setEditing({ ...emptyProduct });
  const openEdit = (p) => setEditing(JSON.parse(JSON.stringify(p)));

  const downloadCsv = async () => {
    try {
      const res = await api.get("/products/export/csv", { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a"); a.href = url; a.download = "products.csv"; a.click();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const importCsv = async (file) => {
    const fd = new FormData(); fd.append("file", file);
    try {
      const { data } = await api.post("/products/import-csv", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Import: ${data.created} new, ${data.updated} updated${data.errors?.length ? `, ${data.errors.length} errors` : ""}`);
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const printLabels = async (product_id) => {
    try {
      const res = await api.post("/labels/pdf", { items: [{ product_id, count: 1 }] }, { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data], { type: "application/pdf" }));
      window.open(url, "_blank");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-center md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Product Master</h1>
          <p className="text-slate-500 text-sm">SKU-keyed catalog with GST pricing & packaging.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
            <input data-testid="product-search" placeholder="Search SKU / name / barcode…"
                   value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && load()}
                   className="pl-8 pr-3 py-2 text-sm border border-slate-300 rounded-md w-full md:w-72" />
          </div>
          <button data-testid="products-export" onClick={downloadCsv} className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50 flex items-center gap-1"><Download size={14} />CSV</button>
          <button
            data-testid="filter-placeholder-pricing"
            onClick={() => setPlaceholderOnly((v) => !v)}
            title="Show only SKUs with placeholder (₹0) pricing"
            className={`px-3 py-2 text-sm rounded-md flex items-center gap-1 border transition ${
              placeholderOnly
                ? "bg-amber-500 text-white border-amber-500"
                : "bg-white border-slate-300 hover:bg-amber-50"
            }`}
          >
            <span className={placeholderOnly ? "" : "text-amber-500"}>●</span>
            Placeholder pricing
            {!placeholderOnly && placeholderCount > 0 && (
              <span className="ml-1 text-[11px] bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded-full">
                {placeholderCount}
              </span>
            )}
          </button>
          {canWrite && (
            <>
              <label className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50 flex items-center gap-1 cursor-pointer">
                <Upload size={14} />Import
                <input data-testid="products-import" type="file" accept=".csv" onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} className="hidden" />
              </label>
              <button data-testid="product-new-btn" onClick={openNew}
                      className="bg-[hsl(234_61%_25%)] text-white px-3 py-2 rounded-md text-sm flex items-center gap-1"><Plus size={14} />New product</button>
            </>
          )}
        </div>
      </div>

      <div className="bg-white border border-slate-200 rounded-md overflow-hidden">
        <div className="overflow-x-auto scroll-thin">
          <table className="newdru-table">
            <thead>
              <tr>
                <th>SKU</th><th>Name</th><th>Brand</th><th>Category</th><th>Barcode</th>
                <th>MRP</th>
                {showCost && <th>Sell</th>}
                {showCost && <th>Margin</th>}
                <th>Channel</th><th>Status</th><th></th>
              </tr>
            </thead>
            <tbody>
              {items.map((p) => (
                <tr key={p.id} className={p.placeholder_pricing ? "bg-amber-50/60" : ""}>
                  <td className="mono">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span>{p.sku}</span>
                      {p.placeholder_pricing && (
                        <span
                          data-testid={`placeholder-badge-${p.sku}`}
                          className="text-[10px] font-semibold uppercase tracking-wide bg-amber-100 text-amber-800 border border-amber-200 px-1.5 py-0.5 rounded"
                          title="Placeholder pricing — set MRP / buy / sell before selling"
                        >
                          Placeholder
                        </span>
                      )}
                      {p.cogs_per_unit > 0 && p.sell_price > 0 && p.sell_price < p.cogs_per_unit && (
                        <span
                          data-testid={`below-cogs-badge-${p.sku}`}
                          className="text-[10px] font-semibold uppercase tracking-wide bg-rose-100 text-rose-800 border border-rose-200 px-1.5 py-0.5 rounded"
                          title={`Sell price ₹${p.sell_price} is BELOW COGS ₹${p.cogs_per_unit} — every store sale needs admin override`}
                        >
                          Below COGS
                        </span>
                      )}
                    </div>
                  </td>
                  <td>{p.name}</td>
                  <td>{p.brand}</td>
                  <td>{p.category}</td>
                  <td className="mono">
                    <div className="flex items-center gap-2">
                      <span>{p.barcode}</span>
                      <span className="chip chip-slate">{p.barcode_type}</span>
                    </div>
                  </td>
                  <td className="mono">{inr(p.mrp)}</td>
                  {showCost && <td className="mono">{inr(p.sell_price)}</td>}
                  {showCost && <td className="mono">{p.pricing?.gst_margin_pct?.toFixed(1)}%</td>}
                  <td><span className="chip chip-info">{p.channel_scope === "online_offline" ? "Online + Offline" : "Offline only"}</span></td>
                  <td><span className={`chip ${p.status === "active" ? "chip-ok" : "chip-slate"}`}>{p.status}</span></td>
                  <td>
                    <div className="flex gap-1">
                      <button title="Print label" onClick={() => printLabels(p.id)} className="p-1.5 hover:bg-slate-100 rounded"><Printer size={14} /></button>
                      {canWrite && (
                        <button data-testid={`edit-product-${p.sku}`} title="Edit" onClick={() => openEdit(p)} className="p-1.5 hover:bg-slate-100 rounded"><Edit3 size={14} /></button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {loading && <div className="p-4 text-sm text-slate-500">Loading…</div>}
        {!loading && items.length === 0 && (
          <div className="p-8 text-center text-slate-500">
            No products. {canWrite && <button className="text-indigo-700 underline" onClick={openNew}>Create your first product</button>}
          </div>
        )}
      </div>

      {editing && (
        <ProductModal product={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} showCost={showCost} />
      )}
    </div>
  );
}

function ProductModal({ product, onClose, onSaved, showCost }) {
  const [p, setP] = useState(product);
  const [saving, setSaving] = useState(false);
  const isEdit = !!p.id;

  const save = async () => {
    setSaving(true);
    try {
      if (isEdit) { await api.patch(`/products/${p.id}`, p); toast.success("Updated"); }
      else { await api.post("/products", p); toast.success("Product created"); }
      onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setSaving(false);
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-md w-full max-w-3xl max-h-[92vh] overflow-y-auto scroll-thin shadow-xl">
        <div className="flex items-center justify-between px-5 py-3 border-b sticky top-0 bg-white">
          <h3 className="font-semibold text-lg">{isEdit ? "Edit product" : "New product"}</h3>
          <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded" data-testid="modal-close"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="SKU *"><input data-testid="prod-sku" value={p.sku} onChange={(e) => setP({ ...p, sku: e.target.value })} className="input" disabled={isEdit} /></Field>
            <Field label="Barcode (FNSKU / auto Code128)"><input data-testid="prod-barcode" value={p.barcode || ""} onChange={(e) => setP({ ...p, barcode: e.target.value })} className="input" placeholder="leave blank for offline-only auto-gen" /></Field>
            <Field label="Barcode Type">
              <select value={p.barcode_type} onChange={(e) => setP({ ...p, barcode_type: e.target.value })} className="input">
                <option value="FNSKU">FNSKU (Amazon)</option>
                <option value="CODE128">Code128 (internal)</option>
              </select>
            </Field>
            <Field label="Name *"><input data-testid="prod-name" value={p.name} onChange={(e) => setP({ ...p, name: e.target.value })} className="input" /></Field>
            <Field label="Brand"><input value={p.brand || ""} onChange={(e) => setP({ ...p, brand: e.target.value })} className="input" /></Field>
            <Field label="Category"><input value={p.category || ""} onChange={(e) => setP({ ...p, category: e.target.value })} className="input" /></Field>
            <Field label="Variant"><input value={p.variant || ""} onChange={(e) => setP({ ...p, variant: e.target.value })} className="input" /></Field>
            <Field label="MRP ₹"><input type="number" step="0.01" value={p.mrp} onChange={(e) => setP({ ...p, mrp: parseFloat(e.target.value || 0) })} className="input" /></Field>
            <Field label="HSN Code"><input value={p.hsn || ""} onChange={(e) => setP({ ...p, hsn: e.target.value })} className="input" /></Field>
            <Field label="Channel">
              <select value={p.channel_scope} onChange={(e) => setP({ ...p, channel_scope: e.target.value })} className="input">
                <option value="offline_only">Offline only</option>
                <option value="online_offline">Online + Offline</option>
              </select>
            </Field>
            <Field label="Status">
              <select value={p.status} onChange={(e) => setP({ ...p, status: e.target.value })} className="input">
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </Field>
          </div>

          {showCost && (
            <PricingCalculator
              buyIncl={p.buy_price || 0}
              gstRate={p.gst_rate ?? 18}
              sellPrice={p.sell_price || 0}
              onChange={(patch) => {
                const next = { ...p };
                if (patch.buy_price_incl_gst !== undefined) next.buy_price = patch.buy_price_incl_gst;
                if (patch.gst_rate !== undefined) next.gst_rate = patch.gst_rate;
                if (patch.sell_price !== undefined) next.sell_price = patch.sell_price;
                setP(next);
              }}
            />
          )}

          <div className="bg-slate-50 border border-slate-200 rounded-md p-4">
            <div className="text-xs uppercase tracking-widest text-slate-600 font-semibold mb-3">Packaging</div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
              <Field label="Unit Weight (g)"><input type="number" value={p.unit_weight_g || ""} onChange={(e) => setP({ ...p, unit_weight_g: parseFloat(e.target.value || 0) })} className="input" /></Field>
              <Field label="Length (cm)"><input type="number" value={p.dimensions?.length_cm || ""} onChange={(e) => setP({ ...p, dimensions: { ...(p.dimensions || {}), length_cm: parseFloat(e.target.value || 0) } })} className="input" /></Field>
              <Field label="Width (cm)"><input type="number" value={p.dimensions?.width_cm || ""} onChange={(e) => setP({ ...p, dimensions: { ...(p.dimensions || {}), width_cm: parseFloat(e.target.value || 0) } })} className="input" /></Field>
              <Field label="Height (cm)"><input type="number" value={p.dimensions?.height_cm || ""} onChange={(e) => setP({ ...p, dimensions: { ...(p.dimensions || {}), height_cm: parseFloat(e.target.value || 0) } })} className="input" /></Field>
              <Field label="Units / Carton"><input type="number" value={p.units_per_carton || 1} onChange={(e) => setP({ ...p, units_per_carton: parseInt(e.target.value || 1) })} className="input" /></Field>
            </div>
          </div>

          {p.barcode && (
            <div className="bg-white border border-slate-200 rounded-md p-4 flex items-center gap-4">
              <div className="text-sm text-slate-600">Barcode preview:</div>
              <BarcodeDisplay value={p.barcode} height={38} />
            </div>
          )}
        </div>
        <div className="border-t px-5 py-3 flex justify-end gap-2 sticky bottom-0 bg-white">
          <button onClick={onClose} className="px-4 py-2 rounded-md border border-slate-300 text-sm">Cancel</button>
          <button data-testid="prod-save" onClick={save} disabled={saving || !p.sku || !p.name}
                  className="px-4 py-2 rounded-md bg-[hsl(234_61%_25%)] text-white text-sm disabled:opacity-60">
            {saving ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
      <style>{`.input { width:100%; border:1px solid #cbd5e1; border-radius: 6px; padding: 8px 10px; font-size: 14px; }`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-xs text-slate-600 mb-1 font-medium">{label}</div>
      {children}
    </label>
  );
}
