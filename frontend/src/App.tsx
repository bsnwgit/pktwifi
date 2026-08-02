import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider, useAuth } from './store/auth'
import Layout from './components/Layout'
import Login from './pages/Login'

import { lazy, Suspense } from 'react'
const Dashboard     = lazy(() => import('./pages/Dashboard'))
const AccessPoints  = lazy(() => import('./pages/AccessPoints'))
const Clients       = lazy(() => import('./pages/Clients'))
const Metrics       = lazy(() => import('./pages/Metrics'))
const Alerts        = lazy(() => import('./pages/Alerts'))
const Logs          = lazy(() => import('./pages/Logs'))
const Settings      = lazy(() => import('./pages/Settings'))
const Documentation = lazy(() => import('./pages/Documentation'))

function PageFallback() {
  return <div className="flex items-center justify-center h-48 text-white">Loading…</div>
}

// Embedded via pkthub's remote-settings iframe (?chromeless=1) — hide the
// sidebar/header, just render the page content.
const isChromeless = new URLSearchParams(window.location.search).get('chromeless') === '1'

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace />
  return <Layout chromeless={isChromeless}>{children}</Layout>
}

function AdminRoute({ children }: { children: React.ReactNode }) {
  const { user, isLoading } = useAuth()
  if (isLoading) return <PageFallback />
  if (!user) return <Navigate to="/login" replace />
  if (user.role !== 'admin') return <Navigate to="/" replace />
  return <Layout chromeless={isChromeless}>{children}</Layout>
}

// When loaded through pkthub's proxy, the browser's real path is
// /proxy/<app_id>/... — react-router needs that as its basename or every
// route fails to match and falls through to the "*" redirect (Dashboard).
const proxyPrefixMatch = window.location.pathname.match(/^\/proxy\/\d+/)
const routerBasename = proxyPrefixMatch ? proxyPrefixMatch[0] : undefined

export default function App() {
  return (
    <BrowserRouter basename={routerBasename}>
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
          <Route path="/metrics" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Metrics /></Suspense>
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
          <Route path="/documentation" element={
            <ProtectedRoute>
              <Suspense fallback={<PageFallback />}><Documentation /></Suspense>
            </ProtectedRoute>
          } />
          <Route path="/sites" element={<Navigate to="/settings?tab=sites" replace />} />
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
