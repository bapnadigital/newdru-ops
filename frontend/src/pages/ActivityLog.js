import { useEffect, useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

const AREAS = [
  ["", "Everything"],
  ["export", "Data downloads"],
  ["sale", "Sales & returns"],
  ["inventory", "Stock changes"],
  ["transfer", "Transfers"],
  ["product", "Products & prices"],
  ["user", "Staff accounts"],
  ["login", "Sign-ins"],
  ["customer", "Customers"],
  ["b2b", "Wholesale"],
];

// What happened, in plain words, for the most important actions.
const LABEL = {
  "export.customers": "Downloaded the customer list",
  "export.sales": "Downloaded sales",
  "export.inventory": "Downloaded stock",
  "export.products": "Downloaded products",
  "export.receivables": "Downloaded wholesale dues",
  "export.warranty": "Downloaded warranty registrations",
  "export.credit_notes": "Downloaded credit notes",
  "sale.create": "Made a bill",
  "sale.return": "Did a return / refund",
  "sale.below_cogs_override": "Sold below cost (approved)",
  "inventory.adjust": "Changed stock by hand",
  "inventory.count": "Stock count",
  "inventory.receive": "Goods in",
  "inventory.count_approve": "Approved a stock count",
  "cash.close": "Closed the day (cash-up)",
  "inventory.count_reject": "Rejected a stock count",
  "user.password_change": "Changed own password",
  "product.update": "Edited a product",
  "product.delete": "Deleted a product",
  "user.create": "Added a staff account",
  "user.update": "Changed a staff account",
  "user.delete": "Deleted a staff account",
  login: "Signed in",
  logout: "Signed out",
};

const short = (d) => {
  if (!d) return "";
  const parts = [];
  for (const k of ["invoice_no", "credit_note_no", "total", "refund", "reason", "delta", "location", "sku", "role", "email", "method", "approved_by"]) {
    if (d[k] !== undefined && d[k] !== null && d[k] !== "") parts.push(`${k.replace("_", " ")}: ${d[k]}`);
  }
  if (d.params && Object.keys(d.params).length) parts.push(`filters: ${JSON.stringify(d.params)}`);
  if (d.ip) parts.push(`IP ${d.ip}`);
  if (!parts.length) {
    const rest = Object.fromEntries(Object.entries(d).filter(([k, v]) => !["params", "ip"].includes(k) && v !== null && v !== undefined));
    if (!Object.keys(rest).length) return "";
    const s = JSON.stringify(rest); return s.length > 140 ? s.slice(0, 140) + "…" : s;
  }
  return parts.join(" · ");
};

export default function ActivityLog() {
  const [area, setArea] = useState("");
  const [who, setWho] = useState("");
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/reports/audit", { params: { area: area || undefined, user_name: who || undefined, limit: 300 } });
      setRows(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setLoading(false);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load(); }, [area]);

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-brand text-slate-900">Activity Log</h1>
        <p className="text-sm text-slate-500">Who did what, and when. Nobody can edit or delete these entries. Check "Data downloads" now and then: it shows anyone who pulled customer or sales lists.</p>
      </div>
      <div className="flex flex-wrap gap-2 mb-4">
        <select value={area} onChange={(e) => setArea(e.target.value)} data-testid="activity-area"
                className="border border-slate-300 rounded-md px-2 py-2 text-sm">
          {AREAS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </select>
        <form onSubmit={(e) => { e.preventDefault(); load(); }} className="flex gap-2">
          <input value={who} onChange={(e) => setWho(e.target.value)} placeholder="Staff name"
                 className="border border-slate-300 rounded-md px-3 py-2 text-sm" />
          <button className="btn-outline">Filter</button>
        </form>
      </div>
      <div className="bg-white border border-slate-200 rounded-xl overflow-x-auto">
        <table className="w-full text-sm">
          <thead><tr className="text-xs uppercase text-slate-500 text-left border-b border-slate-200">
            <th className="p-3">When</th><th className="p-3">Who</th><th className="p-3">What</th><th className="p-3">Details</th>
          </tr></thead>
          <tbody>
            {loading && <tr><td className="p-3 text-slate-500" colSpan={4}>Loading…</td></tr>}
            {!loading && !rows.length && <tr><td className="p-3 text-slate-500" colSpan={4}>Nothing here yet.</td></tr>}
            {rows.map((r) => (
              <tr key={r.id} className={`border-t border-slate-100 ${r.action?.startsWith("export.") ? "bg-amber-50" : ""}`}>
                <td className="p-3 whitespace-nowrap text-slate-600">{new Date(r.created_at).toLocaleString("en-IN")}</td>
                <td className="p-3 whitespace-nowrap">{r.user_name || "System"}</td>
                <td className="p-3">{LABEL[r.action] || r.action}</td>
                <td className="p-3 text-xs text-slate-500 break-all">{short(r.details)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
