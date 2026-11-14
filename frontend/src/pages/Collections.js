import { useEffect, useState } from "react";
import { api, fmtINR, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { BellRing, Download } from "lucide-react";

export default function Collections() {
  const [data, setData] = useState(null);
  const load = async () => { try { setData((await api.get("/b2b/collections/dashboard")).data); } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); } };
  useEffect(() => { load(); }, []);

  const remind = async (id, channel) => {
    try { const { data } = await api.post(`/b2b/orders/${id}/remind`, null, { params: { channel } });
      toast.success(`Reminder sent via ${channel}${data.result?.mode === "simulator" ? " (simulator)" : ""}`); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const download = async () => {
    const res = await api.get("/b2b/collections/receivables.csv", { responseType: "blob" });
    const url = URL.createObjectURL(new Blob([res.data])); const a = document.createElement("a");
    a.href = url; a.download = "receivables.csv"; a.click();
  };

  if (!data) return <div className="text-slate-500">Loading…</div>;
  const bucketColor = { "0-30": "bg-emerald-50 text-emerald-700 border-emerald-200",
                       "31-60": "bg-amber-50 text-amber-700 border-amber-200",
                       "61-90": "bg-orange-50 text-orange-700 border-orange-200",
                       "90+": "bg-red-50 text-red-700 border-red-200" };
  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl md:text-3xl font-brand text-slate-900">Collections</h1>
          <p className="text-sm text-slate-500">Aging buckets and outstanding receivables for wholesale invoices.</p>
        </div>
        <button onClick={download} className="btn-secondary flex items-center gap-1"><Download size={14} />Receivables CSV</button>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-6">
        <div className="card-surface p-4"><div className="text-xs text-slate-500 uppercase tracking-widest">Total outstanding</div><div className="text-3xl font-brand text-slate-900 mt-1">{fmtINR(data.total_outstanding)}</div><div className="text-xs text-slate-500 mt-1">{data.orders_open} open invoices</div></div>
        {["0-30", "31-60", "61-90", "90+"].map((b) => (
          <div key={b} className={`p-4 rounded-lg border ${bucketColor[b]}`}>
            <div className="text-xs uppercase tracking-widest">Bucket {b}d</div>
            <div className="text-2xl font-brand mt-1">{fmtINR(data.buckets[b] || 0)}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="card-surface p-4">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Top debtors</div>
          <table className="data-table w-full">
            <thead><tr><th>Customer</th><th className="text-right">Outstanding</th><th className="text-right">Orders</th><th className="text-right">Oldest</th></tr></thead>
            <tbody>
              {data.top_debtors.map(d => (
                <tr key={d.customer_id}>
                  <td>{d.customer_name}</td>
                  <td className="text-right font-mono font-semibold">{fmtINR(d.outstanding)}</td>
                  <td className="text-right font-mono">{d.orders}</td>
                  <td className="text-right font-mono">{d.oldest_days_overdue}d</td>
                </tr>
              ))}
              {data.top_debtors.length === 0 && <tr><td colSpan={4} className="p-4 text-center text-slate-400">No outstanding.</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="card-surface p-4">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Overdue orders</div>
          <div className="max-h-96 overflow-y-auto scroll-thin">
            <table className="data-table w-full">
              <thead><tr><th>#</th><th>Customer</th><th className="text-right">Outstanding</th><th className="text-right">Days</th><th></th></tr></thead>
              <tbody>
                {data.overdue_orders.map(o => (
                  <tr key={o.id}>
                    <td className="font-mono">{o.order_no}</td>
                    <td>{o.customer_name}</td>
                    <td className="text-right font-mono font-semibold">{fmtINR(o.outstanding)}</td>
                    <td className="text-right font-mono text-red-600">{o.days_overdue}d</td>
                    <td>
                      <div className="flex gap-1">
                        <button data-testid={`remind-wa-${o.order_no}`} onClick={() => remind(o.id, "whatsapp")} className="px-2 py-1 text-xs border border-slate-300 rounded flex items-center gap-1"><BellRing size={11} />WA</button>
                        <button onClick={() => remind(o.id, "sms")} className="px-2 py-1 text-xs border border-slate-300 rounded flex items-center gap-1"><BellRing size={11} />SMS</button>
                      </div>
                    </td>
                  </tr>
                ))}
                {data.overdue_orders.length === 0 && <tr><td colSpan={5} className="p-4 text-center text-slate-400">No overdue invoices.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
