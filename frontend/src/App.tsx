import { Navigate, Route, Routes } from 'react-router-dom'
import AuthProvider from './components/AuthProvider.tsx'
import RequireAuth from './components/RequireAuth.tsx'
import Dashboard from './pages/Dashboard.tsx'
import SignIn from './pages/SignIn.tsx'

/**
 * Routing is role-aware: `/login` is public, everything else needs a session.
 * The dashboard then hides the administrator areas unless the session holds the
 * `admin` role, matching the server-side guards on /api/audit and /api/admin/*.
 */
export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<SignIn />} />
        <Route
          path="/dashboard"
          element={
            <RequireAuth>
              <Dashboard />
            </RequireAuth>
          }
        />
        <Route path="/" element={<Navigate to="/dashboard" replace />} />
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </AuthProvider>
  )
}

