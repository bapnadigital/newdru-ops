import { useEffect, useState } from "react";
import { api, inr, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import { IndianRupee, Coins, CreditCard, Smartphone, Receipt, TrendingUp } from "lucide-react";

export default function Cash() {
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get("/pos/shift/report");
      setReport(data);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
    setLoading(false);
  };
  useEffect(() => { load(); }, []);

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <div className="text-xs uppercase tracking-widest text-slate-500">My Till</div>
          <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Cash &amp; Shift Summary</h1>
          <p className="text-slate-500 text-sm mt-1">
            Your sales, payments received, and cash-in-drawer for the current shift.
          </p>
        </div>
        <button
          data-testid="cash-refresh"
          onClick={load}
          className="px-3 py-2 text-sm border border-slate-300 rounded-md hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>

      {loading && <SkeletonGrid />}

      {!loading && report && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <StatTile
              icon={<Receipt size={16} />}
              label="Orders in shift"
              value={report.order_count ?? 0}
              testid="cash-orders"
            />
            <StatTile
              icon={<TrendingUp size={16} />}
              label="Gross sales"
              value={inr(report.total ?? 0)}
              tone="brand"
              testid="cash-total"
            />
            <StatTile
              icon={<Coins size={16} />}
              label="Cash-in-drawer"
              value={inr(report.cash_in_drawer ?? report.by_method?.cash ?? 0)}
              tone="ok"
              testid="cash-drawer"
            />
            <StatTile
              icon={<CreditCard size={16} />}
              label="Card + UPI"
              value={inr((report.by_method?.card ?? 0) + (report.by_method?.upi ?? 0))}
              tone="info"
              testid="cash-digital"
            />
          </div>

          {report.refunds && Object.keys(report.refunds).length > 0 && (
            <div className="mt-4 bg-amber-50 border border-amber-200 rounded-xl p-4 text-sm" data-testid="cash-refunds">
              <span className="font-semibold">Refunds given today: </span>
              {Object.entries(report.refunds).map(([m, v]) => `${m.replace("_", " ")} ${inr(v)}`).join(" · ")}
              {report.refunds.cash ? <span className="text-slate-600"> (cash refunds are already taken off Cash-in-drawer)</span> : null}
            </div>
          )}

          <div className="mt-6 bg-white border border-slate-200 rounded-xl shadow-sm p-5">
            <div className="text-xs uppercase tracking-widest text-slate-500 font-semibold mb-3">
              Payment breakdown
            </div>
            <div className="space-y-3">
              {["cash", "card", "upi"].map((m) => {
                const amt = report.by_method?.[m] ?? 0;
                const tot = report.total || 1;
                const pct = Math.min(100, (amt / tot) * 100);
                const Icon = m === "cash" ? Coins : m === "card" ? CreditCard : Smartphone;
                return (
                  <div key={m} data-testid={`cash-row-${m}`}>
                    <div className="flex items-center justify-between text-sm">
                      <span className="flex items-center gap-2 capitalize">
                        <Icon size={14} className="text-slate-500" />
                        {m}
                      </span>
                      <span className="mono font-semibold">{inr(amt)}</span>
                    </div>
                    <div className="h-1.5 bg-slate-100 rounded-full mt-1.5">
                      <div
                        className="h-full rounded-full transition-all"
                        style={{
                          width: `${pct}%`,
                          background: "linear-gradient(90deg, #F0544A 0%, #F27F5C 100%)",
                        }}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {report.shift_start && (
            <div className="mt-4 text-xs text-slate-500">
              Shift started: {new Date(report.shift_start).toLocaleString()}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function StatTile({ icon, label, value, sub, tone = "brand", testid }) {
  const toneCls = {
    brand: "text-[#F0544A]",
    ok: "text-emerald-600",
    info: "text-indigo-700",
    warn: "text-amber-600",
  }[tone] || "text-slate-700";
  return (
    <div className="bg-white border border-slate-200 rounded-xl shadow-sm p-4">
      <div className="flex items-center justify-between text-slate-500">
        <span className="text-[11px] uppercase tracking-widest font-semibold">{label}</span>
        <span className={toneCls}>{icon}</span>
      </div>
      <div data-testid={testid} className={`mt-2 text-2xl font-semibold mono ${toneCls}`}>{value}</div>
      {sub && <div className="text-xs text-slate-500 mt-1">{sub}</div>}
    </div>
  );
}

function SkeletonGrid() {
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="bg-white border border-slate-200 rounded-xl p-4 animate-pulse">
          <div className="h-3 bg-slate-100 rounded w-1/2" />
          <div className="h-6 bg-slate-100 rounded w-2/3 mt-3" />
        </div>
      ))}
    </div>
  );
}
