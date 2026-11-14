import { useState } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { Menu, X } from "lucide-react";
import Sidebar from "./Sidebar";

export default function DashboardLayout() {
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  const isPOS = loc.pathname.startsWith("/pos");

  return (
    <div className="min-h-screen flex" style={{ background: "var(--app-bg)" }}>
      <div className="hidden lg:flex"><Sidebar /></div>
      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setOpen(false)} />
          <div className="absolute inset-y-0 left-0"><Sidebar onNavigate={() => setOpen(false)} /></div>
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0">
        <header className="lg:hidden bg-white border-b border-slate-200 px-4 h-14 flex items-center justify-between">
          <button
            data-testid="mobile-menu-btn"
            className="p-2 -ml-2 rounded-md hover:bg-slate-100"
            onClick={() => setOpen((v) => !v)}
          >{open ? <X size={20} /> : <Menu size={20} />}</button>
          <span className="font-brand text-xl" style={{ color: "#F0544A" }}>NEWDRU</span>
          <span className="w-8" />
        </header>
        <main className={`flex-1 min-w-0 ${isPOS ? "" : "p-6"}`}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
