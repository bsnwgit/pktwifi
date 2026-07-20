import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './store/auth'
import Layout from './components/Layout'
import Login from './pages/Login'

import { lazy, Suspense } from 'react'
const Dashboard     = lazy(() => import('./pages/Dashboard'))
const AccessPoints  = lazy(() => import('./pages/AccessPoints'))
const Clients       = lazy(() => import('./pages/Clients'))
const Alerts        = lazy(() => import('./pages/Alerts'))
const Logs          = lazy(() => import('./pages/Logs'))
const Collectors    = lazy(() => import('./pages/Collectors'))
const Sites         = lazy(() => import('./pages/Sites'))
const Settings      = lazy(() => import('./pages/Settings'))

function PageFallback() {
  return <div className="flex items-center justify-center h-48 text-white">Loading…</div>
}

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace />
  return <Layout>{children}</Layout>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return <Layout>{children}</Layout>
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Dashboard /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/access-points" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><AccessPoints /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/clients" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Clients /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/alerts" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Alerts /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/logs" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Logs /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/collectors" element={
            <AdminRoute>
              <Suspense fallback={<PageFallback />}><Collectors /></Suspense>
            </AdminRoute>
          } />
          <Route path="/sites" element={
            <AdminRoute>
              <Suspense fallback={<PageFallback />}><Sites /></Suspense>
            </AdminRoute>
          } />
          <Route path="/integrations" element={<Navigate to="/settings" replace />} />
          <Route path="/settings" element={
            <AdminRoute>
              <Suspense fallback={<PageFallback />}><Settings /></Suspense>
            </AdminRoute>
          } />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
