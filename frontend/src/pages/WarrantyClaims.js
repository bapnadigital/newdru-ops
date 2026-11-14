/* Admin: warranty claims workflow. */
import { useEffect, useState, useCallback } from "react";
import { api, fmtDate } from "@/lib/api";
import { toast } from "sonner";
import { LifeBuoy } from "lucide-react";

const STATUS = ["submitted", "under_review", "approved", "rejected", "resolved"];
const COLORS = {
  submitted: { bg: "#FEF3C7", fg: "#B45309" },
  under_review: { bg: "#DBEAFE", fg: "#1D4ED8" },
  approved: { bg: "#DCFCE7", fg: "#16A34A" },
  resolved: { bg: "#DCFCE7", fg: "#16A34A" },
  rejected: { bg: "#FEE2E2", fg: "#B91C1C" },
};

export default function WarrantyClaims() {
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [status, setStatus] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/warranty/claims", { params: { status: status || undefined, limit: 100 } });
      setRows(data.rows); setTotal(data.total);
    } catch (e) { toast.error("Load failed"); }
    finally { setLoading(false); }
  }, [status]);
  useEffect(() => { load(); }, [load]);

  const setClaimStatus = async (id, s) => {
    try {
      await api.patch(`/warranty/claims/${id}`, { status: s });
      toast.success(`Claim → ${s}`);
      load();
    } catch (e) { toast.error(e.response?.data?.detail || "Update failed"); }
  };

  return (
    <div className="p-6" data-testid="warranty-claims-page">
      <div className="flex items-center gap-3 mb-6">
        <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
          <LifeBuoy size={22} style={{ color: "#F0544A" }} />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Warranty Claims</h1>
          <div className="text-sm text-slate-500">{total.toLocaleString()} claims total</div>
        </div>
      </div>

      <div className="mb-4">
        <select value={status} onChange={(e) => setStatus(e.target.value)} data-testid="claims-status-filter"
                className="py-2 px-3 rounded-lg border border-slate-300 text-sm">
          <option value="">All statuses</option>
          {STATUS.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
        </select>
      </div>

      <div className="bg-white border rounded-2xl overflow-hidden shadow-sm">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-slate-500 uppercase text-xs">
            <tr>
              <th className="text-left p-3">Warranty ID</th>
              <th className="text-left p-3">SKU</th>
              <th className="text-left p-3">Customer</th>
              <th className="text-left p-3">Issue</th>
              <th className="text-left p-3">Submitted</th>
              <th className="text-left p-3">Status</th>
              <th className="text-left p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading && <tr><td colSpan={7} className="p-6 text-center text-slate-400">Loading…</td></tr>}
            {!loading && rows.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-slate-400">No claims filed.</td></tr>}
            {rows.map((r) => {
              const c = COLORS[r.status] || { bg: "#F1F5F9", fg: "#64748B" };
              return (
                <tr key={r.id} className="border-t border-slate-100">
                  <td className="p-3 font-mono font-bold" style={{ color: "#F0544A" }}>#{r.warranty_id}</td>
                  <td className="p-3 font-mono text-xs">{r.sku}</td>
                  <td className="p-3">
                    <div>{r.name}</div>
                    <div className="text-xs text-slate-500">{r.email}</div>
                  </td>
                  <td className="p-3">
                    <div className="font-semibold">{r.issue_type}</div>
                    <div className="text-xs text-slate-500 max-w-md truncate">{r.description}</div>
                  </td>
                  <td className="p-3 text-slate-500 whitespace-nowrap">{fmtDate(r.created_at)}</td>
                  <td className="p-3">
                    <span className="px-2 py-1 rounded text-xs font-semibold uppercase" style={{ background: c.bg, color: c.fg }}>{r.status.replace("_", " ")}</span>
                  </td>
                  <td className="p-3">
                    <select onChange={(e) => e.target.value && setClaimStatus(r.id, e.target.value)}
                            defaultValue="" data-testid={`claim-set-${r.id}`}
                            className="text-xs px-2 py-1 rounded border border-slate-300">
                      <option value="">Change…</option>
                      {STATUS.filter(s => s !== r.status).map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
                    </select>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
