import { useEffect, useRef } from "react";
import JsBarcode from "jsbarcode";

export default function Barcode({ value, height = 40, width = 1.4, displayValue = false, className = "" }) {
  const ref = useRef(null);
  useEffect(() => {
    if (!ref.current || !value) return;
    try {
      JsBarcode(ref.current, String(value), {
        format: "CODE128", displayValue, height, width, margin: 0, background: "#ffffff",
      });
    } catch (e) { /* ignore */ }
  }, [value, height, width, displayValue]);
  return <svg ref={ref} className={className} data-testid={`barcode-${value}`} />;
}
