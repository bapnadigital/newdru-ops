import { useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Download } from "lucide-react";

export default function Reports() {
  const [from, setFrom] = useState(new Date(Date.now() - 30 * 86400e3).toISOString().slice(0, 10));
  const [to, setTo] = useState(new Date().toISOString().slice(0, 10));
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/reports/sales", { params: { from_date: from, to_date: to + "T23:59:59" } });
      setData(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setLoading(false);
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, []);

  const download = async (kind = "sales") => {
    try {
      const res = await api.get(`/reports/${kind}/csv`, { params: { from_date: from, to_date: to + "T23:59:59" }, responseType: "blob" });
      const url = URL.createObjectURL(new Blob([res.data]));
      const a = document.createElement("a"); a.href = url; a.download = kind === "returns" ? "credit_notes.csv" : "sales.csv"; a.click();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Reports</h1>
          <p className="text-slate-500 text-sm">Sales, GST summary and inventory value.</p>
        </div>
        <div className="flex gap-2 items-end">
          <div>
            <label className="text-xs text-slate-500 block mb-1">From</label>
            <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} className="border border-slate-300 rounded-md px-2 py-2 text-sm" />
          </div>
          <div>
            <label className="text-xs text-slate-500 block mb-1">To</label>
            <input type="date" value={to} onChange={(e) => setTo(e.target.value)} className="border border-slate-300 rounded-md px-2 py-2 text-sm" />
          </div>
          <button onClick={load} className="px-3 py-2 bg-[hsl(234_61%_25%)] text-white rounded-md text-sm">Run</button>
          <button onClick={() => download("sales")} className="px-3 py-2 border border-slate-300 rounded-md text-sm flex items-center gap-1"><Download size={14} />Sales CSV</button>
          <button onClick={() => download("returns")} data-testid="credit-notes-csv" className="px-3 py-2 border border-slate-300 rounded-md text-sm flex items-center gap-1"><Download size={14} />Credit notes CSV</button>
        </div>
      </div>

      {loading && <div className="text-slate-500">Loading…</div>}
      {data && (
        <>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-4 mb-6">
            <div className="newdru-kpi"><div className="text-xs uppercase text-slate-500 tracking-widest">Sales</div><div className="text-3xl font-semibold text-indigo-700 mt-1">{data.count}</div></div>
            <div className="newdru-kpi"><div className="text-xs uppercase text-slate-500 tracking-widest">Subtotal (ex-GST)</div><div className="text-3xl font-semibold text-indigo-700 mt-1">{inr(data.subtotal)}</div></div>
            <div className="newdru-kpi"><div className="text-xs uppercase text-slate-500 tracking-widest">Total GST</div><div className="text-3xl font-semibold text-indigo-700 mt-1">{inr(data.tax_total)}</div></div>
            <div className="newdru-kpi"><div className="text-xs uppercase text-slate-500 tracking-widest">Grand Total</div><div className="text-3xl font-semibold text-indigo-700 mt-1">{inr(data.total)}</div></div>
          </div>
          {data.credit_notes?.count > 0 && (
            <div className="bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm mb-6" data-testid="report-net">
              Returns in this period: {data.credit_notes.count} credit note{data.credit_notes.count > 1 ? "s" : ""}, {inr(data.credit_notes.total)} (GST {inr(data.credit_notes.tax)}).
              {" "}<b>Net sales {inr(data.net_total)} · net GST {inr(data.net_tax)}</b>
            </div>
          )}

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <div className="newdru-kpi">
              <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">GST Summary</div>
              <table className="newdru-table">
                <thead><tr><th>Rate</th><th className="text-right">Taxable</th><th className="text-right">GST</th></tr></thead>
                <tbody>
                  {Object.entries(data.gst_breakup || {}).map(([rate, v]) => (
                    <tr key={rate}><td>@ {rate}%</td><td className="text-right mono">{inr(v.taxable)}</td><td className="text-right mono">{inr(v.tax)}</td></tr>
                  ))}
                  {Object.keys(data.gst_breakup || {}).length === 0 && <tr><td colSpan={3} className="text-center text-slate-400 p-4">No data</td></tr>}
                </tbody>
              </table>
            </div>
            <div className="newdru-kpi">
              <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Recent invoices</div>
              <div className="max-h-96 overflow-y-auto scroll-thin">
                <table className="newdru-table">
                  <thead><tr><th>#</th><th>Date</th><th>Loc</th><th className="text-right">Total</th></tr></thead>
                  <tbody>
                    {(data.sales || []).slice(0, 40).map((s) => (
                      <tr key={s.id}>
                        <td className="mono">{s.invoice_no}</td>
                        <td className="text-xs">{s.created_at?.slice(0, 16).replace("T", " ")}</td>
                        <td>{s.location_code}</td>
                        <td className="text-right mono">{inr(s.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
