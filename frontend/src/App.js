import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { LOGIN_PATH } from "@/lib/loginPath";
import { AuthProvider, useAuth } from "@/contexts/AuthContext";
import ProtectedRoute from "@/components/ProtectedRoute";
import DashboardLayout from "@/components/layout/DashboardLayout";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Products from "@/pages/Products";
import Inventory from "@/pages/Inventory";
import POS from "@/pages/POS";
import Cash from "@/pages/Cash";
import Receive from "@/pages/Receive";
import StockCount from "@/pages/StockCount";
import Returns from "@/pages/Returns";
import ActivityLog from "@/pages/ActivityLog";
import Transfers from "@/pages/Transfers";
import StockLedger from "@/pages/StockLedger";
import Customers from "@/pages/Customers";
import Reports from "@/pages/Reports";
import Users from "@/pages/Users";
import Integrations from "@/pages/Integrations";
import B2B from "@/pages/B2B";
import Collections from "@/pages/Collections";
import BoxFit from "@/pages/BoxFit";
import WarrantyPublic from "@/pages/WarrantyPublic";
import WarrantyRegistrations from "@/pages/WarrantyRegistrations";
import WarrantyActivity from "@/pages/WarrantyActivity";
import WarrantyClaims from "@/pages/WarrantyClaims";
import WarrantyAnalytics from "@/pages/WarrantyAnalytics";
import WarrantySettings from "@/pages/WarrantySettings";
import Help from "@/pages/Help";
import { Toaster } from "sonner";
import "@/App.css";

const ANY = ["owner", "store_manager", "cashier", "warehouse_manager", "warehouse_staff"];
const OWNER = ["owner"];
const STORE = ["store_manager", "cashier"];
const WAREHOUSE = ["warehouse_manager", "warehouse_staff"];

// Owner sees Dashboard at "/". Store role lands on POS; warehouse role on Inventory.
function HomeGate() {
  const { user } = useAuth();
  if (!user) return null;
  if (user.role === "owner") return <Dashboard />;
  if (STORE.includes(user.role)) return <Navigate to="/pos" replace />;
  if (WAREHOUSE.includes(user.role)) return <Navigate to="/inventory" replace />;
  return <Navigate to="/pos" replace />;
}

function App() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Toaster position="top-right" richColors />
        <Routes>
          <Route path={LOGIN_PATH} element={<Login />} />
          <Route path="/warranty" element={<WarrantyPublic />} />
          <Route element={<ProtectedRoute roles={ANY}><DashboardLayout /></ProtectedRoute>}>
            <Route path="/" element={<HomeGate />} />
            <Route path="/pos" element={<ProtectedRoute roles={[...OWNER, ...STORE]}><POS /></ProtectedRoute>} />
            <Route path="/cash" element={<ProtectedRoute roles={[...OWNER, ...STORE]}><Cash /></ProtectedRoute>} />
            <Route path="/products" element={<ProtectedRoute roles={[...OWNER, ...WAREHOUSE]}><Products /></ProtectedRoute>} />
            <Route path="/inventory" element={<ProtectedRoute roles={[...OWNER, ...STORE, ...WAREHOUSE]}><Inventory /></ProtectedRoute>} />
            <Route path="/receive" element={<ProtectedRoute roles={[...OWNER, ...STORE, ...WAREHOUSE]}><Receive /></ProtectedRoute>} />
            <Route path="/activity" element={<ProtectedRoute roles={OWNER}><ActivityLog /></ProtectedRoute>} />
            <Route path="/returns" element={<ProtectedRoute roles={[...OWNER, "store_manager"]}><Returns /></ProtectedRoute>} />
            <Route path="/stock-count" element={<ProtectedRoute roles={[...OWNER, ...STORE, ...WAREHOUSE]}><StockCount /></ProtectedRoute>} />
            <Route path="/transfers" element={<ProtectedRoute roles={[...OWNER, ...WAREHOUSE]}><Transfers /></ProtectedRoute>} />
            <Route path="/movements" element={<ProtectedRoute roles={[...OWNER, "warehouse_manager"]}><StockLedger /></ProtectedRoute>} />
            <Route path="/box-fit" element={<ProtectedRoute roles={[...OWNER, ...WAREHOUSE]}><BoxFit /></ProtectedRoute>} />
            <Route path="/customers" element={<ProtectedRoute roles={OWNER}><Customers /></ProtectedRoute>} />
            <Route path="/reports" element={<ProtectedRoute roles={OWNER}><Reports /></ProtectedRoute>} />
            <Route path="/b2b" element={<ProtectedRoute roles={OWNER}><B2B /></ProtectedRoute>} />
            <Route path="/collections" element={<ProtectedRoute roles={OWNER}><Collections /></ProtectedRoute>} />
            <Route path="/warranty-admin" element={<ProtectedRoute roles={[...OWNER, "store_manager"]}><WarrantyRegistrations /></ProtectedRoute>} />
            <Route path="/warranty-activity" element={<ProtectedRoute roles={[...OWNER, "store_manager"]}><WarrantyActivity /></ProtectedRoute>} />
            <Route path="/warranty-claims" element={<ProtectedRoute roles={[...OWNER, "store_manager"]}><WarrantyClaims /></ProtectedRoute>} />
            <Route path="/warranty-analytics" element={<ProtectedRoute roles={[...OWNER, "store_manager"]}><WarrantyAnalytics /></ProtectedRoute>} />
            <Route path="/warranty-settings" element={<ProtectedRoute roles={OWNER}><WarrantySettings /></ProtectedRoute>} />
            <Route path="/help" element={<Help />} />
            <Route path="/users" element={<ProtectedRoute roles={OWNER}><Users /></ProtectedRoute>} />
            <Route path="/integrations" element={<ProtectedRoute roles={OWNER}><Integrations /></ProtectedRoute>} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}

export default App;
