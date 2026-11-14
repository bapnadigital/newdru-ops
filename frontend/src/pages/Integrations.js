import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Plug, CreditCard, ShoppingBag, MessageSquare, Upload, Circle } from "lucide-react";

const MODE_CHIP = { disabled: "chip-slate", simulator: "chip-warn", csv_only: "chip-info", uat: "chip-info", live: "chip-ok", production: "chip-ok" };

export default function Integrations() {
  const [pl, setPL] = useState(null);
  const [fc, setFC] = useState(null);
  const [msg, setMsg] = useState(null);
  const [file, setFile] = useState(null);
  const [fcLoc, setFCLoc] = useState("AMAZON_FC");
  const [uploading, setUploading] = useState(false);
  const [syncing, setSyncing] = useState(false);

  const syncNow = async (what) => {
    setSyncing(true);
    try {
      if (what === "orders") {
        const { data } = await api.post("/fc-sync/orders/pull", null, { params: { since_minutes: 1440 } });
        toast.success(`Orders: ${data.new} new, ${data.updated} updated`);
      } else {
        const { data } = await api.post("/fc-sync/pull");
        const parts = Object.entries(data.locations || {}).map(([k, v]) => `${k}: ${v.changed} changed, ${v.unknown_count} unknown`);
        toast.success(`Stock synced · ${parts.join(" · ")}`);
      }
      load();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setSyncing(false);
  };

  const load = () => {
    api.get("/pinelabs/config").then(r => setPL(r.data)).catch(() => setPL({ mode: "error" }));
    api.get("/fc-sync/config").then(r => setFC(r.data)).catch(() => setFC({ mode: "error" }));
    api.get("/messaging/config").then(r => setMsg(r.data)).catch(() => setMsg({}));
  };
  useEffect(() => { load(); }, []);

  const uploadCsv = async () => {
    if (!file) return toast.error("Pick a CSV first");
    const fd = new FormData(); fd.append("location_code", fcLoc); fd.append("file", file);
    setUploading(true);
    try {
      const { data } = await api.post("/fc-sync/csv", fd, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success(`Synced ${data.updated} SKUs · ${data.unknown_count} unknown skipped`);
      setFile(null);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setUploading(false);
  };

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-brand text-slate-900">Integrations</h1>
        <p className="text-sm text-slate-500">Payment terminal, Unicommerce stock and order sync, and outbound messaging. Keys are stored as Cloudflare secrets, never in the app.</p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card icon={<CreditCard size={18} />} title="Pine Labs terminal" mode={pl?.mode}
              subtitle="Cloud API v1 (Plutus) — card + UPI on a physical terminal.">
          <PineLabsSettings pl={pl} reload={load} />
        </Card>

        <Card icon={<ShoppingBag size={18} />} title="Unicommerce" mode={fc?.mode}
              subtitle="Stock syncs automatically every 30 min, marketplace orders every hour. CSV upload still works.">
          {fc?.mode === "live" && (
            <div className="mt-3 space-y-2">
              <div className="text-xs text-slate-600">
                <Row k="Facilities" v={Object.entries(fc.facilities || {}).map(([k, v]) => `${k} ← ${v}`).join(", ") || "none mapped"} />
                <Row k="Login set" v={fc.tenant_set && fc.api_user_set && fc.password_set ? "yes" : "no"} />
                <Row k="Last run" v={fc.recent_runs?.[0] ? `${fc.recent_runs[0].kind} · ${fc.recent_runs[0].ok ? "OK" : "FAILED"} · ${new Date(fc.recent_runs[0].finished_at).toLocaleString()}` : "never"} />
                {fc.recent_runs?.[0] && !fc.recent_runs[0].ok && (
                  <div className="text-red-600 mt-1">{fc.recent_runs[0].result?.error}</div>
                )}
              </div>
              <div className="flex gap-2">
                <button data-testid="uc-sync-stock" onClick={() => syncNow("stock")} disabled={syncing} className="btn-brand disabled:opacity-50">Sync stock now</button>
                <button data-testid="uc-sync-orders" onClick={() => syncNow("orders")} disabled={syncing} className="border border-slate-300 rounded-md px-3 py-2 text-sm disabled:opacity-50">Sync orders (24h)</button>
              </div>
            </div>
          )}
          <div className="mt-2 flex flex-wrap gap-2 items-end">
            <select value={fcLoc} onChange={(e) => setFCLoc(e.target.value)} className="border border-slate-300 rounded-md px-3 py-2 text-sm">
              <option value="AMAZON_FC">Amazon FC</option>
              <option value="FLIPKART_FC">Flipkart FC</option>
            </select>
            <input data-testid="fc-csv-file" type="file" accept=".csv" onChange={(e) => setFile(e.target.files?.[0] || null)} className="text-sm" />
            <button data-testid="fc-csv-upload" onClick={uploadCsv} disabled={uploading || !file} className="btn-brand disabled:opacity-50 flex items-center gap-1"><Upload size={14} />Upload</button>
          </div>
          <div className="text-xs text-slate-500 mt-2">CSV format: <span className="font-mono">sku,quantity</span> — unknown SKUs are skipped and reported.</div>
        </Card>

        <Card icon={<MessageSquare size={18} />} title="Gupshup WhatsApp" mode={msg?.gupshup?.mode}
              subtitle="Send GST invoices & B2B payment reminders on WhatsApp.">
          <div className="text-xs text-slate-600 mt-2">
            <Row k="Configured" v={msg?.gupshup?.configured ? "yes" : "no — set GUPSHUP_API_KEY, GUPSHUP_SOURCE_NUMBER, GUPSHUP_APP_NAME"} />
          </div>
        </Card>

        <Card icon={<MessageSquare size={18} />} title="MSG91 SMS" mode={msg?.msg91?.mode}
              subtitle="Transactional SMS fallback for customers without WhatsApp.">
          <div className="text-xs text-slate-600 mt-2">
            <Row k="Configured" v={msg?.msg91?.configured ? "yes" : "no — set MSG91_AUTH_KEY (+ optional MSG91_SENDER_ID)"} />
          </div>
        </Card>
      </div>
    </div>
  );
}

function Card({ icon, title, subtitle, mode, children }) {
  const modeClass = MODE_CHIP[mode] || "chip-slate";
  return (
    <div className="card-surface p-5">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          <div className="h-9 w-9 rounded-md flex items-center justify-center" style={{ background: "#FDECEA", color: "#D84038" }}>{icon}</div>
          <div>
            <div className="font-semibold">{title}</div>
            <div className="text-xs text-slate-500">{subtitle}</div>
          </div>
        </div>
        <span className={`chip ${modeClass}`}><Circle size={8} /> {mode || "unknown"}</span>
      </div>
      {children}
    </div>
  );
}

function Row({ k, v }) { return <div className="flex justify-between"><span className="text-slate-500">{k}</span><span className="font-mono">{v}</span></div>; }

function PineLabsSettings({ pl, reload }) {
  const [s, setS] = useState(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState({
    merchant_id: "", security_token: "", store_id: "", terminal_id: "", user_id: "", mode: "simulator",
  });
  useEffect(() => {
    api.get("/pinelabs/settings").then((r) => {
      setS(r.data);
      setForm((f) => ({
        ...f,
        merchant_id: r.data.merchant_id || "",
        store_id: r.data.store_id || "",
        terminal_id: r.data.terminal_id || "",
        user_id: r.data.user_id || "",
        mode: r.data.mode || "simulator",
      }));
    }).catch(() => {});
  }, []);
  const save = async () => {
    setSaving(true);
    try {
      const patch = { ...form };
      // Only send security_token if the owner typed a new one
      if (!patch.security_token) delete patch.security_token;
      await api.post("/pinelabs/settings", patch);
      toast.success("Pine Labs settings saved");
      reload();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setSaving(false);
  };
  return (
    <div className="mt-3 space-y-2">
      <div className="grid grid-cols-2 gap-2 text-xs">
        <label className="flex flex-col gap-1"><span className="text-slate-500">Merchant ID</span>
          <input data-testid="pl-merchant" value={form.merchant_id} onChange={(e) => setForm({ ...form, merchant_id: e.target.value })}
                 className="px-2 py-1.5 border border-slate-300 rounded font-mono" /></label>
        <label className="flex flex-col gap-1"><span className="text-slate-500">Store ID</span>
          <input data-testid="pl-store" value={form.store_id} onChange={(e) => setForm({ ...form, store_id: e.target.value })}
                 className="px-2 py-1.5 border border-slate-300 rounded font-mono" /></label>
        <label className="flex flex-col gap-1"><span className="text-slate-500">Terminal / Client ID</span>
          <input data-testid="pl-terminal" value={form.terminal_id} onChange={(e) => setForm({ ...form, terminal_id: e.target.value })}
                 className="px-2 py-1.5 border border-slate-300 rounded font-mono" /></label>
        <label className="flex flex-col gap-1"><span className="text-slate-500">User ID</span>
          <input data-testid="pl-user" value={form.user_id} onChange={(e) => setForm({ ...form, user_id: e.target.value })}
                 className="px-2 py-1.5 border border-slate-300 rounded font-mono" /></label>
        <label className="flex flex-col gap-1 col-span-2"><span className="text-slate-500">Security token {s?.security_token_masked && <em className="text-slate-400 not-italic">(current: {s.security_token_masked})</em>}</span>
          <input data-testid="pl-token" type="password" placeholder={s?.security_token_masked ? "Leave blank to keep current" : "Paste token…"} value={form.security_token} onChange={(e) => setForm({ ...form, security_token: e.target.value })}
                 className="px-2 py-1.5 border border-slate-300 rounded font-mono" /></label>
        <label className="flex flex-col gap-1 col-span-2"><span className="text-slate-500">Mode</span>
          <select data-testid="pl-mode" value={form.mode} onChange={(e) => setForm({ ...form, mode: e.target.value })}
                  className="px-2 py-1.5 border border-slate-300 rounded font-mono">
            <option value="simulator">simulator (test flow — auto-APPROVED)</option>
            <option value="uat">uat (Pine Labs test terminal)</option>
            <option value="production">production (real terminal)</option>
          </select></label>
      </div>
      <div className="flex justify-between items-center pt-2">
        <div className="text-xs text-slate-500">{pl?.note}</div>
        <button data-testid="pl-save" onClick={save} disabled={saving} className="btn-brand text-sm disabled:opacity-50">
          {saving ? "Saving…" : "Save Pine Labs settings"}
        </button>
      </div>
    </div>
  );
}
