import { useEffect, useMemo, useRef, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import ShipModal from "@/components/ShipModal";
import { toast } from "sonner";
import { ScanBarcode, Trash2, Plus, Minus, Printer, IndianRupee, LayoutGrid, X, ImageOff } from "lucide-react";
import { v4 as uuidv4 } from "@/lib/uuid";

export default function POS() {
  const { user } = useAuth();
  const [scan, setScan] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [showSuggest, setShowSuggest] = useState(false);
  const [showBrowse, setShowBrowse] = useState(false);
  const [browseItems, setBrowseItems] = useState([]);
  const [browseQ, setBrowseQ] = useState("");
  const [browseLoading, setBrowseLoading] = useState(false);
  const [cart, setCart] = useState([]);
  const [customer, setCustomer] = useState(null);
  const [custPhone, setCustPhone] = useState("");
  const [custName, setCustName] = useState("");
  const [cartDiscount, setCartDiscount] = useState(0);
  const [discountCode, setDiscountCode] = useState("");
  const [campaignTag, setCampaignTag] = useState("");
  const [payments, setPayments] = useState([{ method: "cash", amount: 0 }]);
  const [terminalPTR, setTerminalPTR] = useState(null);
  const [terminalStatus, setTerminalStatus] = useState(null);
  const [terminalPolling, setTerminalPolling] = useState(false);
  const [pinelabsMode, setPinelabsMode] = useState("");
  const [autoBill, setAutoBill] = useState(false);
  const grandRef = useRef(0);
  const [processing, setProcessing] = useState(false);
  const [lastSale, setLastSale] = useState(null);
  const [shipSale, setShipSale] = useState(null);
  const [shipOn, setShipOn] = useState(false);
  useEffect(() => { if (!["owner", "store_manager"].includes(user?.role)) return; api.get("/shipping/config").then((r) => setShipOn(r.data.mode === "live" && r.data.configured)).catch(() => {}); }, []);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideCreds, setOverrideCreds] = useState({ email: "admin@newdru.com", password: "", reason: "" });
  const [overrideError, setOverrideError] = useState("");
  const [offlineQueue, setOfflineQueue] = useState(() => {
    try { return JSON.parse(localStorage.getItem("newdru_offline_sales") || "[]"); } catch { return []; }
  });
  const scanRef = useRef(null);
  const suggestTimerRef = useRef(null);
  const browseTimerRef = useRef(null);

  useEffect(() => { scanRef.current?.focus(); }, []);
  useEffect(() => { localStorage.setItem("newdru_offline_sales", JSON.stringify(offlineQueue)); }, [offlineQueue]);
  useEffect(() => { api.get("/pinelabs/config").then(r => setPinelabsMode(r.data.mode)).catch((err) => console.warn("pinelabs config unavailable:", err?.response?.status)); }, []);

  // Typeahead: debounced product search as user types
  useEffect(() => {
    if (suggestTimerRef.current) clearTimeout(suggestTimerRef.current);
    if (!scan || scan.length < 2) { setSuggestions([]); setShowSuggest(false); return; }
    suggestTimerRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get("/products", { params: { q: scan, limit: 8 } });
        setSuggestions(data || []);
        setShowSuggest((data || []).length > 0);
      } catch (err) { console.warn("product typeahead failed:", err); }
    }, 220);
    return () => clearTimeout(suggestTimerRef.current);
  }, [scan]);

  // Browse grid: debounced fetch when panel is open (or q changes)
  useEffect(() => {
    if (!showBrowse) return;
    if (browseTimerRef.current) clearTimeout(browseTimerRef.current);
    setBrowseLoading(true);
    browseTimerRef.current = setTimeout(async () => {
      try {
        const params = { limit: 40 };
        if (browseQ.trim()) params.q = browseQ.trim();
        const { data } = await api.get("/products", { params });
        setBrowseItems(data || []);
      } catch (err) { console.warn("product browse fetch failed:", err); }
      setBrowseLoading(false);
    }, 220);
    return () => clearTimeout(browseTimerRef.current);
  }, [showBrowse, browseQ]);

  // Poll Pine Labs terminal txn status while OPEN
  useEffect(() => {
    if (!terminalPTR || !terminalPolling) return;
    const t = setInterval(async () => {
      try {
        const { data } = await api.get(`/pinelabs/status/${terminalPTR}`);
        setTerminalStatus(data);
        if (["APPROVED", "DECLINED", "CANCELLED", "TIMEOUT"].includes(data.status)) {
          setTerminalPolling(false);
          if (data.status === "APPROVED") {
            // Auto-fill the last payment row with the approved terminal amount
            const method = data.mode === "upi" ? "upi" : "card";
            // The machine payment replaces any auto-filled cash amount; only a genuine
            // shortfall (split payment) is left for cash.
            const grand = grandRef.current;
            const remaining = Math.round((grand - Number(data.amount || 0)) * 100) / 100;
            setPayments([
              { method, amount: data.amount, ptr_id: data.ptr_id, rrn: data.rrn,
                approval_code: data.approval_code, masked_pan: data.masked_pan, acquirer: data.acquirer },
              ...(remaining > 0.05 ? [{ method: "cash", amount: remaining }] : []),
            ]);
            toast.success(`Terminal approved · ${data.masked_pan || data.acquirer || ""} · generating bill…`);
            setAutoBill(true);
          } else {
            toast.error(`Terminal ${data.status.toLowerCase()}`);
          }
        }
      } catch (err) { console.warn("pinelabs poll failed:", err?.response?.status); }
    }, 2000);
    return () => clearInterval(t);
  }, [terminalPTR, terminalPolling]);

  useEffect(() => {
    const t = setInterval(async () => {
      if (offlineQueue.length === 0 || !navigator.onLine) return;
      for (const s of [...offlineQueue]) {
        try {
          await api.post("/pos/sales", s);
          setOfflineQueue((q) => q.filter((x) => x.client_ref !== s.client_ref));
        } catch (err) { console.warn("offline sale sync failed, will retry:", err?.response?.status); break; }
      }
    }, 30000);
    return () => clearInterval(t);
  }, [offlineQueue]);

  const doScan = async (e) => {
    e.preventDefault();
    if (!scan) return;
    // 1st try: exact barcode / SKU / product-id lookup
    try {
      const { data } = await api.get("/products/lookup", { params: { code: scan } });
      addToCart(data);
      setScan(""); setSuggestions([]); setShowSuggest(false);
      scanRef.current?.focus();
      return;
    } catch (err) { /* fall through to typeahead */ }
    // 2nd try: fall back to the first typeahead match (typed-name flow)
    if (suggestions.length > 0) {
      pickSuggestion(suggestions[0]);
      return;
    }
    toast.error("No product matches: " + scan);
  };

  const pickSuggestion = (product) => {
    addToCart(product);
    setScan(""); setSuggestions([]); setShowSuggest(false);
    scanRef.current?.focus();
  };

  const addToCart = (product, qty = 1) => {
    const idx = cart.findIndex((c) => c.product_id === product.id);
    if (idx >= 0) {
      const next = [...cart]; next[idx].quantity += qty; setCart(next);
    } else {
      setCart([...cart, {
        product_id: product.id, sku: product.sku, name: product.name,
        hsn: product.hsn, quantity: qty,
        unit_price: product.sell_price ?? product.mrp ?? 0,
        gst_rate: product.gst_rate ?? 18, discount: 0,
        cogs_per_unit: product.cogs_per_unit ?? 0,
      }]);
    }
  };

  const updateLine = (idx, patch) => { const next = [...cart]; next[idx] = { ...next[idx], ...patch }; setCart(next); };
  const removeLine = (idx) => setCart(cart.filter((_, i) => i !== idx));

  const lookupCustomer = async () => {
    if (!custPhone) return;
    if (custPhone.trim().length < 3) { toast.info("Type at least 3 digits of the phone number"); return; }
    try {
      const { data } = await api.get("/customers", { params: { q: custPhone.trim(), limit: 10 } });
      const rows = Array.isArray(data) ? data : (data?.rows || []);
      if (rows.length > 0) { setCustomer(rows[0]); setCustName(rows[0].name); toast.success("Customer found"); }
      else toast.info("New customer — will be created on checkout");
    } catch (err) { console.error("customer lookup failed:", err); toast.error("Customer lookup failed"); }
  };

  const totals = useMemo(() => {
    let subEx = 0, gstTotal = 0;
    const breakup = {};
    for (const l of cart) {
      const gross = Math.max(0, l.quantity * l.unit_price - l.discount);
      const g = l.gst_rate / 100;
      const ex = gross / (1 + g);
      const gst = gross - ex;
      subEx += ex; gstTotal += gst;
      const k = String(l.gst_rate.toFixed(2));
      breakup[k] = breakup[k] || { taxable: 0, tax: 0 };
      breakup[k].taxable += ex; breakup[k].tax += gst;
    }
    const totalGross = subEx + gstTotal;
    const disc = Math.min(cartDiscount || 0, totalGross);
    const grand = totalGross - disc;
    return { subEx, gstTotal, grand, disc, breakup };
  }, [cart, cartDiscount]);

  // Keep payments summed = grand total
  useEffect(() => {
    if (payments.length === 1) {
      setPayments([{ ...payments[0], amount: Math.round(totals.grand * 100) / 100 }]);
    }
  }, [totals.grand]); // eslint-disable-line

  const addPayment = () => setPayments([...payments, { method: "cash", amount: 0 }]);
  const removePayment = (i) => setPayments(payments.filter((_, x) => x !== i));
  const totalPaid = payments.reduce((s, p) => s + Number(p.amount || 0), 0);

  const checkout = async () => {
    if (cart.length === 0) return toast.error("Cart is empty");
    if (Math.abs(totalPaid - totals.grand) > 0.05) return toast.error("Payment total must match grand total exactly");

    // Owner can just push through; store users get the override modal.
    if (belowCogsLines.length > 0 && user.role !== "owner") {
      setOverrideOpen(true);
      return;
    }

    setProcessing(true);
    try {
      const data = await submitSale();
      try {
        if (data.customer_id) {
          const cust = await api.get(`/customers/${data.customer_id}`).catch((err) => { console.warn("post-sale customer fetch failed:", err); return null; });
          if (cust?.data?.customer?.phone) {
            await api.post("/messaging/send-receipt", { sale_id: data.id, channel: "whatsapp" }).catch((err) => console.warn("receipt WhatsApp failed:", err));
          }
        }
      } catch (err) { console.warn("post-sale hooks failed:", err); }
    } catch (e) {
      if (!navigator.onLine || e.message?.includes("Network")) {
        setOfflineQueue([...offlineQueue, {
          items: cart, customer_id: customer?.id || null,
          customer: !customer && (custName || custPhone) ? { name: custName || "Walk-in", phone: custPhone || null, channel: "store", tags: [] } : null,
          cart_discount: cartDiscount, payments: payments.filter((p) => p.amount > 0),
          client_ref: uuidv4(),
          campaign_tag: campaignTag.trim() || null,
          discount_code: discountCode.trim() || null,
        }]);
        toast.warning("Offline — sale queued for sync");
        setCart([]); setCartDiscount(0); setCustomer(null); setCustName(""); setCustPhone("");
        setDiscountCode(""); setCampaignTag("");
      } else if (e.response?.status === 403 && e.response.data?.detail?.code === "BELOW_COGS_BLOCKED") {
        setOverrideOpen(true);
      } else {
        toast.error(formatApiError(e.response?.data?.detail));
      }
    }
    setProcessing(false);
  };

  // When the Pine Labs terminal approves and the payments now cover the bill,
  // complete the sale automatically: GST invoice + store stock goes down.
  grandRef.current = totals.grand;

  useEffect(() => {
    if (!autoBill) return;
    setAutoBill(false);
    const terminalPaid = payments.filter((p) => p.ptr_id).reduce((a, p) => a + Number(p.amount || 0), 0);
    if (Math.abs(terminalPaid - totals.grand) <= 0.05 && cart.length > 0) checkout();
    else toast.info("Terminal paid part of the bill — collect the rest in cash, then press Complete");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoBill, payments]);

  const canDiscount = ["owner", "admin", "store_manager"].includes(user.role);

  // Which lines are currently priced below their COGS?
  const belowCogsLines = useMemo(() => {
    return cart
      .map((l) => {
        const cogs = Number(l.cogs_per_unit || 0);
        if (cogs <= 0) return null;
        const qty = Math.max(1, Number(l.quantity || 1));
        const effective = (Number(l.unit_price) * qty - Number(l.discount || 0)) / qty;
        if (effective < cogs - 0.005) {
          return { sku: l.sku, name: l.name, cogs, effective: Math.round(effective * 100) / 100, quantity: qty };
        }
        return null;
      })
      .filter(Boolean);
  }, [cart]);

  const submitSale = async (override) => {
    const payload = {
      items: cart,
      customer_id: customer?.id || null,
      customer: !customer && (custName || custPhone) ? { name: custName || "Walk-in", phone: custPhone || null, channel: "store", tags: [] } : null,
      cart_discount: cartDiscount,
      payments: payments.filter((p) => p.amount > 0),
      client_ref: uuidv4(),
      campaign_tag: campaignTag.trim() || null,
      discount_code: discountCode.trim() || null,
      ...(override ? {
        admin_override_email: override.email,
        admin_override_password: override.password,
        admin_override_reason: override.reason || null,
      } : {}),
    };
    const { data } = await api.post("/pos/sales", payload);
    toast.success("Sale " + data.invoice_no + " completed");
    setLastSale(data);
    setCart([]); setCartDiscount(0); setCustomer(null); setCustName(""); setCustPhone("");
    setDiscountCode(""); setCampaignTag("");
    setPayments([{ method: "cash", amount: 0 }]);
    setTerminalPTR(null); setTerminalStatus(null); setTerminalPolling(false);
    setOverrideOpen(false); setOverrideCreds({ email: "admin@newdru.com", password: "", reason: "" });
    return data;
  };

  const submitOverride = async () => {
    setOverrideError("");
    if (!overrideCreds.password) { setOverrideError("Password required"); return; }
    setProcessing(true);
    try {
      await submitSale(overrideCreds);
    } catch (e) {
      const detail = e.response?.data?.detail;
      setOverrideError(typeof detail === "string" ? detail : formatApiError(detail));
    }
    setProcessing(false);
  };

  return (
    <div>
      <div className="flex flex-col lg:flex-row gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-3">
            <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Point of Sale</h1>
            <div className="text-xs text-slate-500 flex items-center gap-3">
              <span className={`chip ${navigator.onLine ? "chip-ok" : "chip-danger"}`}>{navigator.onLine ? "Online" : "Offline"}</span>
              {offlineQueue.length > 0 && <span className="chip chip-warn">{offlineQueue.length} queued</span>}
            </div>
          </div>

          <form onSubmit={doScan} className="flex gap-2 mb-3 relative">
            <div className="flex-1 relative">
              <ScanBarcode size={18} className="absolute left-3 top-2.5 text-slate-400" />
              <input data-testid="pos-scan-input" ref={scanRef} autoFocus value={scan}
                     onChange={(e) => setScan(e.target.value)}
                     onFocus={() => scan.length >= 2 && setShowSuggest(suggestions.length > 0)}
                     onBlur={() => setTimeout(() => setShowSuggest(false), 150)}
                     placeholder="Scan barcode or type product name / SKU…"
                     className="w-full pl-10 pr-3 py-2.5 border border-slate-300 rounded-md text-base" />
              {showSuggest && suggestions.length > 0 && (
                <div data-testid="pos-suggest-dropdown" className="absolute left-0 right-0 z-30 mt-1 bg-white border border-slate-200 rounded-md shadow-lg max-h-80 overflow-y-auto scroll-thin">
                  {suggestions.map((p) => (
                    <button
                      type="button"
                      key={p.id}
                      data-testid={`pos-suggest-${p.sku}`}
                      onMouseDown={(e) => { e.preventDefault(); pickSuggestion(p); }}
                      className="w-full flex items-center gap-3 text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-100 last:border-b-0"
                    >
                      <ProductThumb p={p} size={40} />
                      <div className="flex-1 min-w-0">
                        <div className="text-sm font-semibold truncate">{p.name}</div>
                        <div className="text-xs text-slate-500 mono truncate">{p.sku}</div>
                      </div>
                      <div className="text-sm mono font-semibold text-slate-700 whitespace-nowrap">
                        {inr(p.sell_price ?? p.mrp ?? 0)}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            <button data-testid="pos-scan-btn" className="px-4 py-2.5 bg-[hsl(234_61%_25%)] text-white rounded-md">Add</button>
            <button type="button" data-testid="pos-browse-btn" onClick={() => setShowBrowse((v) => !v)}
                    className={`px-3 py-2.5 rounded-md border text-sm flex items-center gap-1 ${
                      showBrowse ? "bg-slate-900 text-white border-slate-900" : "border-slate-300 hover:bg-slate-50"
                    }`}>
              <LayoutGrid size={16} /> Browse
            </button>
          </form>

          {showBrowse && (
            <div data-testid="pos-browse-panel" className="bg-white border border-slate-200 rounded-md p-3 mb-3">
              <div className="flex items-center gap-2 mb-3">
                <input
                  data-testid="pos-browse-search"
                  placeholder="Filter tiles by name / SKU / brand…"
                  value={browseQ}
                  onChange={(e) => setBrowseQ(e.target.value)}
                  className="flex-1 px-3 py-1.5 border border-slate-300 rounded-md text-sm"
                />
                <button onClick={() => setShowBrowse(false)} className="p-1.5 hover:bg-slate-100 rounded" title="Close">
                  <X size={16} />
                </button>
              </div>
              {browseLoading && <div className="text-xs text-slate-400 p-3">Loading…</div>}
              {!browseLoading && browseItems.length === 0 && (
                <div className="text-sm text-slate-500 p-6 text-center">No products match.</div>
              )}
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-5 gap-2 max-h-[380px] overflow-y-auto scroll-thin">
                {browseItems.map((p) => (
                  <button
                    key={p.id}
                    data-testid={`pos-tile-${p.sku}`}
                    onClick={() => { addToCart(p); toast.success(`Added ${p.name}`); }}
                    className="group text-left border border-slate-200 rounded-md p-2 hover:border-indigo-400 hover:shadow-sm transition bg-white"
                  >
                    <ProductThumb p={p} size={90} full />
                    <div className="mt-1.5 text-xs font-semibold leading-tight line-clamp-2 min-h-[28px]">
                      {p.name}
                    </div>
                    <div className="mt-0.5 flex items-center justify-between">
                      <span className="text-[10px] mono text-slate-400 truncate max-w-[70%]">{p.sku}</span>
                      <span className="text-xs mono font-semibold text-slate-800">
                        {inr(p.sell_price ?? p.mrp ?? 0)}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="bg-white border border-slate-200 rounded-md overflow-hidden">
            <div className="overflow-x-auto scroll-thin">
              <table className="newdru-table">
                <thead><tr><th>SKU</th><th>Item</th><th className="text-center">Qty</th><th className="text-right">Rate</th><th className="text-right">Disc</th><th className="text-right">GST%</th><th className="text-right">Amount</th><th></th></tr></thead>
                <tbody>
                  {cart.map((l, i) => {
                    const amt = Math.max(0, l.quantity * l.unit_price - l.discount);
                    return (
                      <tr key={l.product_id || `line-${i}`}>
                        <td className="mono">{l.sku}</td>
                        <td>{l.name}</td>
                        <td>
                          <div className="flex items-center justify-center gap-1">
                            <button className="p-1 hover:bg-slate-100 rounded" onClick={() => updateLine(i, { quantity: Math.max(1, l.quantity - 1) })}><Minus size={12} /></button>
                            <input data-testid={`cart-qty-${i}`} type="number" value={l.quantity} onChange={(e) => updateLine(i, { quantity: parseInt(e.target.value || 1) })} className="w-14 text-center border border-slate-300 rounded" />
                            <button className="p-1 hover:bg-slate-100 rounded" onClick={() => updateLine(i, { quantity: l.quantity + 1 })}><Plus size={12} /></button>
                          </div>
                        </td>
                        <td className="text-right mono">{inr(l.unit_price)}</td>
                        <td className="text-right">
                          <input type="number" value={l.discount} disabled={!canDiscount}
                                 onChange={(e) => updateLine(i, { discount: parseFloat(e.target.value || 0) })}
                                 className="w-16 text-right border border-slate-300 rounded px-1 disabled:opacity-50" />
                        </td>
                        <td className="text-right mono">{l.gst_rate}%</td>
                        <td className="text-right mono font-semibold">{inr(amt)}</td>
                        <td><button onClick={() => removeLine(i)} className="p-1 hover:bg-red-50 rounded text-red-600"><Trash2 size={14} /></button></td>
                      </tr>
                    );
                  })}
                  {cart.length === 0 && <tr><td colSpan={8} className="p-8 text-center text-slate-400">Scan or search for a product to begin.</td></tr>}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <div className="w-full lg:w-96 flex-shrink-0 space-y-3">
          <div className="bg-white border border-slate-200 rounded-md p-4">
            <div className="text-xs uppercase tracking-widest text-slate-500 mb-2">Customer</div>
            <div className="flex gap-2 mb-2">
              <input data-testid="pos-cust-phone" placeholder="Phone…" value={custPhone} onChange={(e) => setCustPhone(e.target.value)} className="flex-1 px-2 py-1.5 border border-slate-300 rounded-md text-sm" />
              <button onClick={lookupCustomer} className="px-3 py-1.5 border border-slate-300 rounded-md text-sm hover:bg-slate-50">Find</button>
            </div>
            <input placeholder="Name" value={custName} onChange={(e) => setCustName(e.target.value)} className="w-full px-2 py-1.5 border border-slate-300 rounded-md text-sm" />
            {customer && <div className="mt-2 text-xs text-slate-500">Repeat customer · {customer.order_count} past orders · Spent {inr(customer.total_spend)}</div>}
          </div>

          <div className="bg-white border border-slate-200 rounded-md p-4">
            <Row label="Subtotal (ex-GST)" value={inr(totals.subEx)} />
            <Row label="Total GST" value={inr(totals.gstTotal)} />
            {Object.entries(totals.breakup).map(([k, v]) => (
              <div key={k} className="flex justify-between text-xs text-slate-500"><span>@ {k}%</span><span className="mono">{inr(v.tax)}</span></div>
            ))}
            <div className="flex justify-between items-center mt-2">
              <span className="text-sm text-slate-600">Cart Discount</span>
              <input data-testid="pos-cart-disc" type="number" value={cartDiscount} disabled={!canDiscount}
                     onChange={(e) => setCartDiscount(parseFloat(e.target.value || 0))}
                     className="w-24 text-right border border-slate-300 rounded px-2 py-1 text-sm disabled:opacity-50" />
            </div>
            <div className="flex justify-between items-center mt-2">
              <span className="text-sm text-slate-600">Coupon code</span>
              <input data-testid="pos-discount-code" type="text" value={discountCode} disabled={!canDiscount}
                     onChange={(e) => setDiscountCode(e.target.value.toUpperCase())}
                     placeholder="e.g. DIWALI25"
                     className="w-32 text-right border border-slate-300 rounded px-2 py-1 text-sm font-mono uppercase disabled:opacity-50" />
            </div>
            <div className="flex justify-between items-center mt-2">
              <span className="text-sm text-slate-600">How did you hear?</span>
              <input data-testid="pos-campaign-tag" type="text" value={campaignTag}
                     onChange={(e) => setCampaignTag(e.target.value)}
                     placeholder="e.g. WhatsApp, Instagram"
                     className="w-40 text-right border border-slate-300 rounded px-2 py-1 text-sm" />
            </div>
            <div className="flex justify-between items-center mt-3 pt-3 border-t">
              <span className="font-semibold">Grand Total</span>
              <span className="text-2xl font-semibold mono text-indigo-800">{inr(totals.grand)}</span>
            </div>
          </div>

          <div className="bg-white border border-slate-200 rounded-md p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="text-xs uppercase tracking-widest text-slate-500">Payments</div>
              <button onClick={addPayment} className="text-xs text-indigo-700 flex items-center gap-1"><Plus size={12} />Split</button>
            </div>
            {payments.map((p, i) => (
              <div key={`pay-${p.method}-${i}`} className="flex gap-1 mb-1">
                <select value={p.method} onChange={(e) => { const n = [...payments]; n[i].method = e.target.value; setPayments(n); }} className="px-1 py-1.5 border border-slate-300 rounded-md text-sm">
                  <option value="cash">Cash</option>
                  <option value="card">Card (Pine Labs stub)</option>
                  <option value="upi">UPI (stub)</option>
                </select>
                <input data-testid={`pos-pay-amt-${i}`} type="number" value={p.amount}
                       onChange={(e) => { const n = [...payments]; n[i].amount = parseFloat(e.target.value || 0); setPayments(n); }}
                       className="flex-1 px-2 py-1.5 border border-slate-300 rounded-md text-sm text-right" />
                {payments.length > 1 && <button onClick={() => removePayment(i)} className="p-1.5 text-red-600 hover:bg-red-50 rounded"><Trash2 size={12} /></button>}
              </div>
            ))}
            <div className="flex justify-between text-sm mt-2 pt-2 border-t">
              <span>Paid</span><span className="mono font-semibold">{inr(totalPaid)}</span>
            </div>
            {Math.abs(totalPaid - totals.grand) > 0.05 && (
              <div className="text-xs text-red-600 mt-1">Payment total must equal grand total ({inr(totals.grand)}).</div>
            )}
          </div>

          <button data-testid="pos-checkout-btn" onClick={checkout} disabled={processing || cart.length === 0}
                  className="w-full bg-amber-500 hover:bg-amber-600 text-white py-3 rounded-md font-semibold disabled:opacity-50 flex items-center justify-center gap-2">
            <IndianRupee size={18} /> {processing ? "Processing…" : "Complete Sale"}
          </button>

          {/* Pay on terminal (Pine Labs) */}
          {pinelabsMode && pinelabsMode !== "disabled" && totals.grand > 0 && cart.length > 0 && (
            <div className="card-surface p-3 mt-2">
              <div className="flex justify-between items-center mb-2">
                <div className="text-xs uppercase tracking-widest text-slate-500">Pine Labs terminal</div>
                <span className="chip chip-info text-[10px]">{pinelabsMode}</span>
              </div>
              {!terminalPTR && (
                <div className="flex gap-2">
                  <button data-testid="pos-pay-card" onClick={async () => {
                    try { const { data } = await api.post("/pinelabs/pay", { amount: totals.grand, mode: "card" });
                      setTerminalPTR(data.ptr_id); setTerminalStatus({ status: "OPEN" }); setTerminalPolling(true); }
                    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
                  }} className="flex-1 px-2 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50">Card</button>
                  <button data-testid="pos-pay-upi" onClick={async () => {
                    try { const { data } = await api.post("/pinelabs/pay", { amount: totals.grand, mode: "upi" });
                      setTerminalPTR(data.ptr_id); setTerminalStatus({ status: "OPEN" }); setTerminalPolling(true); }
                    catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
                  }} className="flex-1 px-2 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50">UPI</button>
                </div>
              )}
              {terminalPTR && terminalStatus && (
                <div className="text-xs space-y-1">
                  <div className="flex justify-between"><span>PTR</span><span className="font-mono">{terminalPTR}</span></div>
                  <div className="flex justify-between"><span>Status</span>
                    <span className={`chip ${terminalStatus.status === "APPROVED" ? "chip-ok" : terminalStatus.status === "OPEN" ? "chip-warn" : "chip-danger"}`}>{terminalStatus.status}</span></div>
                  {terminalStatus.masked_pan && <div className="flex justify-between"><span>Card</span><span className="font-mono">{terminalStatus.masked_pan}</span></div>}
                  {terminalStatus.rrn && <div className="flex justify-between"><span>RRN</span><span className="font-mono">{terminalStatus.rrn}</span></div>}
                  {terminalStatus.status === "OPEN" && (
                    <div className="flex gap-2 pt-1">
                      <button onClick={async () => {
                        await api.post(`/pinelabs/cancel/${terminalPTR}`); setTerminalPolling(false); setTerminalPTR(null); setTerminalStatus(null);
                      }} className="flex-1 px-2 py-1 border border-red-300 text-red-700 rounded">Cancel</button>
                      {pinelabsMode === "simulator" && user.role === "owner" && (
                        <button data-testid="pos-sim-approve" onClick={async () => {
                          await api.post(`/pinelabs/simulate/${terminalPTR}/approve`, { outcome: "approved" });
                        }} className="flex-1 px-2 py-1 border border-emerald-300 text-emerald-700 rounded">Simulate ✓</button>
                      )}
                    </div>
                  )}
                  {["APPROVED", "DECLINED", "CANCELLED", "TIMEOUT"].includes(terminalStatus.status) && (
                    <button onClick={() => { setTerminalPTR(null); setTerminalStatus(null); }} className="w-full mt-1 px-2 py-1 border border-slate-300 rounded">Clear</button>
                  )}
                </div>
              )}
            </div>
          )}

          {lastSale && (
            <div className="bg-emerald-50 border border-emerald-200 rounded-md p-3">
              <div className="text-sm text-emerald-900">Sale complete · <span className="mono font-semibold">{lastSale.invoice_no}</span></div>
              <div className="text-xs text-emerald-700 mt-1">Total: {inr(lastSale.total)}</div>
              {shipOn && ["owner", "store_manager"].includes(user.role) && !lastSale.shipment && (
                <button data-testid="pos-home-delivery" onClick={() => setShipSale(lastSale)} className="mt-2 text-xs border border-emerald-300 rounded px-2 py-1 bg-white">Home delivery (Shiprocket)</button>
              )}
              {lastSale.shipment?.awb && <div className="text-xs text-emerald-800 mt-1">Shipped · AWB {lastSale.shipment.awb}</div>}
            </div>
          )}
          {shipSale && <ShipModal kind="sale" refId={shipSale.id} refNo={shipSale.invoice_no}
                                  defaults={{ name: shipSale.customer_name || "", phone: custPhone || "" }}
                                  onClose={() => setShipSale(null)}
                                  onDone={(d) => { setLastSale({ ...shipSale, shipment: { awb: d.awb } }); setShipSale(null); }} />}
        </div>
      </div>

      {/* ---------- Below-COGS warning banner ---------- */}
      {belowCogsLines.length > 0 && (
        <div data-testid="pos-below-cogs-warning" className="mt-3 bg-rose-50 border border-rose-200 rounded-md p-3">
          <div className="text-sm font-semibold text-rose-900">⚠ {belowCogsLines.length} line(s) priced below COGS — admin permission required</div>
          <ul className="mt-1 text-xs text-rose-700 space-y-0.5">
            {belowCogsLines.map((l) => (
              <li key={l.sku}>
                <span className="mono">{l.sku}</span> — Price ₹{l.effective} is below COGS ₹{l.cogs}
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* ---------- Admin override modal ---------- */}
      {overrideOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-2xl w-full max-w-md">
            <div className="px-5 py-3 border-b flex items-center justify-between">
              <h3 className="font-semibold text-lg">Admin approval required</h3>
              <button onClick={() => setOverrideOpen(false)} className="p-1 hover:bg-slate-100 rounded">✕</button>
            </div>
            <div className="p-5 space-y-3">
              <div className="bg-rose-50 border border-rose-200 rounded-md p-3 text-xs text-rose-900">
                {belowCogsLines.map((l) => (
                  <div key={l.sku}>Price ₹{l.effective} on <b>{l.sku}</b> is below COGS ₹{l.cogs}.</div>
                ))}
              </div>
              <label className="block">
                <div className="text-xs text-slate-600 mb-1 font-medium">Admin email</div>
                <input data-testid="override-email" type="email" value={overrideCreds.email}
                       onChange={(e) => setOverrideCreds({ ...overrideCreds, email: e.target.value })}
                       className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md" />
              </label>
              <label className="block">
                <div className="text-xs text-slate-600 mb-1 font-medium">Admin password</div>
                <input data-testid="override-password" type="password" value={overrideCreds.password}
                       onChange={(e) => setOverrideCreds({ ...overrideCreds, password: e.target.value })}
                       autoFocus
                       className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md" />
              </label>
              <label className="block">
                <div className="text-xs text-slate-600 mb-1 font-medium">Reason (recorded on audit log)</div>
                <input data-testid="override-reason" type="text" value={overrideCreds.reason}
                       onChange={(e) => setOverrideCreds({ ...overrideCreds, reason: e.target.value })}
                       placeholder="Clearance / manager approval / …"
                       className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md" />
              </label>
              {overrideError && <div className="text-xs text-rose-700">{overrideError}</div>}
            </div>
            <div className="border-t px-5 py-3 flex justify-end gap-2">
              <button onClick={() => setOverrideOpen(false)} className="px-4 py-2 border border-slate-300 rounded-md text-sm">Cancel</button>
              <button data-testid="override-confirm" onClick={submitOverride} disabled={processing}
                      className="px-4 py-2 bg-rose-600 hover:bg-rose-700 text-white rounded-md text-sm font-semibold disabled:opacity-60">
                {processing ? "Verifying…" : "Approve & complete sale"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Row({ label, value }) {
  return <div className="flex justify-between text-sm"><span className="text-slate-600">{label}</span><span className="mono">{value}</span></div>;
}

function ProductThumb({ p, size = 40, full = false }) {
  const img = Array.isArray(p?.images) && p.images.length > 0 ? p.images[0] : null;
  const initials = (p?.name || p?.sku || "?").split(/[\s-]+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
  const style = full
    ? { width: "100%", aspectRatio: "1 / 1" }
    : { width: size, height: size, minWidth: size };
  if (img) {
    return (
      <img
        src={img}
        alt={p?.name || p?.sku}
        style={style}
        className="rounded-md object-cover border border-slate-200 bg-slate-50"
        onError={(e) => { e.currentTarget.style.display = "none"; e.currentTarget.nextSibling.style.display = "flex"; }}
      />
    );
  }
  return (
    <div
      style={style}
      className="rounded-md bg-gradient-to-br from-slate-100 to-slate-200 border border-slate-200 flex flex-col items-center justify-center text-slate-500"
    >
      <ImageOff size={size < 60 ? 14 : 20} className="opacity-40" />
      <span className={`${size < 60 ? "text-[9px]" : "text-[11px]"} font-semibold mt-0.5`}>{initials}</span>
    </div>
  );
}
