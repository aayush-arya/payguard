import type { ReactNode } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './lib/auth'
import { ToastProvider } from './components/ui'
import { Layout } from './components/Layout'
import { Connect } from './pages/Connect'
import { DashboardHome } from './pages/DashboardHome'
import { PaymentsList } from './pages/PaymentsList'
import { PaymentDetail } from './pages/PaymentDetail'
import { Reconciliation } from './pages/Reconciliation'
import { RiskAndFraud } from './pages/RiskAndFraud'
import { Webhooks } from './pages/Webhooks'
import { ProviderHealth } from './pages/ProviderHealth'
import { ComingSoon } from './pages/ComingSoon'

function RequireAuth({ children }: { children: ReactNode }) {
  const { apiKey } = useAuth()
  if (!apiKey) return <Navigate to="/connect" replace />
  return <>{children}</>
}

function AppRoutes() {
  return (
    <Routes>
      <Route path="/connect" element={<Connect />} />
      <Route
        element={
          <RequireAuth>
            <Layout />
          </RequireAuth>
        }
      >
        <Route path="/" element={<DashboardHome />} />
        <Route path="/payments" element={<PaymentsList />} />
        <Route path="/payments/:paymentId" element={<PaymentDetail />} />
        <Route path="/reconciliation" element={<Reconciliation />} />
        <Route path="/risk" element={<RiskAndFraud />} />
        <Route path="/webhooks" element={<Webhooks />} />
        <Route path="/providers" element={<ProviderHealth />} />
        <Route path="/refunds" element={<ComingSoon title="Refunds" />} />
        <Route path="/analytics" element={<ComingSoon title="Analytics" />} />
        <Route path="/settings" element={<ComingSoon title="Settings" />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

function App() {
  return (
    <AuthProvider>
      <ToastProvider>
        <BrowserRouter>
          <AppRoutes />
        </BrowserRouter>
      </ToastProvider>
    </AuthProvider>
  )
}

export default App
