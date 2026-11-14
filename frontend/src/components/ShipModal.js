import { useState } from "react";
import { api, formatApiError } from "@/lib/api";
import { toast } from "sonner";

// One-click Shiprocket shipment for a wholesale order (kind="b2b") or a store bill (kind="sale").
export default function ShipModal({ kind, refId, refNo, defaults = {}, onClose, onDone }) {
  const [a, setA] = useState({
    name: defaults.name || "", phone: defaults.phone || "", email: defaults.email || "",
    line1: defaults.line1 || "", line2: "", city: defaults.city || "", state: defaults.state || "Maharashtra",
    pincode: defaults.pincode || "",
  });
  const [pkg, setPkg] = useState({ weight_kg: 1, length_cm: 20, breadth_cm: 15, height_cm: 10 });
  const [cod, setCod] = useState(false);
  const [rates, setRates] = useState(null);
  const [courier, setCourier] = useState("");
  const [busy, setBusy] = useState(false);
  const set = (k) => (e) => setA({ ...a, [k]: e.target.value });

  const checkRates = async () => {
    if (!/^[1-9][0-9]{5}$/.test(a.pincode)) return toast.error("Enter a 6-digit pincode");
    setBusy(true);
    try {
      const { data } = await api.post("/shipping/rates", { delivery_pincode: a.pincode, weight_kg: Number(pkg.weight_kg), cod,
        ship_from: kind === "sale" ? "STORE" : "BHIWANDI" });
      setRates(data);
      if (!data.couriers.length) toast.error("No courier serves this pincode");
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setBusy(false);
  };

  const ship = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/shipping/ship", {
        kind, ref_id: refId, address: a, cod,
        weight_kg: Number(pkg.weight_kg), length_cm: Number(pkg.length_cm),
        breadth_cm: Number(pkg.breadth_cm), height_cm: Number(pkg.height_cm),
        courier_id: courier ? Number(courier) : null,
      });
      toast.success(`Shipped · ${data.courier} · AWB ${data.awb}`);
      if (data.label_url) window.open(data.label_url, "_blank", "noopener,noreferrer");
      onDone?.(data);
    } catch (e) { toast.error(formatApiError(e.response?.data?.detail)); }
    setBusy(false);
  };

  const field = (k, label, extra = {}) => (
    <label className="text-xs text-slate-600 block">{label}
      <input value={a[k]} onChange={set(k)} className="mt-1 w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm" {...extra} />
    </label>
  );

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white rounded-xl w-full max-w-lg p-5 max-h-[90vh] overflow-auto" onClick={(e) => e.stopPropagation()}>
        <div className="font-semibold mb-1">Ship {refNo} with Shiprocket</div>
        <div className="text-xs text-slate-500 mb-3">Creates the shipment, books the courier, schedules pickup and opens the label.</div>
        <div className="grid grid-cols-2 gap-2">
          {field("name", "Receiver name")}
          {field("phone", "Phone", { inputMode: "tel" })}
          <div className="col-span-2">{field("line1", "Address")}</div>
          <div className="col-span-2">{field("line2", "Landmark (optional)")}</div>
          {field("city", "City")}
          {field("state", "State")}
          {field("pincode", "Pincode", { inputMode: "numeric", maxLength: 6 })}
          {field("email", "Email (optional)", { type: "email" })}
        </div>
        <div className="grid grid-cols-4 gap-2 mt-3">
          {[["weight_kg", "Weight kg"], ["length_cm", "L cm"], ["breadth_cm", "B cm"], ["height_cm", "H cm"]].map(([k, l]) => (
            <label key={k} className="text-xs text-slate-600">{l}
              <input type="number" min="0" step="0.1" value={pkg[k]} onChange={(e) => setPkg({ ...pkg, [k]: e.target.value })}
                     className="mt-1 w-full border border-slate-300 rounded-md px-2 py-1.5 text-sm" />
            </label>
          ))}
        </div>
        <label className="flex items-center gap-2 text-sm mt-3"><input type="checkbox" checked={cod} onChange={(e) => setCod(e.target.checked)} /> Cash on delivery</label>
        <div className="flex gap-2 mt-3 items-center">
          <button onClick={checkRates} disabled={busy} className="border border-slate-300 rounded-md px-3 py-2 text-sm">Check couriers</button>
          {rates?.couriers?.length > 0 && (
            <select value={courier} onChange={(e) => setCourier(e.target.value)} className="border border-slate-300 rounded-md px-2 py-2 text-sm flex-1">
              <option value="">Shiprocket recommended</option>
              {rates.couriers.map((c) => <option key={c.courier_id} value={c.courier_id}>{c.name} · ₹{c.rate}{c.etd ? ` · ${c.etd}` : ""}</option>)}
            </select>
          )}
        </div>
        <div className="flex justify-end gap-2 mt-5">
          <button onClick={onClose} className="px-3 py-2 text-sm">Cancel</button>
          <button data-testid="ship-confirm" onClick={ship} disabled={busy} className="btn-brand disabled:opacity-50">{busy ? "Working…" : "Ship now"}</button>
        </div>
      </div>
    </div>
  );
}
