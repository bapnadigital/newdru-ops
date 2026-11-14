import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { LOGIN_PATH } from "@/lib/loginPath";

// user === undefined: still checking the session -> show a loader (don't redirect,
// otherwise a page refresh would bounce staff to the home screen).
// user === null: not signed in -> go to login and remember where they were.
export default function ProtectedRoute({ children, roles }) {
  const { user } = useAuth();
  const location = useLocation();
  if (user === undefined) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-400">
        Loading…
      </div>
    );
  }
  if (!user) return <Navigate to={LOGIN_PATH} replace state={{ from: location.pathname + location.search }} />;
  if (roles && roles.length && !roles.includes(user.role)) {
    return <Navigate to="/" replace />;
  }
  return children;
}
