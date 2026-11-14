/* Owner + Store Manager: Warranty analytics dashboard.
   Uses the /api/warranty/analytics endpoint (extended with mom_series + claim_rate). */
import { useEffect, useState, useCallback } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Legend,
} from "recharts";
import { LineChart as LineIcon, TrendingUp, TrendingDown, ShieldCheck, LifeBuoy, Package } from "lucide-react";

const CORAL = "#F0544A";
const CORAL_LIGHT = "#FDECEA";
const INK = "#0F172A";
const SOURCE_COLORS = ["#F0544A", "#F59E0B", "#10B981", "#6366F1", "#94A3B8"];

const monthLabel = (yyyymm) => {
  if (!yyyymm) return "";
  const [y, m] = yyyymm.split("-");
  const d = new Date(Number(y), Number(m) - 1, 1);
  return d.toLocaleDateString("en-IN", { month: "short", year: "2-digit" });
};

export default function WarrantyAnalytics() {
  const [data, setData] = useState(null);
  const [months, setMonths] = useState(12);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/warranty/analytics", { params: { months } });
      setData(data);
    } catch (e) {
      toast.error(e.response?.data?.detail || "Load failed");
    } finally { setLoading(false); }
  }, [months]);
  useEffect(() => { load(); }, [load]);

  if (loading && !data) return <div className="p-6 text-slate-400">Loading analytics…</div>;
  if (!data) return null;

  const trendUp = (data.mom_change_pct ?? 0) >= 0;
  const momSeries = (data.mom_series || []).map((r) => ({ ...r, label: monthLabel(r.month) }));

  return (
    <div className="p-6 space-y-6" data-testid="warranty-analytics-page">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-lg" style={{ background: CORAL_LIGHT }}>
            <LineIcon size={22} style={{ color: CORAL }} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-slate-900">Warranty Analytics</h1>
            <div className="text-sm text-slate-500">Registrations, claim rates, geography and SKU health</div>
          </div>
        </div>
        <select value={months} onChange={(e) => setMonths(Number(e.target.value))}
                data-testid="analytics-range-select"
                className="py-2 px-3 rounded-lg border border-slate-300 text-sm">
          <option value={3}>Last 3 months</option>
          <option value={6}>Last 6 months</option>
          <option value={12}>Last 12 months</option>
          <option value={24}>Last 24 months</option>
        </select>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <KPI icon={ShieldCheck} label="Total registrations" value={data.total.toLocaleString()} tint="#EDE9FE" iconColor="#6D28D9" testid="kpi-total" />
        <KPI icon={TrendingUp} label="Last 30 days" value={data.last_30_days.toLocaleString()}
             sub={<Trend up={trendUp} pct={data.mom_change_pct} />} tint="#DCFCE7" iconColor="#16A34A" testid="kpi-last30" />
        <KPI icon={ShieldCheck} label="Active warranties" value={data.active.toLocaleString()}
             sub={<span className="text-slate-500">{data.total ? `${Math.round(data.active / data.total * 100)}% of total` : ""}</span>}
             tint="#DBEAFE" iconColor="#1D4ED8" testid="kpi-active" />
        <KPI icon={LifeBuoy} label="Claims filed" value={data.claims_total.toLocaleString()}
             sub={<span className="text-slate-500">{data.claims_open} open</span>}
             tint="#FEF3C7" iconColor="#B45309" testid="kpi-claims" />
        <KPI icon={LifeBuoy} label="Claim rate"
             value={`${data.claim_rate_pct}%`}
             sub={<span className={data.claim_rate_pct > 5 ? "text-red-600" : "text-slate-500"}>industry avg ~3%</span>}
             tint={CORAL_LIGHT} iconColor={CORAL} testid="kpi-claim-rate" />
      </div>

      {/* MoM chart */}
      <section className="bg-white border rounded-2xl p-6 shadow-sm" data-testid="mom-chart">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold text-slate-900">Month-over-month</h2>
            <div className="text-xs text-slate-500">Registrations (bars) vs Claim rate % (line)</div>
          </div>
        </div>
        <div style={{ width: "100%", height: 320 }}>
          <ResponsiveContainer>
            <BarChart data={momSeries} margin={{ top: 10, right: 30, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" vertical={false} />
              <XAxis dataKey="label" tick={{ fill: "#64748B", fontSize: 12 }} />
              <YAxis yAxisId="left" tick={{ fill: "#64748B", fontSize: 12 }} allowDecimals={false} />
              <YAxis yAxisId="right" orientation="right" unit="%" tick={{ fill: "#64748B", fontSize: 12 }} />
              <Tooltip contentStyle={{ borderRadius: 8, border: "1px solid #E2E8F0" }} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar yAxisId="left" dataKey="registrations" fill={CORAL} radius={[6, 6, 0, 0]} name="Registrations" />
              <Bar yAxisId="left" dataKey="claims" fill="#F59E0B" radius={[6, 6, 0, 0]} name="Claims" />
              <Line yAxisId="right" type="monotone" dataKey="claim_rate_pct" stroke={INK} strokeWidth={2} dot={{ r: 3 }} name="Claim rate %" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      {/* By source + top SKUs */}
      <div className="grid lg:grid-cols-2 gap-4">
        <section className="bg-white border rounded-2xl p-6 shadow-sm" data-testid="by-source-chart">
          <h2 className="text-lg font-semibold text-slate-900 mb-1">Registrations by source</h2>
          <div className="text-xs text-slate-500 mb-4">Where customers bought before registering</div>
          {data.by_source.length === 0 ? (
            <EmptyChart />
          ) : (
            <div style={{ width: "100%", height: 260 }}>
              <ResponsiveContainer>
                <PieChart>
                  <Pie data={data.by_source} dataKey="count" nameKey="source" cx="50%" cy="50%" outerRadius={90} innerRadius={45} paddingAngle={2}>
                    {data.by_source.map((entry, i) => <Cell key={`src-${entry.source || i}`} fill={SOURCE_COLORS[i % SOURCE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ borderRadius: 8 }} />
                  <Legend wrapperStyle={{ fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
        </section>

        <section className="bg-white border rounded-2xl p-6 shadow-sm" data-testid="top-skus-chart">
          <h2 className="text-lg font-semibold text-slate-900 mb-1 flex items-center gap-2">
            <Package size={18} className="text-slate-500" /> Top SKUs by registrations
          </h2>
          <div className="text-xs text-slate-500 mb-4">Watch SKUs where claim-rate crosses 5%</div>
          {data.top_skus.length === 0 ? (
            <EmptyChart />
          ) : (
            <div className="space-y-2">
              {data.top_skus.map((s) => {
                const bad = s.claim_rate_pct > 5;
                return (
                  <div key={s.sku} className="flex items-center gap-3 text-sm py-1.5 border-b border-slate-100 last:border-0">
                    <div className="flex-1 min-w-0">
                      <div className="font-semibold text-slate-900 truncate">{s.name}</div>
                      <div className="text-xs text-slate-500 font-mono">{s.sku}</div>
                    </div>
                    <div className="text-right">
                      <div className="font-bold text-slate-900">{s.count}</div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-400">regs</div>
                    </div>
                    <div className="text-right w-16">
                      <div className={`font-semibold ${bad ? "text-red-600" : "text-slate-700"}`}>
                        {s.claims}
                      </div>
                      <div className="text-[10px] uppercase tracking-wider text-slate-400">claims</div>
                    </div>
                    <div className="w-14 text-right">
                      <span className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${bad ? "bg-red-50 text-red-700" : "bg-emerald-50 text-emerald-700"}`}>
                        {s.claim_rate_pct}%
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </section>
      </div>

      {/* By state */}
      <section className="bg-white border rounded-2xl p-6 shadow-sm" data-testid="by-state-chart">
        <h2 className="text-lg font-semibold text-slate-900 mb-1">Top 10 states</h2>
        <div className="text-xs text-slate-500 mb-4">Based on IP geolocation at registration time</div>
        {data.by_state.length === 0 ? (
          <div className="text-sm text-slate-400 py-8 text-center">
            No state-level data yet. In preview, ingress IPs don't resolve to a city; production traffic will populate this.
          </div>
        ) : (
          <div style={{ width: "100%", height: 260 }}>
            <ResponsiveContainer>
              <BarChart data={data.by_state} layout="vertical" margin={{ top: 5, right: 30, left: 60, bottom: 5 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#E2E8F0" horizontal={false} />
                <XAxis type="number" tick={{ fill: "#64748B", fontSize: 12 }} allowDecimals={false} />
                <YAxis type="category" dataKey="state" tick={{ fill: "#64748B", fontSize: 12 }} width={90} />
                <Tooltip contentStyle={{ borderRadius: 8 }} />
                <Bar dataKey="count" fill={CORAL} radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </section>
    </div>
  );
}

function KPI({ icon: Icon, label, value, sub, tint, iconColor, testid }) {
  return (
    <div className="bg-white border rounded-2xl p-4 shadow-sm" data-testid={testid}>
      <div className="flex items-center justify-between mb-1">
        <div className="text-xs uppercase tracking-wider text-slate-500 font-semibold">{label}</div>
        <div className="p-1.5 rounded-lg" style={{ background: tint }}>
          <Icon size={14} style={{ color: iconColor }} />
        </div>
      </div>
      <div className="text-2xl font-bold text-slate-900">{value}</div>
      {sub && <div className="text-xs mt-0.5">{sub}</div>}
    </div>
  );
}

function Trend({ up, pct }) {
  if (pct == null) return null;
  const abs = Math.abs(pct);
  const Icon = up ? TrendingUp : TrendingDown;
  const cls = up ? "text-emerald-600" : "text-red-600";
  return (
    <span className={`inline-flex items-center gap-1 ${cls}`}>
      <Icon size={12} /> {abs}% vs prev 30d
    </span>
  );
}

function EmptyChart() {
  return <div className="text-sm text-slate-400 py-10 text-center">No data yet — register a few warranties on <span className="font-mono">/warranty</span> to see this chart.</div>;
}
