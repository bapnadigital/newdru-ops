import { useEffect, useMemo, useState } from "react";
import { api, fmtINR, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { Plus, X, ScanBarcode, Trash2, Truck, FileText, IndianRupee, BellRing } from "lucide-react";

export default function B2B() {
  const [tab, setTab] = useState("orders");
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-brand text-slate-900">B2B / Wholesale</h1>
        <p className="text-sm text-slate-500">Wholesale customers, orders, dispatch notes and invoicing.</p>
      </div>
      <div className="flex gap-1 mb-4 border-b border-slate-200">
        {[["orders", "Orders"], ["customers", "Wholesale Customers"]].map(([k, l]) => (
          <button key={k} data-testid={`b2b-tab-${k}`} onClick={() => setTab(k)}
                  className={`px-4 py-2 text-sm border-b-2 -mb-px ${tab === k ? "border-[#F0544A] text-[#D84038] font-semibold" : "border-transparent text-slate-600 hover:text-slate-900"}`}>
            {l}
          </button>
        ))}
      </div>
      {tab === "orders" ? <Orders /> : <CustomersTab />}
    </div>
  );
}

function Orders() {
  const [orders, setOrders] = useState([]);
  const [status, setStatus] = useState("");
  const [creating, setCreating] = useState(false);

  const load = async () => {
    try { const { data } = await api.get("/b2b/orders", { params: { status: status || undefined } }); setOrders(data); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  useEffect(() => { load(); /* eslint-disable-next-line */ }, [status]);

  const act = async (id, path) => {
    try { await api.post(`/b2b/orders/${id}/${path}`); toast.success(path); load(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  const chip = (s) => ({
    draft: "bg-slate-100 text-slate-700",
    confirmed: "bg-amber-50 text-amber-700",
    dispatched: "bg-blue-50 text-blue-700",
    invoiced: "bg-indigo-50 text-indigo-700",
    partially_paid: "bg-purple-50 text-purple-700",
    paid: "bg-emerald-50 text-emerald-700",
    cancelled: "bg-red-50 text-red-700",
  }[s] || "bg-slate-100 text-slate-700");

  return (
    <div>
      <div className="flex justify-between items-center mb-3 gap-2 flex-wrap">
        <select value={status} onChange={(e) => setStatus(e.target.value)} className="px-3 py-2 border border-slate-300 rounded-md text-sm">
          <option value="">All statuses</option>
          {["confirmed", "dispatched", "invoiced", "partially_paid", "paid", "cancelled"].map(s => <option key={s} value={s}>{s}</option>)}
        </select>
        <button data-testid="b2b-new-order" onClick={() => setCreating(true)} className="btn-brand"><Plus size={14} className="mr-1" />New order</button>
      </div>

      <div className="card-surface overflow-x-auto">
        <table className="data-table w-full">
          <thead><tr><th>Order #</th><th>Customer</th><th className="text-right">Total</th><th className="text-right">Outstanding</th><th>Status</th><th>Due</th><th></th></tr></thead>
          <tbody>
            {orders.map((o) => (
              <tr key={o.id}>
                <td className="font-mono font-semibold">{o.order_no}</td>
                <td>
                  <div>{o.customer_name}</div>
                  {o.customer_gstin && <div className="text-xs text-slate-500 font-mono">{o.customer_gstin}</div>}
                </td>
                <td className="text-right font-mono">{fmtINR(o.total)}</td>
                <td className={`text-right font-mono ${o.outstanding > 0 ? "text-red-600 font-semibold" : ""}`}>{fmtINR(o.outstanding || 0)}</td>
                <td><span className={`chip ${chip(o.status)}`}>{o.status}</span></td>
                <td className="text-xs text-slate-500">{o.due_date?.slice(0, 10) || "—"}</td>
                <td>
                  <div className="flex gap-1">
                    {o.status === "confirmed" && <button onClick={() => act(o.id, "dispatch")} className="px-2 py-1 border border-slate-300 rounded text-xs flex items-center gap-1"><Truck size={12} />Dispatch</button>}
                    {(o.status === "dispatched" || o.status === "confirmed") && !o.invoice_no && <button onClick={() => act(o.id, "invoice")} className="px-2 py-1 bg-indigo-600 text-white rounded text-xs flex items-center gap-1"><FileText size={12} />Invoice</button>}
                    {o.outstanding > 0 && o.invoice_no && <PaymentButton orderId={o.id} onDone={load} />}
                  </div>
                </td>
              </tr>
            ))}
            {orders.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-slate-400">No orders yet.</td></tr>}
          </tbody>
        </table>
      </div>

      {creating && <OrderModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} />}
    </div>
  );
}

function PaymentButton({ orderId, onDone }) {
  const [open, setOpen] = useState(false);
  const [amt, setAmt] = useState(0);
  const [method, setMethod] = useState("bank_transfer");
  const [ref, setRef] = useState("");
  const save = async () => {
    try { await api.post(`/b2b/orders/${orderId}/payments`, { amount: parseFloat(amt), method, reference: ref }); toast.success("Payment recorded"); setOpen(false); onDone(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <>
      <button onClick={() => setOpen(true)} className="px-2 py-1 bg-emerald-600 text-white rounded text-xs flex items-center gap-1"><IndianRupee size={12} />Payment</button>
      {open && (
        <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4" onClick={(e) => e.target === e.currentTarget && setOpen(false)}>
          <div className="bg-white rounded-md w-full max-w-md shadow-xl">
            <div className="px-5 py-3 border-b flex justify-between"><h3 className="font-semibold">Record payment</h3><button onClick={() => setOpen(false)}><X size={16} /></button></div>
            <div className="p-5 space-y-3">
              <input type="number" placeholder="Amount ₹" value={amt} onChange={(e) => setAmt(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
              <select value={method} onChange={(e) => setMethod(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm">
                {["cash", "bank_transfer", "upi", "cheque", "card"].map(m => <option key={m} value={m}>{m}</option>)}
              </select>
              <input placeholder="Reference / UTR / cheque #" value={ref} onChange={(e) => setRef(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
            </div>
            <div className="border-t px-5 py-3 flex justify-end gap-2"><button onClick={() => setOpen(false)} className="px-4 py-2 border border-slate-300 rounded-md text-sm">Cancel</button><button onClick={save} className="btn-brand">Record</button></div>
          </div>
        </div>
      )}
    </>
  );
}

function OrderModal({ onClose, onSaved }) {
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState("");
  const [poRef, setPoRef] = useState("");
  const [shipFrom, setShipFrom] = useState("BHIWANDI");
  const [scan, setScan] = useState("");
  const [lines, setLines] = useState([]);
  const [notes, setNotes] = useState("");
  useEffect(() => { api.get("/b2b/customers").then(r => setCustomers(r.data)).catch(() => {}); }, []);

  const addProd = async (e) => {
    e.preventDefault(); if (!scan) return;
    try {
      const { data } = await api.get("/products/lookup", { params: { code: scan } });
      setLines([...lines, { product_id: data.id, sku: data.sku, name: data.name, hsn: data.hsn,
        gst_rate: data.gst_rate || 18, quantity: 1, unit_price: data.sell_price || data.mrp || 0, discount: 0 }]);
      setScan("");
    } catch { toast.error("Not found"); }
  };
  const upd = (i, patch) => { const n = [...lines]; n[i] = { ...n[i], ...patch }; setLines(n); };
  const rm = (i) => setLines(lines.filter((_, x) => x !== i));

  const total = useMemo(() => lines.reduce((s, l) => s + Math.max(0, l.unit_price * l.quantity - l.discount), 0), [lines]);

  const save = async () => {
    try {
      await api.post("/b2b/orders", { customer_id: customerId, po_reference: poRef, ship_from: shipFrom, lines, notes });
      toast.success("Order created"); onSaved();
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };

  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-md w-full max-w-3xl max-h-[92vh] overflow-y-auto shadow-xl">
        <div className="px-5 py-3 border-b flex justify-between sticky top-0 bg-white"><h3 className="font-semibold text-lg">New B2B order</h3><button onClick={onClose}><X size={18} /></button></div>
        <div className="p-5 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block"><div className="text-xs text-slate-600 mb-1">Wholesale customer *</div>
              <select data-testid="b2b-customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm">
                <option value="">Select…</option>
                {customers.map(c => <option key={c.id} value={c.id}>{c.company || c.name} — outstanding {fmtINR(c.outstanding || 0)}</option>)}
              </select></label>
            <label className="block"><div className="text-xs text-slate-600 mb-1">PO reference</div><input value={poRef} onChange={(e) => setPoRef(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" /></label>
            <label className="block"><div className="text-xs text-slate-600 mb-1">Ship from</div>
              <select value={shipFrom} onChange={(e) => setShipFrom(e.target.value)} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm">
                <option value="BHIWANDI">Bhiwandi Warehouse</option>
                <option value="STORE">Newdru Store</option>
              </select></label>
          </div>
          <form onSubmit={addProd} className="flex gap-2">
            <div className="flex-1 relative"><ScanBarcode size={16} className="absolute left-3 top-2.5 text-slate-400" /><input value={scan} onChange={(e) => setScan(e.target.value)} placeholder="Scan/SKU/barcode" className="w-full pl-9 pr-3 py-2 border border-slate-300 rounded-md text-sm" /></div>
            <button className="btn-brand">Add</button>
          </form>
          <div className="border border-slate-200 rounded-md overflow-x-auto">
            <table className="data-table w-full">
              <thead><tr><th>SKU</th><th>Name</th><th>Qty</th><th className="text-right">Rate</th><th className="text-right">Disc</th><th className="text-right">Amount</th><th></th></tr></thead>
              <tbody>
                {lines.map((l, i) => (
                  <tr key={i}>
                    <td className="font-mono">{l.sku}</td><td>{l.name}</td>
                    <td><input type="number" value={l.quantity} onChange={(e) => upd(i, { quantity: parseInt(e.target.value || 1) })} className="w-16 border border-slate-300 rounded px-2 py-1" /></td>
                    <td className="text-right"><input type="number" value={l.unit_price} onChange={(e) => upd(i, { unit_price: parseFloat(e.target.value || 0) })} className="w-20 border border-slate-300 rounded px-2 py-1 text-right" /></td>
                    <td className="text-right"><input type="number" value={l.discount} onChange={(e) => upd(i, { discount: parseFloat(e.target.value || 0) })} className="w-16 border border-slate-300 rounded px-2 py-1 text-right" /></td>
                    <td className="text-right font-mono">{fmtINR(Math.max(0, l.quantity * l.unit_price - l.discount))}</td>
                    <td><button onClick={() => rm(i)} className="p-1 text-red-600"><Trash2 size={14} /></button></td>
                  </tr>
                ))}
                {lines.length === 0 && <tr><td colSpan={7} className="p-4 text-center text-slate-400">Scan items to add.</td></tr>}
              </tbody>
            </table>
          </div>
          <input value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
          <div className="text-right text-lg">Estimated total: <span className="font-mono font-bold">{fmtINR(total)}</span></div>
        </div>
        <div className="border-t px-5 py-3 flex justify-end gap-2 sticky bottom-0 bg-white"><button onClick={onClose} className="px-4 py-2 border border-slate-300 rounded-md text-sm">Cancel</button><button data-testid="b2b-save" onClick={save} disabled={!customerId || !lines.length} className="btn-brand disabled:opacity-50">Create order</button></div>
      </div>
    </div>
  );
}

function CustomersTab() {
  const [list, setList] = useState([]);
  const [creating, setCreating] = useState(false);
  const load = async () => { try { setList((await api.get("/b2b/customers")).data); } catch {} };
  useEffect(() => { load(); }, []);
  return (
    <div>
      <div className="flex justify-end mb-3">
        <button data-testid="b2b-new-customer" onClick={() => setCreating(true)} className="btn-brand"><Plus size={14} className="mr-1" />New wholesale customer</button>
      </div>
      <div className="card-surface overflow-x-auto">
        <table className="data-table w-full">
          <thead><tr><th>Name</th><th>Company</th><th>Phone</th><th>GSTIN</th><th className="text-right">Credit Limit</th><th className="text-right">Outstanding</th><th>Terms</th></tr></thead>
          <tbody>
            {list.map(c => (
              <tr key={c.id}>
                <td>{c.name}</td><td>{c.company || "—"}</td><td className="font-mono">{c.phone || "—"}</td>
                <td className="font-mono text-xs">{c.gstin || "—"}</td>
                <td className="text-right font-mono">{fmtINR(c.credit_limit || 0)}</td>
                <td className={`text-right font-mono ${c.outstanding > 0 ? "text-red-600 font-semibold" : ""}`}>{fmtINR(c.outstanding || 0)}</td>
                <td className="text-xs">Net {c.payment_terms_days}d</td>
              </tr>
            ))}
            {list.length === 0 && <tr><td colSpan={7} className="p-8 text-center text-slate-400">No wholesale customers yet.</td></tr>}
          </tbody>
        </table>
      </div>
      {creating && <B2BCustomerModal onClose={() => setCreating(false)} onSaved={() => { setCreating(false); load(); }} />}
    </div>
  );
}

function B2BCustomerModal({ onClose, onSaved }) {
  const [c, setC] = useState({ name: "", company: "", phone: "", email: "", gstin: "", address: "",
    credit_limit: 100000, payment_terms_days: 30, tags: [] });
  const save = async () => {
    try { await api.post("/b2b/customers", c); toast.success("Customer added"); onSaved(); }
    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
  };
  return (
    <div className="fixed inset-0 bg-black/40 z-40 flex items-center justify-center p-4">
      <div className="bg-white rounded-md w-full max-w-lg shadow-xl">
        <div className="px-5 py-3 border-b flex justify-between"><h3 className="font-semibold">New wholesale customer</h3><button onClick={onClose}><X size={18} /></button></div>
        <div className="p-5 space-y-2">
          {[["name", "Contact name *"], ["company", "Company"], ["phone", "Phone"], ["email", "Email"], ["gstin", "GSTIN"], ["address", "Address"]].map(([k, label]) => (
            <input key={k} placeholder={label} value={c[k] || ""} onChange={(e) => setC({ ...c, [k]: e.target.value })} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" />
          ))}
          <div className="grid grid-cols-2 gap-2">
            <label className="block"><div className="text-xs text-slate-500 mb-1">Credit limit ₹</div><input type="number" value={c.credit_limit} onChange={(e) => setC({ ...c, credit_limit: parseFloat(e.target.value || 0) })} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" /></label>
            <label className="block"><div className="text-xs text-slate-500 mb-1">Payment terms (days)</div><input type="number" value={c.payment_terms_days} onChange={(e) => setC({ ...c, payment_terms_days: parseInt(e.target.value || 30) })} className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm" /></label>
          </div>
        </div>
        <div className="border-t px-5 py-3 flex justify-end gap-2"><button onClick={onClose} className="px-4 py-2 border border-slate-300 rounded-md text-sm">Cancel</button><button data-testid="b2b-cust-save" onClick={save} disabled={!c.name} className="btn-brand disabled:opacity-50">Create</button></div>
      </div>
    </div>
  );
}
