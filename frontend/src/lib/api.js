import axios from "axios";
import { LOGIN_PATH } from "@/lib/loginPath";

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL || "";
export const API = `${BACKEND_URL}/api`;

export const api = axios.create({
  baseURL: API,
  withCredentials: true,
  headers: { "Content-Type": "application/json" },
});

// The login session lives in a secure, httpOnly cookie that page scripts can't read.
// The token is only kept in memory as a fallback (never in localStorage, where
// any injected script could steal it).
let memoryToken = null;
export const setAuthToken = (t) => { memoryToken = t || null; };
try { localStorage.removeItem("newdru_token"); } catch { /* ignore */ }

api.interceptors.request.use((config) => {
  const token = memoryToken;
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (r) => r,
  (err) => {
    if (err?.response?.status === 401 && !err?.config?.url?.includes("/auth/")) {
      memoryToken = null;
      if (window.location.pathname !== LOGIN_PATH) window.location.href = LOGIN_PATH;
    }
    return Promise.reject(err);
  }
);

/* ---------- error formatting ---------- */
export function formatApiErrorDetail(detail) {
  if (detail == null) return "Something went wrong.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail))
    return detail.map((e) => (e && typeof e.msg === "string" ? e.msg : JSON.stringify(e))).filter(Boolean).join(" ");
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
}
export const formatApiError = formatApiErrorDetail;

/* ---------- formatting helpers ---------- */
export function fmtINR(n) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency", currency: "INR", maximumFractionDigits: 2,
  }).format(Number(n || 0));
}
export const inr = fmtINR;

export function fmtDate(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      day: "2-digit", month: "short", year: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

/* ---------- role helpers ---------- */
export function canSeeCost(userOrRole) {
  const r = typeof userOrRole === "string" ? userOrRole : userOrRole?.role;
  return r !== "cashier";
}
export function isAdmin(userOrRole) {
  const r = typeof userOrRole === "string" ? userOrRole : userOrRole?.role;
  return r === "owner" || r === "admin";
}

/* ---------- labels & constants ---------- */
export const ROLES = {
  OWNER: "owner",
  STORE_MANAGER: "store_manager",
  CASHIER: "cashier",
  WH_MANAGER: "warehouse_manager",
  WH_STAFF: "warehouse_staff",
};

export const ROLE_LABELS = {
  owner: "Owner",
  admin: "Owner",
  store_manager: "Store Manager",
  cashier: "Cashier",
  warehouse_manager: "Warehouse Manager",
  warehouse_staff: "Warehouse Staff",
};
export const ROLE_LABEL = ROLE_LABELS;

export const ALL_ROLES = ["owner", "store_manager", "cashier", "warehouse_manager", "warehouse_staff"];

export const LOCATION_LABEL = {
  STORE: "Newdru Store",
  BHIWANDI: "Bhiwandi Warehouse",
  AMAZON_FC: "Amazon FC",
  FLIPKART_FC: "Flipkart FC",
};

export default api;
