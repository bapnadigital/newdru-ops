import { useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Download, Search, X, Upload, ChevronLeft, ChevronRight, MessageSquare, Mail, Smartphone } from "lucide-react";

const PAGE = 50;

export default function Customers() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [consent, setConsent] = useState("");
  const [skip, setSkip] = useState(0);
  const [selected, setSelected] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importResult, setImportResult] = useState(null);

  const load = async () => {
    try {
      const { data } = await api.get("/customers", {
        params: {
          q: q || undefined,
          tag: tag || undefined,
          consent: consent || undefined,
          skip, limit: PAGE,
        },
      });
      setRows(data.rows || []);
      setTotal(data.total || 0);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [tag, consent, skip]);

  const doSearch = () => { setSkip(0); load(); };

  const importCsv = async (file) => {
    if (!file) return;
    setImporting(true); setImportResult(null);
    const fd = new FormData(); fd.append("file", file);
    try {
      const { data } = await api.post("/customers/import-csv", fd, {
        headers: { "Content-Type": "multipart/form-data" },
        timeout: 600000,
      });
      setImportResult(data);
      toast.success(`Import complete: ${data.created} created, ${data.updated} updated`);
      load();
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
    setImporting(false);
  };

  const open = async (c) => {
    try { const { data } = await api.get(`/customers/${c.id}`); setSelected(data); }
    catch (err) { console.error("customer detail failed:", err); toast.error("Could not load customer"); }
  };

  const download = async () => {
    try {
      const res = await api.get("/customers/export/csv", { responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a"); a.href = url; a.download = "customers.csv"; a.click();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3 mb-6">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500">Customer Relationship</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Customers (CRM)</h1>
          <p className="text-slate-500 text-sm mt-1">
            Auto-captured on every POS sale, and bulk-loadable from Shopify. Consent flags control who we can message.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-2.5 text-slate-400" />
            <input value={q} onChange={(e) => setQ(e.target.value)}
                   onKeyDown={(e) => e.key === "Enter" && doSearch()}
                   placeholder="Search name / phone / email…"
                   data-testid="customers-search"
                   className="pl-8 pr-3 py-2 text-sm border border-slate-300 rounded-md w-full md:w-64" />
          </div>
          <select data-testid="customers-consent" value={consent} onChange={(e) => { setSkip(0); setConsent(e.target.value); }}
                  className="px-2 py-2 border border-slate-300 rounded-md text-sm">
            <option value="">Any consent</option>
            <option value="email">Email opt-in</option>
            <option value="sms">SMS opt-in</option>
            <option value="whatsapp">WhatsApp opt-in</option>
          </select>
          <input data-testid="customers-tag" value={tag} onChange={(e) => setTag(e.target.value)}
                 onKeyDown={(e) => e.key === "Enter" && (setSkip(0), load())}
                 placeholder="Tag…"
                 className="px-3 py-2 text-sm border border-slate-300 rounded-md w-32" />
          <label className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50 flex items-center gap-1 cursor-pointer">
            <Upload size={14} />{importing ? "Uploading…" : "Import CSV"}
            <input data-testid="customers-import" type="file" accept=".csv" className="hidden"
                   disabled={importing}
                   onChange={(e) => e.target.files?.[0] && importCsv(e.target.files[0])} />
          </label>
          <button onClick={download} className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50 flex items-center gap-1">
            <Download size={14} />Export
          </button>
        </div>
      </div>

      {importResult && (
        <div data-testid="import-summary" className="mb-4 bg-emerald-50 border border-emerald-200 rounded-md p-3 text-sm text-emerald-900">
          <b>Import complete.</b> Created: {importResult.created} · Updated: {importResult.updated} ·
          Skipped: {importResult.skipped} · Errors: {importResult.errors?.length || 0} ·
          Total in CRM now: {importResult.total_after}
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl shadow-sm overflow-hidden">
        <table className="newdru-table">
          <thead>
            <tr>
              <th>Name</th><th>Phone</th><th>Email</th>
              <th className="text-right">Orders</th><th className="text-right">Spend</th>
              <th>Consent</th><th>Tags</th><th>Channel</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.id} className="cursor-pointer hover:bg-slate-50" onClick={() => open(c)}>
                <td className="font-medium">{c.name}</td>
                <td className="mono text-xs">{c.phone || "—"}</td>
                <td className="text-xs">{c.email || "—"}</td>
                <td className="text-right mono">{c.order_count || 0}</td>
                <td className="text-right mono font-semibold">{inr(c.total_spend || 0)}</td>
                <td className="text-xs">
                  <div className="flex gap-1">
                    {c.consent_email && <span title="Email opt-in" className="chip chip-ok"><Mail size={10} />E</span>}
                    {c.consent_sms && <span title="SMS opt-in" className="chip chip-info"><Smartphone size={10} />S</span>}
                    {c.consent_whatsapp && <span title="WhatsApp opt-in" className="chip chip-ok"><MessageSquare size={10} />W</span>}
                    {!c.consent_email && !c.consent_sms && !c.consent_whatsapp && <span className="text-slate-400">—</span>}
                  </div>
                </td>
                <td className="text-xs text-slate-500">{(c.tags || []).slice(0, 3).join(", ")}{(c.tags || []).length > 3 ? "…" : ""}</td>
                <td className="text-xs">{c.channel || "store"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-400">No customers match.</td></tr>}
          </tbody>
        </table>

        {total > 0 && (
          <div className="flex items-center justify-between px-4 py-2 text-xs text-slate-600 border-t border-slate-100">
            <span data-testid="customers-total">
              Showing {skip + 1}–{Math.min(skip + PAGE, total)} of {total.toLocaleString()}
            </span>
            <div className="flex gap-1">
              <button data-testid="customers-prev" onClick={() => setSkip(Math.max(0, skip - PAGE))} disabled={skip === 0}
                      className="p-1.5 rounded border border-slate-300 hover:bg-slate-50 disabled:opacity-40"><ChevronLeft size={14} /></button>
              <button data-testid="customers-next" onClick={() => setSkip(skip + PAGE)} disabled={skip + PAGE >= total}
                      className="p-1.5 rounded border border-slate-300 hover:bg-slate-50 disabled:opacity-40"><ChevronRight size={14} /></button>
            </div>
          </div>
        )}
      </div>

      {selected && <CustomerDrawer data={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}

function CustomerDrawer({ data, onClose }) {
  const c = data.customer;
  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex justify-end">
      <div className="bg-white w-full max-w-lg h-full overflow-y-auto scroll-thin">
        <div className="px-5 py-3 border-b flex justify-between items-center">
          <div>
            <h3 className="font-semibold text-lg">{c.name}</h3>
            <div className="text-xs text-slate-500">{c.phone || "—"} · {c.email || "—"}</div>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-slate-100 rounded"><X size={18} /></button>
        </div>
        <div className="p-5 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <StatBox label="Orders" value={c.order_count || 0} />
            <StatBox label="Spend" value={inr(c.total_spend || 0)} />
            <StatBox label="AOV" value={inr(c.avg_order_value || 0)} />
          </div>
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Consent</div>
            <div className="flex gap-2 text-xs">
              <span className={`chip ${c.consent_email ? "chip-ok" : "chip-slate"}`}>Email {c.consent_email ? "✓" : "✗"}</span>
              <span className={`chip ${c.consent_sms ? "chip-ok" : "chip-slate"}`}>SMS {c.consent_sms ? "✓" : "✗"}</span>
              <span className={`chip ${c.consent_whatsapp ? "chip-ok" : "chip-slate"}`}>WhatsApp {c.consent_whatsapp ? "✓" : "✗"}</span>
            </div>
          </div>
          {(c.tags || []).length > 0 && (
            <div>
              <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Tags</div>
              <div className="flex flex-wrap gap-1 text-xs">
                {c.tags.map((t) => <span key={t} className="chip chip-info">{t}</span>)}
              </div>
            </div>
          )}
          {(c.city || c.state || c.country) && (
            <div className="text-xs text-slate-500">
              {[c.city, c.state, c.country].filter(Boolean).join(", ")}
            </div>
          )}
          <div>
            <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Purchase history</div>
            <div className="space-y-2">
              {(data.history || []).map((s) => (
                <div key={s.id} className="border border-slate-200 rounded-md p-3 text-sm">
                  <div className="flex justify-between">
                    <span className="mono font-semibold">{s.invoice_no}</span>
                    <span className="mono">{inr(s.total)}</span>
                  </div>
                  <div className="text-xs text-slate-500">{s.created_at?.slice(0, 19).replace("T", " ")} · {s.location_code}</div>
                </div>
              ))}
              {(data.history || []).length === 0 && <div className="text-sm text-slate-500">No POS purchases yet.</div>}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function StatBox({ label, value }) {
  return <div className="bg-slate-50 rounded-md p-3"><div className="text-[10px] uppercase text-slate-500 tracking-widest">{label}</div><div className="mono font-semibold">{value}</div></div>;
}
