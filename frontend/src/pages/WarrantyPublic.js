/* Public warranty registration page — no auth required.
   Route:  /warranty  (embed in newdru.com via iframe or link out)          */
import { useEffect, useMemo, useState, useCallback } from "react";
import axios from "axios";
import { Loader2, ShieldCheck, CheckCircle2, PackageSearch } from "lucide-react";
import { toast } from "sonner";
import NewdruLogo from "@/components/NewdruLogo";

const API = `${process.env.REACT_APP_BACKEND_URL || ""}/api`;

const SOURCES = [
  { code: "amazon", label: "Amazon" },
  { code: "flipkart", label: "Flipkart" },
  { code: "newdru.com", label: "newdru.com" },
  { code: "offline_store", label: "Offline Store" },
  { code: "other", label: "Other" },
];

export default function WarrantyPublic() {
  const initialCode = useMemo(() => {
    const p = new URLSearchParams(window.location.search);
    return p.get("sku") || p.get("code") || "";
  }, []);
  const [code, setCode] = useState(initialCode);
  const [product, setProduct] = useState(null);
  const [looking, setLooking] = useState(false);
  const [form, setForm] = useState({
    name: "", email: "", phone: "", purchase_date: "",
    purchase_source: "amazon", retailer_name: "",
  });
  const [invoice, setInvoice] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);

  const today = useMemo(() => new Date().toISOString().slice(0, 10), []);

  const doLookup = useCallback(async (arg) => {
    // Called from (a) form submit with an event, (b) useEffect with a string.
    if (arg && typeof arg === "object" && typeof arg.preventDefault === "function") {
      arg.preventDefault();
    }
    const c = (typeof arg === "string" ? arg : code).trim();
    if (!c) return;
    setLooking(true);
    setProduct(null);
    try {
      const { data } = await axios.get(`${API}/public/warranty/product-lookup`, { params: { code: c } });
      setProduct(data);
    } catch (err) {
      toast.error(err.response?.data?.detail || "Product not found. Check the SKU on your invoice.");
    } finally { setLooking(false); }
  }, [code]);

  const readFileAsDataURL = (file) => new Promise((res, rej) => {
    const r = new FileReader();
    r.onload = () => res(r.result);
    r.onerror = rej;
    r.readAsDataURL(file);
  });

  const submit = async (e) => {
    e.preventDefault();
    if (!product) { toast.error("Look up your product first"); return; }
    setSubmitting(true);
    try {
      let invoice_url = null;
      if (invoice) {
        if (invoice.size > 3 * 1024 * 1024) throw new Error("Invoice image must be under 3 MB");
        invoice_url = await readFileAsDataURL(invoice);
      }
      const payload = { product_code: product.sku, ...form, invoice_url };
      const { data } = await axios.post(`${API}/public/warranty/register`, payload);
      setResult(data);
    } catch (err) {
      toast.error(err.response?.data?.detail || err.message || "Registration failed");
    } finally { setSubmitting(false); }
  };

  useEffect(() => { if (initialCode) doLookup(initialCode); }, [initialCode, doLookup]);

  if (result) {
    return (
      <div className="min-h-screen flex items-center justify-center p-6" style={{ background: "#FDF5F4" }}>
        <div className="max-w-lg w-full bg-white rounded-2xl shadow-lg p-8 text-center">
          <div className="mx-auto w-14 h-14 rounded-full flex items-center justify-center" style={{ background: "#DCFCE7" }}>
            <CheckCircle2 size={28} className="text-emerald-600" />
          </div>
          <h1 className="mt-4 text-2xl font-bold text-slate-900">Warranty registered!</h1>
          <p className="text-slate-500 mt-1 text-sm">Save your Warranty ID for future reference.</p>
          <div className="my-6 py-3 rounded-lg text-2xl font-mono font-bold tracking-widest" style={{ background: "#FDECEA", color: "#B91C1C" }}
            data-testid="warranty-id-display">
            #{result.warranty_id}
          </div>
          <div className="text-left text-sm text-slate-700 space-y-1 border-t pt-4">
            <div><span className="text-slate-500">Product:</span> <b>{result.product_name}</b></div>
            <div><span className="text-slate-500">Valid until:</span> <b>{new Date(result.warranty_end).toDateString()}</b> ({result.warranty_months} months)</div>
          </div>
          <a href={`${API}/warranty/public/certificate/${result.warranty_id}.pdf`} target="_blank" rel="noreferrer"
             data-testid="download-certificate"
             className="mt-6 inline-flex items-center gap-2 px-5 py-2.5 rounded-lg font-semibold text-white"
             style={{ background: "#F0544A" }}>
            Download Certificate (PDF)
          </a>
          <div className="mt-4 text-xs text-slate-500">
            Coverage: manufacturing defects only. To claim, contact <a href="mailto:hello@newdru.com" className="underline">hello@newdru.com</a>.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen" style={{ background: "linear-gradient(180deg,#FDF5F4 0%,#FFFFFF 60%)" }}>
      <header className="max-w-3xl mx-auto px-6 pt-8 flex items-center justify-between">
        <NewdruLogo size="md" tagline />
        <a href="https://newdru.com" className="text-sm text-slate-500 hover:text-slate-700">← Back to newdru.com</a>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        <div className="flex items-start gap-3 mb-8">
          <div className="p-2 rounded-lg" style={{ background: "#FDECEA" }}>
            <ShieldCheck size={24} style={{ color: "#F0544A" }} />
          </div>
          <div>
            <h1 className="text-3xl font-bold text-slate-900">Register your warranty</h1>
            <p className="text-slate-600 mt-1">6-month manufacturing-defect warranty. Register within 400 days of purchase.</p>
          </div>
        </div>

        {/* Step 1: Product lookup */}
        <section className="bg-white rounded-2xl shadow-sm border p-6">
          <div className="flex items-center gap-2 mb-4">
            <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold text-white" style={{ background: "#F0544A" }}>1</span>
            <h2 className="text-lg font-semibold">Find your product</h2>
          </div>
          <form onSubmit={doLookup} className="flex gap-2">
            <input
              data-testid="warranty-sku-input"
              value={code} onChange={(e) => setCode(e.target.value)}
              placeholder="Enter SKU / barcode from your invoice (e.g. BAPNA-BLACK)"
              className="flex-1 border border-slate-300 rounded-lg px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F0544A]/40"
            />
            <button
              type="submit" disabled={looking}
              data-testid="warranty-lookup-btn"
              className="px-5 py-2.5 rounded-lg font-semibold text-white flex items-center gap-2 disabled:opacity-60"
              style={{ background: "#F0544A" }}
            >
              {looking ? <Loader2 size={16} className="animate-spin" /> : <PackageSearch size={16} />}
              Look up
            </button>
          </form>

          {product && (
            <div className="mt-4 p-4 rounded-xl flex items-center gap-4" style={{ background: "#F1F5F9" }} data-testid="product-preview">
              {product.image && <img src={product.image} alt="" className="w-16 h-16 rounded-lg object-cover" />}
              <div className="flex-1">
                <div className="font-semibold text-slate-900">{product.name}</div>
                <div className="text-xs text-slate-500">SKU: {product.sku} · {product.warranty_months}-month warranty</div>
              </div>
              <CheckCircle2 className="text-emerald-500" />
            </div>
          )}
        </section>

        {/* Step 2: Customer + purchase info */}
        {product && (
          <form onSubmit={submit} className="mt-6 bg-white rounded-2xl shadow-sm border p-6 space-y-5">
            <div className="flex items-center gap-2 mb-2">
              <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold text-white" style={{ background: "#F0544A" }}>2</span>
              <h2 className="text-lg font-semibold">Your details</h2>
            </div>

            <div className="grid md:grid-cols-2 gap-4">
              <Field label="Full name">
                <input data-testid="wf-name" required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className="input" />
              </Field>
              <Field label="Email">
                <input data-testid="wf-email" required type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className="input" />
              </Field>
              <Field label="Phone (+91…)">
                <input data-testid="wf-phone" required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className="input" placeholder="+91-98123-45678" />
              </Field>
              <Field label="Date of purchase">
                <input data-testid="wf-purchase-date" required type="date" max={today} value={form.purchase_date} onChange={(e) => setForm({ ...form, purchase_date: e.target.value })} className="input" />
              </Field>
              <Field label="Where did you buy this?">
                <select data-testid="wf-source" value={form.purchase_source} onChange={(e) => setForm({ ...form, purchase_source: e.target.value })} className="input">
                  {SOURCES.map((s) => <option key={s.code} value={s.code}>{s.label}</option>)}
                </select>
              </Field>
              <Field label="Retailer / Dealer name">
                <input data-testid="wf-retailer" value={form.retailer_name} onChange={(e) => setForm({ ...form, retailer_name: e.target.value })} className="input" placeholder="Optional" />
              </Field>
            </div>

            <Field label="Upload invoice (image or PDF, max 3 MB)">
              <input data-testid="wf-invoice" type="file" accept="image/*,application/pdf"
                     onChange={(e) => setInvoice(e.target.files?.[0] || null)}
                     className="block w-full text-sm text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-lg file:border-0 file:font-semibold file:text-white"
                     style={{}} />
              <style>{`input[type=file]::file-selector-button{background:#F0544A;color:#fff}`}</style>
            </Field>

            <div className="pt-2 flex items-center justify-between">
              <div className="text-xs text-slate-500">
                By registering you agree to Newdru's warranty terms. Manufacturing defects only.
              </div>
              <button type="submit" disabled={submitting}
                      data-testid="wf-submit"
                      className="px-6 py-3 rounded-lg font-semibold text-white flex items-center gap-2 disabled:opacity-60"
                      style={{ background: "#F0544A" }}>
                {submitting && <Loader2 size={16} className="animate-spin" />}
                Register warranty
              </button>
            </div>
          </form>
        )}
      </main>
      <style>{`.input{width:100%;border:1px solid #cbd5e1;border-radius:.5rem;padding:.625rem .75rem;font-size:.875rem;background:#fff}.input:focus{outline:none;box-shadow:0 0 0 3px rgba(240,84,74,.25);border-color:#F0544A}`}</style>
    </div>
  );
}

function Field({ label, children }) {
  return (
    <label className="block">
      <div className="text-xs font-semibold text-slate-600 uppercase tracking-wider mb-1.5">{label}</div>
      {children}
    </label>
  );
}
