import { NavLink } from "react-router-dom";
import {
  LayoutDashboard, Package, Boxes, ScanBarcode, ArrowLeftRight,
  ShoppingCart, Users, LineChart, UserCog, ClipboardList, LogOut, Plug,
  Container, Wallet, ShieldCheck, Activity, LifeBuoy, Settings2, BookOpen, ListChecks, Undo2,
} from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import NewdruLogo from "@/components/NewdruLogo";
import { ROLE_LABEL } from "@/lib/api";

// Role buckets kept in sync with backend models.py
const OWNER = ["owner"];
const STORE = ["store_manager", "cashier"];
const WAREHOUSE = ["warehouse_manager", "warehouse_staff"];
const WH_MANAGER_ONLY = ["warehouse_manager"];
const ANY = ["owner", "store_manager", "cashier", "warehouse_manager", "warehouse_staff"];

const NAV = [
  // ---- Owner only ----
  { to: "/", label: "Dashboard", icon: LayoutDashboard, roles: OWNER, section: "Overview" },
  // ---- Store bucket ----
  { to: "/pos", label: "Point of Sale", icon: ShoppingCart, roles: [...OWNER, ...STORE], section: "Store" },
  { to: "/returns", label: "Returns", icon: Undo2, roles: [...OWNER, "store_manager"], section: "Store" },
  { to: "/cash", label: "Cash / Till", icon: Wallet, roles: [...OWNER, ...STORE], section: "Store" },
  // ---- Warehouse bucket ----
  { to: "/products", label: "Products", icon: Package, roles: [...OWNER, ...WAREHOUSE], section: "Warehouse" },
  { to: "/inventory", label: "Inventory", icon: Boxes, roles: [...OWNER, ...STORE, ...WAREHOUSE], section: "Warehouse" },
  { to: "/receive", label: "Goods In / Out", icon: ScanBarcode, roles: [...OWNER, ...STORE, ...WAREHOUSE], section: "Warehouse" },
  { to: "/stock-count", label: "Stock Count", icon: ListChecks, roles: [...OWNER, ...STORE, ...WAREHOUSE], section: "Warehouse" },
  { to: "/transfers", label: "Transfers", icon: ArrowLeftRight, roles: [...OWNER, ...WAREHOUSE], section: "Warehouse" },
  { to: "/box-fit", label: "Box-Fit Planner", icon: Container, roles: [...OWNER, ...WAREHOUSE], section: "Warehouse" },
  { to: "/movements", label: "Stock Ledger", icon: ClipboardList, roles: [...OWNER, ...WH_MANAGER_ONLY], section: "Warehouse" },
  // ---- Owner only ----
  { to: "/customers", label: "Customers (CRM)", icon: Users, roles: OWNER, section: "Growth" },
  { to: "/b2b", label: "B2B Orders", icon: ClipboardList, roles: OWNER, section: "Growth" },
  { to: "/collections", label: "Collections", icon: LineChart, roles: OWNER, section: "Growth" },
  { to: "/reports", label: "Reports", icon: LineChart, roles: OWNER, section: "Growth" },
  // ---- Warranty ----
  { to: "/warranty-admin", label: "Registrations", icon: ShieldCheck, roles: [...OWNER, "store_manager"], section: "Warranty" },
  { to: "/warranty-activity", label: "User Activities", icon: Activity, roles: [...OWNER, "store_manager"], section: "Warranty" },
  { to: "/warranty-claims", label: "Claims", icon: LifeBuoy, roles: [...OWNER, "store_manager"], section: "Warranty" },
  { to: "/warranty-analytics", label: "Analytics", icon: LineChart, roles: [...OWNER, "store_manager"], section: "Warranty" },
  { to: "/warranty-settings", label: "Warranty Settings", icon: Settings2, roles: OWNER, section: "Warranty" },
  { to: "/users", label: "Users", icon: UserCog, roles: OWNER, section: "Admin" },
  { to: "/integrations", label: "Integrations", icon: Plug, roles: OWNER, section: "Admin" },
  { to: "/help", label: "User Guide", icon: BookOpen, roles: ANY, section: "Admin" },
];

const ROLE_BADGE_COLOR = {
  owner: { bg: "#FDECEA", fg: "#D84038" },
  store_manager: { bg: "#DBEAFE", fg: "#1D4ED8" },
  cashier: { bg: "#DBEAFE", fg: "#1D4ED8" },
  warehouse_manager: { bg: "#DCFCE7", fg: "#16A34A" },
  warehouse_staff: { bg: "#DCFCE7", fg: "#16A34A" },
};

export default function Sidebar({ onNavigate }) {
  const { user, logout } = useAuth();
  const items = NAV.filter((n) => n.roles.includes(user?.role));
  const badge = ROLE_BADGE_COLOR[user?.role] || ROLE_BADGE_COLOR.owner;

  // Group items by section, preserving NAV order
  const sections = [];
  const seen = new Map();
  for (const it of items) {
    const key = it.section || "";
    if (!seen.has(key)) { seen.set(key, sections.length); sections.push({ label: key, items: [] }); }
    sections[seen.get(key)].items.push(it);
  }

  return (
    <aside className="h-full w-64 bg-white border-r border-slate-200 flex flex-col">
      <div className="px-5 py-5 border-b border-slate-100">
        <NewdruLogo size="md" tagline />
      </div>
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        {sections.map((s, si) => (
          <div key={si} className={si > 0 ? "mt-4" : ""}>
            {s.label && (
              <div className="px-2 pb-1.5 text-[10px] uppercase tracking-widest text-slate-400 font-semibold">
                {s.label}
              </div>
            )}
            <div className="space-y-1">
              {s.items.map((n) => {
                const Icon = n.icon;
                return (
                  <NavLink
                    key={n.to}
                    to={n.to}
                    end={n.to === "/"}
                    data-testid={`nav-${n.to.replace("/", "") || "dashboard"}`}
                    className={({ isActive }) => `sidebar-item ${isActive ? "active" : ""}`}
                    onClick={onNavigate}
                  >
                    <Icon size={18} />
                    <span>{n.label}</span>
                  </NavLink>
                );
              })}
            </div>
          </div>
        ))}
      </nav>
      <div className="p-3 border-t border-slate-100">
        <div className="flex items-center gap-3 px-2 py-2">
          <div
            className="h-9 w-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0"
            style={{ color: badge.fg, background: badge.bg }}
          >
            {(user?.name || "?").slice(0, 1).toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold truncate" data-testid="user-name">{user?.name}</div>
            <span
              data-testid="user-role-badge"
              className="inline-block text-[10px] uppercase tracking-widest font-semibold px-1.5 py-0.5 rounded"
              style={{ color: badge.fg, background: badge.bg }}
            >
              {ROLE_LABEL[user?.role] || user?.role}
            </span>
          </div>
          <button
            onClick={logout}
            data-testid="logout-btn"
            title="Log out"
            className="p-2 rounded-md hover:bg-slate-100 text-slate-500"
          >
            <LogOut size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}
