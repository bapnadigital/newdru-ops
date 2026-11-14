/* Admin: warranty registrations list + details drawer. */
import { useEffect, useState, useCallback } from "react";
import { api, fmtDate } from "@/lib/api";
import { toast } from "sonner";
import { Search, Download, X, ExternalLink, ShieldCheck } from "lucide-react";

const STATUS_COLORS = {
  active: { bg: "#DCFCE7", fg: "#16A34A" },
  approved: { bg: "#DBEAFE", fg: "#1D4ED8" },
  rejected: { bg: "#FEE2E2", fg: "#B91C1C" },
  expired: { bg: "#F1F5F9", fg: "#64748B" },
};

const EVENT_COLORS = {
  purchased: { bg: "#DCFCE7", fg: "#16A34A" },
  warranty_registered: { bg: "#EDE9FE", fg: "#6D28D9" },
  claim_submitted: { bg: "#FEF3C7", fg: "#B45309" },
  claim_approved: { bg: "#DBEAFE", fg: "#1D4ED8" },
  claim_resolved: { bg: "#DCFCE7", fg: "#16A34A" },
  claim_rejected: { bg: "#FEE2E2", fg: "#B91C1C" },
};

export default function WarrantyRegistrations() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [sourceFilter, setSourceFilter] = useState("");
  const [skip, setSkip] = useState(0);
  const [limit] = useState(25);
  const [selected, setSelected] = useState(null);
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/warranty/registrations", {
        params: { q: q || undefined, status: statusFilter || undefined, source: sourceFilter || undefined, skip, limit },
      });
      setRows(data.rows); setTotal(data.total);
    } catch (e) { toast.error(e.response?.data?.detail || "Load failed"); }
    finally { setLoading(false); }
  }, [q, statusFilter, sourceFilter, skip, limit]);
  useEffect(() => { load(); }, [load]);

  const openDetail = async (r) => {
    setSelected(r); setDetail(null);
    try {
      const { data } = await api.get(`/warranty/registrations/${r.id}`);
      setDetail(data);
    } catch (e) { toast.error("Load detail failed"); }
  };

  const setStatus = async (newStatus) => {
    if (!selected) return;
    try {
      await api.patch(`/warranty/registrations/${selected.id}`, { status: newStatus });
      toast.success(`Status → ${newStatus}`);
      await openDetail(selected); await load();
    } catch (e) { toast.error(e.response?.data?.detail || "Update failed"); }
  };

  return (
    <div className="p-6" data-testid="warranty-registrations-page">
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
            <ShieldCheck size={22} style={{ color: "#F0544A" }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Warranty Registrations</h1>
            <div className="text-sm text-slate-500">{total.toLocaleString()} total · {rows.length} shown</div>
          </div>
        </div>
        <a href={`${process.env.REACT_APP_BACKEND_URL || ""}/api/warranty/export.csv`}
           target="_blank" rel="noreferrer" data-testid="warranty-export-csv"
           className="inline-flex items-center gap-2 px-4 py-2 rounded-lg border border-slate-300 text-sm font-semibold text-slate-700 hover:bg-slate-50">
          <Download size={16} /> Export CSV
        </a>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input data-testid="warranty-search" value={q} onChange={(e) => { setSkip(0); setQ(e.target.value); }}
                 placeholder="Warranty ID, SKU, product, name, email…"
                 className="pl-9 pr-3 py-2 rounded-lg border border-slate-300 text-sm w-80" />
        </div>
        <select data-testid="warranty-status-filter" value={statusFilter} onChange={(e) => { setSkip(0); setStatusFilter(e.target.value); }}
                className="py-2 px-3 rounded-lg border border-slate-300 text-sm">
          <option value="">All statuses</option>
          <option value="active">Active</option>
          <option value="approved">Approved</option>
          <option value="rejected">Rejected</option>
          <option value="expired">Expired</option>
        </select>
        <select data-testid="warranty-source-filter" value={sourceFilter} onChange={(e) => { setSkip(0); setSourceFilter(e.target.value); }}
                className="py-2 px-3 rounded-lg border border-slate-300 text-sm">
          <option value="">All sources</option>
          <option value="amazon">Amazon</option>
          <option value="flipkart">Flipkart</option>
          <option value="newdru.com">newdru.com</option>
          <option value="offline_store">Offline Store</option>
          <option value="other">Other</option>
        </select>
      </div>

      {/* Table */}
      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm" data-testid="warranty-table">
          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
            <tr>
              <th className="text-left p-3">Warranty ID</th>
              <th className="text-left p-3">Product</th>
              <th className="text-left p-3">Customer</th>
              <th className="text-left p-3">Source</th>
              <th className="text-left p-3">Registered</th>
              <th className="text-left p-3">Days left</th>
              <th className="text-left p-3">Status</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="p-6 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && (
              <tr><td colSpan={7} className="p-8 text-center text-slate-400">No registrations yet. When customers register on <span className="font-mono">/warranty</span> they'll appear here.</td></tr>
            )}
            {rows.map((r) => {
              const c = STATUS_COLORS[r.status] || STATUS_COLORS.active;
              return (
                <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50 cursor-pointer"
                    onClick={() => openDetail(r)} data-testid={`warranty-row-${r.warranty_id}`}>
                  <td className="p-3 font-mono font-bold" style={{ color: "#F0544A" }}>#{r.warranty_id}</td>
                  <td className="p-3">
                    <div className="font-semibold text-slate-900">{r.product_name}</div>
                    <div className="text-xs text-slate-500 font-mono">{r.sku}</div>
                  </td>
                  <td className="p-3">
                    <div className="text-slate-900">{r.name}</div>
                    <div className="text-xs text-slate-500">{r.email}</div>
                  </td>
                  <td className="p-3 capitalize">{r.purchase_source?.replace("_", " ")}</td>
                  <td className="p-3 text-slate-500">{fmtDate(r.created_at)}</td>
                  <td className="p-3">
                    <span className={`font-semibold ${r.days_left > 30 ? "text-emerald-600" : r.days_left > 0 ? "text-amber-600" : "text-slate-400"}`}>
                      {r.days_left} days
                    </span>
                  </td>
                  <td className="p-3">
                    <span className="px-2 py-1 rounded text-xs font-semibold uppercase" style={{ background: c.bg, color: c.fg }}>{r.status}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Pager */}
      {total > limit && (
        <div className="flex items-center justify-between mt-3 text-sm">
          <div className="text-slate-500">Showing {skip + 1}–{Math.min(skip + limit, total)} of {total}</div>
          <div className="flex gap-2">
            <button disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - limit))} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Prev</button>
            <button disabled={skip + limit >= total} onClick={() => setSkip(skip + limit)} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}

      {/* Drawer */}
      {selected && (
        <div className="fixed inset-0 z-40 bg-slate-900/40" onClick={() => setSelected(null)}>
          <aside className="absolute right-0 top-0 h-full w-full max-w-xl bg-white shadow-2xl overflow-y-auto" onClick={(e) => e.stopPropagation()}
                 data-testid="warranty-drawer">
            <div className="flex items-center justify-between p-5 border-b">
              <div>
                <div className="font-mono text-xl font-bold" style={{ color: "#F0544A" }}>#{selected.warranty_id}</div>
                <div className="text-xs text-slate-500">Registered {fmtDate(selected.created_at)}</div>
              </div>
              <button onClick={() => setSelected(null)} className="p-1.5 rounded hover:bg-slate-100"><X size={18} /></button>
            </div>

            {!detail && <div className="p-6 text-slate-400">Loading…</div>}
            {detail && (
              <div className="p-5 space-y-6">
                {/* Days-left banner */}
                <div className="rounded-xl p-4" style={{ background: detail.registration.days_left > 30 ? "#DCFCE7" : detail.registration.days_left > 0 ? "#FEF3C7" : "#F1F5F9" }}>
                  <div className="text-3xl font-bold text-slate-900">{detail.registration.days_left} days left</div>
                  <div className="text-xs text-slate-600 mt-0.5">Ends on {fmtDate(detail.registration.warranty_end)}</div>
                </div>

                {/* Actions */}
                <div className="flex flex-wrap gap-2">
                  {["active", "approved", "rejected", "expired"].map((s) => (
                    <button key={s} onClick={() => setStatus(s)} data-testid={`warranty-set-${s}`}
                            disabled={detail.registration.status === s}
                            className="px-3 py-1.5 rounded-lg text-xs font-semibold border border-slate-300 hover:bg-slate-50 disabled:opacity-40 capitalize">
                      Mark {s}
                    </button>
                  ))}
                  <a href={`${process.env.REACT_APP_BACKEND_URL || ""}/api/warranty/public/certificate/${detail.registration.warranty_id}.pdf`}
                     target="_blank" rel="noreferrer"
                     className="ml-auto inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-white"
                     style={{ background: "#F0544A" }}>
                    <ExternalLink size={12} /> Certificate PDF
                  </a>
                </div>

                {/* Product */}
                <Section title="Product">
                  <KV label="Name" value={detail.registration.product_name} />
                  <KV label="SKU" value={<span className="font-mono">{detail.registration.sku}</span>} />
                  <KV label="Warranty" value={`${detail.registration.warranty_months} months`} />
                </Section>

                {/* Customer */}
                <Section title="Customer">
                  <KV label="Name" value={detail.registration.name} />
                  <KV label="Email" value={detail.registration.email} />
                  <KV label="Phone" value={detail.registration.phone} />
                  <KV label="Purchase date" value={fmtDate(detail.registration.purchase_date)} />
                  <KV label="Bought from" value={detail.registration.purchase_source} />
                  {detail.registration.retailer_name && <KV label="Retailer" value={detail.registration.retailer_name} />}
                  {detail.registration.invoice_url && (
                    <KV label="Invoice" value={<a href={detail.registration.invoice_url} target="_blank" rel="noreferrer" className="underline text-[#F0544A]">View file</a>} />
                  )}
                </Section>

                {/* Tracking */}
                <Section title="Tracking">
                  <KV label="IP" value={detail.registration.ip} />
                  <KV label="City" value={detail.registration.geo?.city || "—"} />
                  <KV label="State" value={detail.registration.geo?.region || "—"} />
                  <KV label="Country" value={detail.registration.geo?.country_code || "—"} />
                </Section>

                {/* Activity */}
                <Section title={`Activity (${detail.activity.length})`}>
                  {detail.activity.map((a) => {
                    const c = EVENT_COLORS[a.event] || { bg: "#F1F5F9", fg: "#64748B" };
                    return (
                      <div key={a.id} className="flex items-center gap-2 text-xs py-1">
                        <span className="px-2 py-0.5 rounded font-semibold uppercase" style={{ background: c.bg, color: c.fg }}>{a.event.replace(/_/g, " ")}</span>
                        <span className="text-slate-500">{fmtDate(a.created_at)}</span>
                      </div>
                    );
                  })}
                </Section>

                {/* Claims */}
                <Section title={`Claims (${detail.claims.length})`}>
                  {detail.claims.length === 0 && <div className="text-sm text-slate-400">No claims filed.</div>}
                  {detail.claims.map((c) => (
                    <div key={c.id} className="p-3 rounded-lg border border-slate-200 mb-2">
                      <div className="flex items-center justify-between mb-1">
                        <div className="font-semibold text-sm">{c.issue_type}</div>
                        <span className="text-xs px-2 py-0.5 rounded uppercase font-semibold" style={{ background: "#F1F5F9" }}>{c.status}</span>
                      </div>
                      <div className="text-sm text-slate-600">{c.description}</div>
                      <div className="text-xs text-slate-400 mt-1">{fmtDate(c.created_at)}</div>
                    </div>
                  ))}
                </Section>
              </div>
            )}
          </aside>
        </div>
      )}
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div>
      <div className="text-xs font-bold uppercase tracking-wider text-slate-500 mb-2">{title}</div>
      <div className="space-y-1">{children}</div>
    </div>
  );
}

function KV({ label, value }) {
  return (
    <div className="flex items-baseline gap-3 text-sm">
      <div className="text-slate-500 w-28 shrink-0">{label}</div>
      <div className="text-slate-900 flex-1">{value || "—"}</div>
    </div>
  );
}
