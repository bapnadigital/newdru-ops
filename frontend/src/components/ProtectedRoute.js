import { Navigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { LOGIN_PATH } from "@/lib/loginPath";

export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  if (user === null) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to={LOGIN_PATH} replace />;
  if (roles && roles.length && !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}
