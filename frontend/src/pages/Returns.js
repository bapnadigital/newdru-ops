import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

const inr = (n) => "₹" + Number(n || 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

// Customer returns: find the bill, pick what comes back, refund, print the credit note.
export default function Returns() {
  const [billNo, setBillNo] = useState("");
  const [sale, setSale] = useState(null);
  const [qty, setQty] = useState({});
  const [method, setMethod] = useState("cash");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState(null);
  const [recent, setRecent] = useState([]);
  const [biz, setBiz] = useState({});

  const loadRecent = () => api.get("/pos/returns", { params: { limit: 20 } }).then((r) => setRecent(r.data)).catch(() => {});
  useEffect(() => { loadRecent(); api.get("/pos/business-info").then((r) => setBiz(r.data)).catch(() => {}); }, []);

  const find = async (e) => {
    e.preventDefault();
    setSale(null); setQty({}); setNote(null);
    try {
      const { data } = await api.get("/pos/sales", { params: { invoice_no: billNo.trim(), limit: 1 } });
      if (!data.length) return toast.error("No bill with that number");
      setSale(data[0]);
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
  };

  const left = (it) => Number(it.quantity) - Number(it.returned_qty || 0);
  const ratio = sale ? Number(sale.total) / (sale.items.reduce((a, it) => a + Number(it.line_total || 0), 0) || 1) : 1;
  const estimate = sale ? sale.items.reduce((a, it) => a + (Number(qty[it.product_id]) || 0) * (Number(it.line_total) / Number(it.quantity)) * ratio, 0) : 0;
  const chosen = sale ? sale.items.filter((it) => Number(qty[it.product_id]) > 0) : [];

  const submit = async () => {
    if (!chosen.length) return toast.error("Enter how many of each item came back");
    if (reason.trim().length < 3) return toast.error("Write a short reason");
    setBusy(true);
    try {
      const { data } = await api.post("/pos/returns", {
        sale_id: sale.id, refund_method: method, reason,
        items: chosen.map((it) => ({ product_id: it.product_id, quantity: Number(qty[it.product_id]) })),
      });
      setNote(data); setSale(null); setQty({}); setReason(""); setBillNo("");
      toast.success(`Credit note ${data.credit_note_no} · refund ${inr(data.refund_total)}`);
      loadRecent();
    } catch (err) { toast.error(formatApiError(err.response?.data?.detail)); }
    setBusy(false);
  };

  return (
    <div>
      <div className="mb-6 print:hidden">
        <h1 className="text-2xl md:text-3xl font-brand text-slate-900">Returns</h1>
        <p className="text-sm text-slate-500">Customer brings something back: find the bill, enter what came back, refund. Stock goes back to the store and a GST credit note is created.</p>
      </div>

      <form onSubmit={find} className="flex gap-2 mb-4 max-w-md print:hidden">
        <input value={billNo} onChange={(e) => setBillNo(e.target.value)} placeholder="Bill number, e.g. NW-26-00012"
               data-testid="return-bill" className="flex-1 border border-slate-300 rounded-md px-3 py-2 text-sm" />
        <button className="btn-brand whitespace-nowrap">Find bill</button>
      </form>

      {sale && (
        <div className="bg-white border border-slate-200 rounded-xl p-4 mb-6 max-w-3xl print:hidden">
          <div className="flex justify-between text-sm mb-3">
            <div><span className="font-semibold">{sale.invoice_no}</span> · {new Date(sale.created_at).toLocaleString("en-IN")}</div>
            <div>{sale.customer_name || "Walk-in"} · Paid {inr(sale.total)} ({sale.payment_method_summary})</div>
          </div>
          <table className="w-full text-sm">
            <thead><tr className="text-xs uppercase text-slate-500 text-left"><th className="pb-2">Item</th><th className="text-right">Bought</th><th className="text-right">Already back</th><th className="text-right">Coming back now</th></tr></thead>
            <tbody>
              {sale.items.map((it, i) => (
                <tr key={it.product_id + i} className="border-t border-slate-100">
                  <td className="py-2"><div>{it.name}</div><div className="text-xs text-slate-500 font-mono">{it.sku}</div></td>
                  <td className="text-right">{it.quantity}</td>
                  <td className="text-right">{it.returned_qty || 0}</td>
                  <td className="text-right">
                    <input type="number" min="0" max={left(it)} disabled={left(it) <= 0} data-testid={`return-qty-${i}`}
                           value={qty[it.product_id] ?? ""} placeholder="0"
                           onChange={(e) => setQty({ ...qty, [it.product_id]: Math.max(0, Math.min(Number(e.target.value) || 0, left(it))) })}
                           className="w-16 border border-slate-300 rounded px-1 py-0.5 text-right disabled:bg-slate-50" />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4 items-end">
            <label className="text-xs text-slate-600">Refund as
              <select value={method} onChange={(e) => setMethod(e.target.value)} className="mt-1 w-full border border-slate-300 rounded-md px-2 py-2 text-sm">
                <option value="cash">Cash from till</option>
                <option value="upi">UPI</option>
                <option value="card">Card reversal</option>
                <option value="credit_note">Store credit (no money back)</option>
              </select>
            </label>
            <label className="text-xs text-slate-600 sm:col-span-2">Reason
              <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. wrong size, exchanged for L"
                     data-testid="return-reason" className="mt-1 w-full border border-slate-300 rounded-md px-2 py-2 text-sm" />
            </label>
          </div>
          <div className="flex justify-between items-center mt-4">
            <div className="text-sm">Refund: <span className="font-semibold">{inr(estimate)}</span></div>
            <button onClick={submit} disabled={busy} data-testid="return-confirm" className="btn-brand disabled:opacity-50">{busy ? "Saving…" : "Confirm return"}</button>
          </div>
        </div>
      )}

      {note && (
        <div className="print-area bg-white border border-slate-200 rounded-xl p-5 mb-6 max-w-md" data-testid="credit-note">
          <div className="text-center mb-3">
            <div className="font-semibold">{biz.name || "Newdru"}</div>
            {biz.gstin && <div className="text-xs">GSTIN {biz.gstin}</div>}
            <div className="text-sm font-semibold mt-2">CREDIT NOTE {note.credit_note_no}</div>
            <div className="text-xs text-slate-500">Against bill {note.invoice_no} · {new Date(note.created_at).toLocaleString("en-IN")}</div>
          </div>
          {note.items.map((it) => (
            <div key={it.product_id} className="flex justify-between text-sm"><span>{it.name} × {it.quantity}</span><span>{inr(it.refund)}</span></div>
          ))}
          {Object.entries(note.gst_breakup || {}).map(([rate, g]) => (
            <div key={rate} className="flex justify-between text-xs text-slate-500"><span>GST {Number(rate)}% on {inr(g.taxable)}</span><span>{inr(g.tax)}</span></div>
          ))}
          <div className="flex justify-between font-semibold border-t border-slate-200 mt-2 pt-2"><span>Refund ({note.refund_method.replace("_", " ")})</span><span>{inr(note.refund_total)}</span></div>
          <div className="text-xs text-slate-500 mt-2">Reason: {note.reason} · By {note.by_name}</div>
          <button onClick={() => window.print()} className="btn-outline no-print w-full mt-4">Print credit note</button>
        </div>
      )}

      <div className="bg-white border border-slate-200 rounded-xl p-4 max-w-3xl print:hidden">
        <div className="font-semibold mb-2 text-sm">Recent returns</div>
        {!recent.length && <div className="text-sm text-slate-500">None yet.</div>}
        {recent.map((r) => (
          <div key={r.id} className="flex justify-between text-sm py-1 border-t border-slate-100">
            <span><span className="font-mono">{r.credit_note_no}</span> · {r.invoice_no} · {r.reason}</span>
            <span>{inr(r.refund_total)} · {r.refund_method.replace("_", " ")}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
