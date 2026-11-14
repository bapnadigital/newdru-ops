import { useEffect, useState } from "react";
import { api, inr, canSeeCost } from "@/lib/api";
import { useAuth } from "@/contexts/AuthContext";
import { TrendingUp, Users, AlertTriangle, Receipt } from "lucide-react";

export default function Dashboard() {
  const { user } = useAuth();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try { const { data } = await api.get("/reports/dashboard"); setData(data); }
      catch (err) { console.error("dashboard load failed:", err); }
      setLoading(false);
    })();
  }, []);

  if (loading) return <div className="text-slate-500">Loading dashboard…</div>;
  if (!data) return <div>Unable to load dashboard.</div>;

  return (
    <div>
      <div className="flex flex-col md:flex-row md:items-end md:justify-between gap-2 mb-6">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500">Overview</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Good to see you, {user.name.split(" ")[0]}</h1>
        </div>
        <div className="text-sm text-slate-500">Today · {new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "short" })}</div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <Kpi icon={<Receipt size={18} />} label="Today's Sales" value={inr(data.today_sales_total)} sub={data.today_order_count + " orders"} />
        <Kpi icon={<TrendingUp size={18} />} label="Orders Today" value={data.today_order_count} sub="Store POS + online" />
        <Kpi icon={<Users size={18} />} label="New Customers" value={data.new_customers_today} sub="Captured today" />
        <Kpi icon={<AlertTriangle size={18} />} label="Low Stock" value={data.low_stock_count} sub="SKU x location alerts" accent="warn" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        <div className="newdru-kpi">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Payment split (today)</div>
          {Object.entries(data.by_method || {}).every(([, v]) => v === 0) && (
            <div className="text-sm text-slate-500">No sales yet today.</div>
          )}
          <div className="space-y-2">
            {Object.entries(data.by_method || {}).map(([m, v]) => {
              const total = Object.values(data.by_method).reduce((a, b) => a + b, 0);
              const pct = total > 0 ? (v / total) * 100 : 0;
              return (
                <div key={m}>
                  <div className="flex justify-between text-sm">
                    <span className="capitalize">{m}</span><span className="mono">{inr(v)}</span>
                  </div>
                  <div className="h-1.5 bg-slate-100 rounded-full mt-1">
                    <div className="h-full bg-indigo-700 rounded-full" style={{ width: `${pct}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        <div className="newdru-kpi lg:col-span-2">
          <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Top SKUs (today)</div>
          {(!data.top_skus || data.top_skus.length === 0) && <div className="text-sm text-slate-500">No sales data yet.</div>}
          <table className="newdru-table">
            <thead><tr><th>SKU</th><th>Name</th><th className="text-right">Units</th><th className="text-right">Revenue</th></tr></thead>
            <tbody>
              {(data.top_skus || []).map((s) => (
                <tr key={s.sku}>
                  <td className="mono">{s.sku}</td>
                  <td>{s.name}</td>
                  <td className="text-right mono">{s.qty}</td>
                  <td className="text-right mono">{inr(s.revenue)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {canSeeCost(user.role) && data.inventory_value_by_location && (
          <div className="newdru-kpi lg:col-span-3">
            <div className="text-xs uppercase tracking-widest text-slate-500 mb-3">Inventory value by location</div>
            <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3">
              {Object.entries(data.inventory_value_by_location).map(([code, v]) => (
                <div key={code} className="bg-slate-50 border border-slate-200 rounded-md p-3">
                  <div className="flex items-center justify-between">
                    <span className="chip chip-info">{code}</span>
                    <span className="text-xs text-slate-500">{v.units} units</span>
                  </div>
                  <div className="mt-2 text-lg font-semibold mono text-indigo-800">{inr(v.value)}</div>
                  <div className="text-xs text-slate-500">{v.name}</div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function Kpi({ icon, label, value, sub, accent }) {
  const accentClass = accent === "warn" ? "text-amber-600" : accent === "danger" ? "text-red-600" : accent === "ok" ? "text-emerald-600" : "text-indigo-700";
  return (
    <div className="newdru-kpi">
      <div className="flex items-center justify-between">
        <div className="text-xs uppercase tracking-widest text-slate-500">{label}</div>
        <div className={accentClass}>{icon}</div>
      </div>
      <div className={`text-2xl md:text-3xl mt-2 font-semibold ${accentClass}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}
