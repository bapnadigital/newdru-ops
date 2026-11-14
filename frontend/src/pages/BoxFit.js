import { useEffect, useState, useRef } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";
import {
  Search,
  Package,
  Box,
  Weight,
  Ruler,
  AlertTriangle,
  CheckCircle2,
  XCircle,
  Barcode as BarcodeIcon,
} from "lucide-react";

export default function BoxFit() {
  const [q, setQ] = useState("");
  const [results, setResults] = useState([]);
  const [selected, setSelected] = useState(null);
  const [qty, setQty] = useState(0);
  const [plan, setPlan] = useState(null);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);

  // debounced product search
  useEffect(() => {
    if (!q || q.length < 2) {
      setResults([]);
      return;
    }
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(async () => {
      try {
        const { data } = await api.get("/products", { params: { q, limit: 20 } });
        setResults(data);
      } catch (e) {
        toast.error(formatApiError(e.response?.data?.detail));
      }
    }, 250);
  }, [q]);

  const runPlan = async () => {
    if (!selected || !qty || qty <= 0) {
      toast.error("Pick a product and enter a quantity > 0");
      return;
    }
    setLoading(true);
    try {
      const { data } = await api.get("/planner/box-fit", {
        params: { product_id: selected.id, quantity: qty },
      });
      setPlan(data);
    } catch (e) {
      toast.error(formatApiError(e.response?.data?.detail));
    }
    setLoading(false);
  };

  const pickProduct = (p) => {
    setSelected(p);
    setResults([]);
    setQ(p.sku);
    setPlan(null);
  };

  return (
    <div className="max-w-5xl">
      <div className="mb-6">
        <h1 className="text-2xl md:text-3xl font-semibold tracking-tight">Box-Fit Planner</h1>
        <p className="text-slate-500 text-sm">
          Enter a product + quantity to ship — get boxes, weight, volume, FNSKU, and Bhiwandi
          availability in one shot.
        </p>
      </div>

      {/* ---------- Inputs ---------- */}
      <div className="bg-white border border-slate-200 rounded-md p-5 mb-6">
        <div className="grid grid-cols-1 md:grid-cols-[2fr_1fr_auto] gap-3 items-end">
          <div>
            <label className="text-xs uppercase tracking-widest text-slate-600 font-semibold mb-1 block">
              Product
            </label>
            <div className="relative">
              <Search size={14} className="absolute left-2.5 top-3 text-slate-400" />
              <input
                data-testid="boxfit-product-search"
                placeholder="Search SKU / name / FNSKU…"
                value={q}
                onChange={(e) => {
                  setQ(e.target.value);
                  setSelected(null);
                }}
                className="pl-8 pr-3 py-2 text-sm border border-slate-300 rounded-md w-full"
              />
              {results.length > 0 && !selected && (
                <div className="absolute left-0 right-0 z-20 mt-1 bg-white border border-slate-200 rounded-md shadow-lg max-h-72 overflow-y-auto scroll-thin">
                  {results.map((p) => (
                    <button
                      key={p.id}
                      data-testid={`boxfit-pick-${p.sku}`}
                      onClick={() => pickProduct(p)}
                      className="w-full text-left px-3 py-2 hover:bg-slate-50 border-b border-slate-100 text-sm"
                    >
                      <div className="font-semibold">
                        {p.sku}{" "}
                        {p.placeholder_pricing && (
                          <span className="ml-1 text-[10px] uppercase tracking-wide bg-amber-100 text-amber-800 px-1.5 py-0.5 rounded">
                            Placeholder
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-slate-500">{p.name}</div>
                    </button>
                  ))}
                </div>
              )}
            </div>
            {selected && (
              <div className="mt-2 text-xs text-slate-600">
                Selected: <span className="font-semibold">{selected.sku}</span> — {selected.name}
              </div>
            )}
          </div>
          <div>
            <label className="text-xs uppercase tracking-widest text-slate-600 font-semibold mb-1 block">
              Quantity to ship
            </label>
            <input
              data-testid="boxfit-qty"
              type="number"
              min="1"
              value={qty || ""}
              onChange={(e) => setQty(parseInt(e.target.value || 0))}
              className="w-full px-3 py-2 text-sm border border-slate-300 rounded-md"
            />
          </div>
          <button
            data-testid="boxfit-calc"
            onClick={runPlan}
            disabled={loading || !selected || !qty}
            className="bg-[hsl(234_61%_25%)] text-white px-4 py-2 rounded-md text-sm font-medium disabled:opacity-60"
          >
            {loading ? "Calculating…" : "Calculate"}
          </button>
        </div>
      </div>

      {/* ---------- Results ---------- */}
      {plan && <PlanResult plan={plan} />}
    </div>
  );
}

function PlanResult({ plan }) {
  const c = plan.computation || {};
  const s = plan.stock || {};
  const pk = plan.packaging || {};
  const noPacking = !pk.units_per_carton;

  return (
    <div className="space-y-4">
      {plan.warnings?.length > 0 && (
        <div
          data-testid="boxfit-warnings"
          className="bg-amber-50 border border-amber-200 rounded-md p-3"
        >
          {plan.warnings.map((w, i) => (
            <div key={i} className="flex items-start gap-2 text-sm text-amber-900">
              <AlertTriangle size={16} className="mt-0.5 shrink-0" />
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* stock verdict */}
      <div
        data-testid="boxfit-stock"
        className={`rounded-md border p-4 ${
          s.has_enough
            ? "bg-emerald-50 border-emerald-200"
            : "bg-rose-50 border-rose-200"
        }`}
      >
        <div className="flex items-center gap-3">
          {s.has_enough ? (
            <CheckCircle2 size={22} className="text-emerald-600" />
          ) : (
            <XCircle size={22} className="text-rose-600" />
          )}
          <div>
            <div className="font-semibold text-sm">
              {s.has_enough
                ? `YES — Bhiwandi has enough stock (${s.available.toLocaleString()} available)`
                : `SHORT by ${s.shortage.toLocaleString()} units at Bhiwandi (have ${s.available.toLocaleString()}, need ${s.requested.toLocaleString()})`}
            </div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Boxes */}
        <div className="bg-white border border-slate-200 rounded-md p-4">
          <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-widest text-slate-600 font-semibold">
            <Box size={14} /> Boxes
          </div>
          {noPacking ? (
            <div className="text-sm text-slate-500">
              Packaging not set — please add units per carton on the Products screen.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric label="Units per box" value={c.units_per_box} testid="metric-upc" />
              <Metric label="Full boxes" value={c.full_boxes} testid="metric-full" />
              <Metric
                label="Loose units in last box"
                value={c.loose_units}
                testid="metric-loose"
              />
              <Metric
                label="Total boxes"
                value={c.total_boxes}
                emphasize
                testid="metric-total-boxes"
              />
            </div>
          )}
        </div>

        {/* Weight */}
        <div className="bg-white border border-slate-200 rounded-md p-4">
          <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-widest text-slate-600 font-semibold">
            <Weight size={14} /> Weight
          </div>
          {c.gross_weight_per_box_kg == null ? (
            <div className="text-sm text-slate-500">Carton weight missing.</div>
          ) : (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric
                label="Gross wt / box"
                value={`${c.gross_weight_per_box_kg} kg`}
                testid="metric-wt-per-box"
              />
              <Metric
                label="Total gross weight"
                value={`${c.total_gross_weight_kg} kg`}
                emphasize
                testid="metric-total-wt"
              />
            </div>
          )}
        </div>

        {/* Volume */}
        <div className="bg-white border border-slate-200 rounded-md p-4">
          <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-widest text-slate-600 font-semibold">
            <Ruler size={14} /> Volume
          </div>
          {c.volume_per_box_cft == null ? (
            <div className="text-sm text-slate-500">Carton dimensions missing.</div>
          ) : (
            <div className="grid grid-cols-2 gap-3 text-sm">
              <Metric
                label="CFT / box"
                value={c.volume_per_box_cft}
                testid="metric-cft-per-box"
              />
              <Metric
                label="CBM / box"
                value={c.volume_per_box_cbm}
                testid="metric-cbm-per-box"
              />
              <Metric
                label="Total CFT"
                value={c.total_volume_cft}
                emphasize
                testid="metric-total-cft"
              />
              <Metric
                label="Total CBM"
                value={c.total_volume_cbm}
                emphasize
                testid="metric-total-cbm"
              />
            </div>
          )}
        </div>

        {/* Amazon */}
        <div className="bg-white border border-slate-200 rounded-md p-4">
          <div className="flex items-center gap-2 mb-3 text-xs uppercase tracking-widest text-slate-600 font-semibold">
            <BarcodeIcon size={14} /> Amazon / Shipment Label
          </div>
          <div className="space-y-2 text-sm">
            <Field
              label="FNSKU (shipment barcode)"
              value={plan.product?.fnsku}
              missing="Not set"
              mono
              testid="metric-fnsku"
            />
            <Field label="ASIN" value={plan.product?.amazon_asin} mono />
            <Field label="MSKU" value={plan.product?.amazon_msku} mono />
            {plan.product?.notes && (
              <div className="text-xs text-slate-500 italic">
                Notes: {plan.product.notes}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Packaging reference */}
      <div className="bg-white border border-slate-200 rounded-md p-4 text-xs text-slate-600">
        <div className="flex items-center gap-2 mb-2 text-slate-500 uppercase tracking-widest font-semibold">
          <Package size={12} /> Packaging reference
        </div>
        <div className="flex flex-wrap gap-x-6 gap-y-1">
          <span>UPC: <strong>{pk.units_per_carton ?? "—"}</strong></span>
          <span>
            L×W×H:{" "}
            <strong>
              {pk.carton_length_cm
                ? `${pk.carton_length_cm} × ${pk.carton_width_cm} × ${pk.carton_height_cm} cm`
                : "—"}
            </strong>
          </span>
          <span>Carton wt: <strong>{pk.carton_weight_kg ? `${pk.carton_weight_kg} kg` : "—"}</strong></span>
          <span>Unit wt: <strong>{pk.unit_weight_g ? `${pk.unit_weight_g} g` : "—"}</strong></span>
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value, emphasize, testid }) {
  return (
    <div>
      <div className="text-xs text-slate-500">{label}</div>
      <div
        data-testid={testid}
        className={`${
          emphasize ? "text-lg font-semibold text-[hsl(234_61%_25%)]" : "text-sm font-medium"
        }`}
      >
        {value ?? "—"}
      </div>
    </div>
  );
}

function Field({ label, value, missing = "—", mono, testid }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-slate-500">{label}:</span>
      <span
        data-testid={testid}
        className={`${mono ? "font-mono" : ""} ${
          !value ? "text-slate-400 italic" : "text-slate-800 font-medium"
        }`}
      >
        {value || missing}
      </span>
    </div>
  );
}
