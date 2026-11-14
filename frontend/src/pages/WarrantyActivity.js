/* Admin: warranty user activity feed — Dyrect-style. */
import { useEffect, useState, useCallback } from "react";
import { api, fmtDate } from "@/lib/api";
import { toast } from "sonner";
import { Activity, Search } from "lucide-react";

const EVENT_COLORS = {
  purchased: { bg: "#DCFCE7", fg: "#16A34A" },
  warranty_registered: { bg: "#EDE9FE", fg: "#6D28D9" },
  claim_submitted: { bg: "#FEF3C7", fg: "#B45309" },
  claim_approved: { bg: "#DBEAFE", fg: "#1D4ED8" },
  claim_resolved: { bg: "#DCFCE7", fg: "#16A34A" },
  claim_rejected: { bg: "#FEE2E2", fg: "#B91C1C" },
};

export default function WarrantyActivity() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [event, setEvent] = useState("");
  const [skip, setSkip] = useState(0);
  const [limit] = useState(50);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/warranty/activity", {
        params: { q: q || undefined, event: event || undefined, skip, limit },
      });
      setRows(data.rows); setTotal(data.total);
    } catch (e) { toast.error("Load failed"); }
    finally { setLoading(false); }
  }, [q, event, skip, limit]);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="p-6" data-testid="warranty-activity-page">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
          <Activity size={22} style={{ color: "#F0544A" }} />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">User Activities</h1>
          <div className="text-sm text-slate-500">{total.toLocaleString()} events across purchases, registrations, and claims</div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input data-testid="activity-search" value={q} onChange={(e) => { setSkip(0); setQ(e.target.value); }}
                 placeholder="SKU, product, warranty ID…"
                 className="pl-9 pr-3 py-2 rounded-lg border border-slate-300 text-sm w-80" />
        </div>
        <select data-testid="activity-event-filter" value={event} onChange={(e) => { setSkip(0); setEvent(e.target.value); }}
                className="py-2 px-3 rounded-lg border border-slate-300 text-sm">
          <option value="">All events</option>
          <option value="purchased">Purchased</option>
          <option value="warranty_registered">Warranty Registered</option>
          <option value="claim_submitted">Claim Submitted</option>
          <option value="claim_approved">Claim Approved</option>
          <option value="claim_rejected">Claim Rejected</option>
        </select>
      </div>

      <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
            <tr>
              <th className="text-left p-3">Date</th>
              <th className="text-left p-3">SKU ID</th>
              <th className="text-left p-3">Product</th>
              <th className="text-left p-3">Event</th>
              <th className="text-left p-3">Tracking info</th>
              <th className="text-left p-3">IP City</th>
              <th className="text-left p-3">IP State</th>
              <th className="text-left p-3">Country</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={8} className="p-6 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-400">No activity yet.</td></tr>}
            {rows.map((r) => {
              const c = EVENT_COLORS[r.event] || { bg: "#F1F5F9", fg: "#64748B" };
              return (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="p-3 whitespace-nowrap text-slate-600">{fmtDate(r.created_at)}</td>
                  <td className="p-3 font-mono text-xs">{r.sku || "—"}</td>
                  <td className="p-3">{r.product_name || "—"}</td>
                  <td className="p-3">
                    <span className="px-2 py-1 rounded text-xs font-semibold uppercase" style={{ background: c.bg, color: c.fg }}>{(r.event || "").replace(/_/g, " ")}</span>
                  </td>
                  <td className="p-3 text-xs text-slate-600">
                    <div>Tracking Id: <span className="font-mono">{(r.tracking_id || "").slice(0, 32)}</span></div>
                    {r.user_agent && <div>UA: {(r.user_agent || "").slice(0, 40)}</div>}
                    {r.ip && <div>IP: {r.ip}</div>}
                  </td>
                  <td className="p-3">{r.geo?.city || "—"}</td>
                  <td className="p-3">{r.geo?.region || "—"}</td>
                  <td className="p-3">{r.geo?.country_code || "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {total > limit && (
        <div className="flex items-center justify-between mt-3 text-sm">
          <div className="text-slate-500">Showing {skip + 1}–{Math.min(skip + limit, total)} of {total}</div>
          <div className="flex gap-2">
            <button disabled={skip === 0} onClick={() => setSkip(Math.max(0, skip - limit))} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Prev</button>
            <button disabled={skip + limit >= total} onClick={() => setSkip(skip + limit)} className="px-3 py-1.5 rounded border border-slate-300 disabled:opacity-40">Next</button>
          </div>
        </div>
      )}
    </div>
  );
}
