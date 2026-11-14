/* Admin: warranty settings (default 6 months, per-SKU override) + Shopify sync card. */
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import { Settings2, ShoppingBag, Loader2 } from "lucide-react";

export default function WarrantySettings() {
  const [products, setProducts] = useState([]);
  const [q, setQ] = useState("");
  const [saving, setSaving] = useState(null);

  const [shopify, setShopify] = useState(null);
  const [shopSaving, setShopSaving] = useState(false);
  const [shopForm, setShopForm] = useState({ shop_domain: "", access_token: "", location_id: "", mode: "disabled" });
  const [syncBusy, setSyncBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/warranty/settings");
      setProducts(data.products);
    } catch (err) { console.error("warranty settings load:", err); toast.error("Load failed"); }
    try {
      const { data } = await api.get("/shopify/config");
      setShopify(data);
      setShopForm((f) => ({ ...f, shop_domain: data.shop_domain || "", mode: data.mode || "disabled" }));
    } catch (err) { /* owner-only endpoint — non-owners intentionally get 403 */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const saveMonths = async (sku, months) => {
    setSaving(sku);
    try {
      await api.post("/warranty/settings/product", { sku, warranty_months: Number(months) });
      toast.success(`${sku} → ${months} months`);
    } catch (e) { toast.error(e.response?.data?.detail || "Save failed"); }
    finally { setSaving(null); }
  };

  const saveShopify = async () => {
    setShopSaving(true);
    try {
      const patch = { ...shopForm };
      // don't send access_token if unchanged (empty)
      if (!patch.access_token) delete patch.access_token;
      const { data } = await api.post("/shopify/settings", patch);
      setShopify(data);
      toast.success("Shopify settings saved");
    } catch (e) { toast.error(e.response?.data?.detail || "Save failed"); }
    finally { setShopSaving(false); }
  };

  const runOrderSync = async () => {
    setSyncBusy(true);
    try {
      const { data } = await api.post("/shopify/sync/orders", null, { params: { since_hours: 24, limit: 50 } });
      if (data.ok) toast.success(`Pulled ${data.orders} orders · matched ${data.matched_line_items}, unknown ${data.unknown_skus}`);
      else toast.error(`Sync failed: ${data.reason}`);
    } catch (e) { toast.error(e.response?.data?.detail || "Sync failed"); }
    finally { setSyncBusy(false); }
  };

  const runInvSync = async () => {
    setSyncBusy(true);
    try {
      const { data } = await api.post("/shopify/sync/inventory");
      toast.success(`Pushed ${data.pushed} SKUs · ${data.failed} failed`);
    } catch (e) { toast.error(e.response?.data?.detail || "Push failed"); }
    finally { setSyncBusy(false); }
  };

  const filtered = products.filter((p) =>
    !q || p.sku.toLowerCase().includes(q.toLowerCase()) || p.name.toLowerCase().includes(q.toLowerCase())
  );

  return (
    <div className="p-6 space-y-8" data-testid="warranty-settings-page">
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
          <Settings2 size={22} style={{ color: "#F0544A" }} />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Warranty & Shopify Settings</h1>
          <div className="text-sm text-slate-500">Default warranty: 6 months manufacturing defect. Override per SKU if needed.</div>
        </div>
      </div>

      {/* Shopify card */}
      <section className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <ShoppingBag size={20} className="text-slate-600" />
            <h2 className="text-lg font-semibold">Shopify Sync</h2>
            {shopify && (
              <span className="ml-2 px-2 py-0.5 rounded text-xs font-semibold uppercase" style={{
                background: shopify.ready ? "#DCFCE7" : "#FEF3C7",
                color: shopify.ready ? "#16A34A" : "#B45309",
              }} data-testid="shopify-status-badge">
                {shopify.mode} {shopify.ready ? "· ready" : "· not configured"}
              </span>
            )}
          </div>
          <div className="flex gap-2">
            <button onClick={runOrderSync} disabled={syncBusy || !shopify?.ready} data-testid="shopify-sync-orders-btn"
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 hover:bg-slate-50 disabled:opacity-40 inline-flex items-center gap-1.5">
              {syncBusy && <Loader2 size={12} className="animate-spin" />} Pull orders (24h)
            </button>
            <button onClick={runInvSync} disabled={syncBusy || shopify?.mode !== "full"} data-testid="shopify-sync-inv-btn"
                    className="px-3 py-1.5 rounded-lg text-xs font-semibold text-white disabled:opacity-40 inline-flex items-center gap-1.5"
                    style={{ background: "#F0544A" }}>
              {syncBusy && <Loader2 size={12} className="animate-spin" />} Push store inventory
            </button>
          </div>
        </div>

        <div className="grid md:grid-cols-2 gap-4">
          <label className="block">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Shop domain</div>
            <input data-testid="shopify-shop-domain" value={shopForm.shop_domain}
                   onChange={(e) => setShopForm({ ...shopForm, shop_domain: e.target.value })}
                   placeholder="newdru.myshopify.com"
                   className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
          </label>
          <label className="block">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Location ID (for inventory push)</div>
            <input data-testid="shopify-location-id" value={shopForm.location_id}
                   onChange={(e) => setShopForm({ ...shopForm, location_id: e.target.value })}
                   placeholder="e.g. 12345678901"
                   className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm" />
          </label>
          <label className="block md:col-span-2">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">
              Admin API access token {shopify?.access_token_set && <span className="text-emerald-600">· saved</span>}
            </div>
            <input data-testid="shopify-access-token" type="password" value={shopForm.access_token}
                   onChange={(e) => setShopForm({ ...shopForm, access_token: e.target.value })}
                   placeholder={shopify?.access_token_set ? "•••• (leave blank to keep)" : "shpat_…"}
                   className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm font-mono" />
          </label>
          <label className="block">
            <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">Mode</div>
            <select data-testid="shopify-mode" value={shopForm.mode}
                    onChange={(e) => setShopForm({ ...shopForm, mode: e.target.value })}
                    className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm">
              <option value="disabled">Disabled</option>
              <option value="pull_only">Pull only (orders → activity feed)</option>
              <option value="full">Full (also push inventory)</option>
            </select>
          </label>
          <div className="flex items-end">
            <button onClick={saveShopify} disabled={shopSaving} data-testid="shopify-save-btn"
                    className="px-5 py-2 rounded-lg font-semibold text-white disabled:opacity-40 inline-flex items-center gap-2"
                    style={{ background: "#F0544A" }}>
              {shopSaving && <Loader2 size={14} className="animate-spin" />} Save Shopify settings
            </button>
          </div>
        </div>

        <details className="mt-4 text-sm text-slate-600">
          <summary className="cursor-pointer font-semibold">How to get the Shopify Admin API token</summary>
          <ol className="list-decimal ml-5 mt-2 space-y-1">
            <li>In Shopify admin → <b>Settings → Apps and sales channels → Develop apps → Create an app</b>.</li>
            <li>Name it <b>Newdru Sync</b> → <b>Configure Admin API scopes</b>.</li>
            <li>Enable: <code>read_orders</code>, <code>read_products</code>, <code>read_inventory</code>, <code>write_inventory</code>, <code>read_customers</code>.</li>
            <li>Click <b>Install app</b> → copy the <b>Admin API access token</b> (starts with <code>shpat_</code>) → paste above.</li>
            <li>For location ID: <b>Settings → Locations</b> → open your primary location → the numeric ID is at the end of the URL.</li>
            <li>Set Mode → <b>Pull only</b> first to verify orders arrive; then flip to <b>Full</b> to push inventory.</li>
          </ol>
        </details>
      </section>

      {/* Warranty per-SKU */}
      <section className="bg-white border rounded-2xl p-6 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">Per-SKU warranty override</h2>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search SKU or name…"
                 className="px-3 py-2 rounded-lg border border-slate-300 text-sm w-64" data-testid="warranty-sku-search" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
              <tr>
                <th className="text-left p-3">SKU</th>
                <th className="text-left p-3">Product</th>
                <th className="text-left p-3">Warranty (months)</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((p) => (
                <tr key={p.sku} className="border-t border-slate-100">
                  <td className="p-3 font-mono text-xs">{p.sku}</td>
                  <td className="p-3">{p.name}</td>
                  <td className="p-3">
                    <div className="inline-flex items-center gap-2">
                      <input type="number" min={0} max={60} defaultValue={p.warranty_months ?? 6}
                             data-testid={`warranty-months-${p.sku}`}
                             onBlur={(e) => {
                               const v = Number(e.target.value);
                               if (v !== (p.warranty_months ?? 6)) saveMonths(p.sku, v);
                             }}
                             className="w-20 border border-slate-300 rounded px-2 py-1 text-sm" />
                      {saving === p.sku && <Loader2 size={14} className="animate-spin text-slate-400" />}
                    </div>
                  </td>
                </tr>
              ))}
              {filtered.length === 0 && <tr><td colSpan={3} className="p-6 text-center text-slate-400">No SKUs match.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
