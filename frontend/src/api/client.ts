/**
 * pktWiFi API client — typed fetch wrappers.
 * Access token is stored in memory (not localStorage).
 */

let _accessToken: string | null = null
let _tokenRole: string | null = null

export function setToken(token: string, role: string) {
  _accessToken = token
  _tokenRole = role
}

export function clearToken() {
  _accessToken = null
  _tokenRole = null
}

export function getRole(): string | null {
  return _tokenRole
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  }
  if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`

  const res = await fetch(`/api${path}`, { ...options, headers })

  if (res.status === 401) {
    const refreshed = await tryRefresh()
    if (refreshed) {
      headers['Authorization'] = `Bearer ${_accessToken}`
      const retry = await fetch(`/api${path}`, { ...options, headers })
      if (!retry.ok) throw new Error(`${retry.status} ${retry.statusText}`)
      return retry.status === 204 ? (null as T) : retry.json()
    }
    clearToken()
    window.location.href = '/login'
    throw new Error('Session expired')
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || res.statusText)
  }

  if (res.status === 204) return null as T
  return res.json()
}

async function tryRefresh(): Promise<boolean> {
  try {
    const res = await fetch('/api/auth/refresh', { method: 'POST', credentials: 'include' })
    if (!res.ok) return false
    const data = await res.json()
    setToken(data.access_token, data.role)
    return true
  } catch {
    return false
  }
}

export const api = {
  // -- Auth --------------------------------------------------------------------
  // Deliberately bypasses request() — a bad password here is a normal login
  // failure, not an expired session, and must not trigger the 401 handler's
  // refresh-then-redirect-to-/login flow (that would hard-reload the login
  // page itself before the error message is even visible).
  login: async (username: string, password: string) => {
    const res = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password }),
    })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json() as Promise<{ access_token: string; role: string }>
  },
  logout: () => request('/auth/logout', { method: 'POST' }),
  getAuthConfig: () => request<{ saml_enabled: boolean; local_enabled: boolean }>('/auth/config'),

  // -- Users ---------------------------------------------------------------------
  getMe: () => request<User>('/users/me'),
  getUsers: () => request<User[]>('/users'),
  createUser: (body: { username: string; email: string; password: string; role: string }) =>
    request<User>('/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: { role?: string; is_active?: boolean }) =>
    request<User>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteUser: (id: number) => request(`/users/${id}`, { method: 'DELETE' }),
  changeMyPassword: (current_password: string, new_password: string) =>
    request('/users/me/change-password', { method: 'POST', body: JSON.stringify({ current_password, new_password }) }),

  // -- Devices (access points) ---------------------------------------------------
  getDevicesSummary: () => request<DevicesSummary>('/devices/summary'),
  getAccessPoints: (params?: { status?: string; site?: string }) => {
    const q = new URLSearchParams(params as Record<string, string>)
    return request<AccessPoint[]>(`/devices${q.toString() ? '?' + q : ''}`)
  },
  getAccessPoint: (id: number) => request<AccessPoint & { radios: Radio[] }>(`/devices/${id}`),
  createAccessPoint: (body: Partial<AccessPoint>) => request<AccessPoint>('/devices', { method: 'POST', body: JSON.stringify(body) }),
  updateAccessPoint: (id: number, body: Partial<AccessPoint>) =>
    request<AccessPoint>(`/devices/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteAccessPoint: (id: number) => request(`/devices/${id}`, { method: 'DELETE' }),

  // -- Clients ---------------------------------------------------------------------
  getClients: (params?: { access_point_id?: number; ssid?: string }) => {
    const q = new URLSearchParams(params as any)
    return request<WifiClient[]>(`/clients${q.toString() ? '?' + q : ''}`)
  },
  getClient: (mac: string) => request<WifiClient>(`/clients/${mac}`),
  getClientEvents: (mac: string) => request<ClientEvent[]>(`/clients/${mac}/events`),

  // -- Metrics ---------------------------------------------------------------------
  getRadioMetrics: (radioId: number, sinceMinutes = 60) =>
    request<MetricPoint[]>(`/metrics/radios/${radioId}?since_minutes=${sinceMinutes}`),
  getAccessPointMetrics: (apId: number, sinceMinutes = 60) =>
    request<Record<string, MetricPoint[]>>(`/metrics/access-points/${apId}?since_minutes=${sinceMinutes}`),

  // -- Alerts ---------------------------------------------------------------------
  getAlertRules: () => request<AlertRule[]>('/alerts/rules'),
  createAlertRule: (body: Partial<AlertRule>) => request<AlertRule>('/alerts/rules', { method: 'POST', body: JSON.stringify(body) }),
  updateAlertRule: (id: number, body: Partial<AlertRule>) => request<AlertRule>(`/alerts/rules/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteAlertRule: (id: number) => request(`/alerts/rules/${id}`, { method: 'DELETE' }),
  getAlertEvents: (params?: { active?: boolean; acked?: boolean; limit?: number }) => {
    const q = new URLSearchParams()
    if (params?.active !== undefined) q.set('active', String(params.active))
    if (params?.acked !== undefined) q.set('acked', String(params.acked))
    if (params?.limit !== undefined) q.set('limit', String(params.limit))
    return request<AlertEvent[]>(`/alerts/events?${q}`)
  },
  ackAlertEvent: (id: number) => request(`/alerts/events/${id}/ack`, { method: 'POST' }),
  resolveAlertEvent: (id: number) => request(`/alerts/events/${id}/resolve`, { method: 'POST' }),

  // -- Logs ---------------------------------------------------------------------
  getAppLogs: (params?: { level?: string; limit?: number }) => {
    const q = new URLSearchParams(params as any)
    return request<AppLog[]>(`/logs${q.toString() ? '?' + q : ''}`)
  },
  getPktLogEntries: (mac_address?: string) =>
    request<any[]>(`/logs/pktlog${mac_address ? `?mac_address=${mac_address}` : ''}`),

  // -- Collectors ---------------------------------------------------------------------
  getCollectorTypes: () => request<CollectorType[]>('/collectors/types'),
  getCollectors: () => request<Collector[]>('/collectors'),
  getCollector: (id: number) => request<Collector & { config: Record<string, unknown> }>(`/collectors/${id}`),
  createCollector: (body: Partial<Collector> & { config: Record<string, unknown> }) =>
    request<Collector>('/collectors', { method: 'POST', body: JSON.stringify(body) }),
  updateCollector: (id: number, body: Partial<Collector> & { config?: Record<string, unknown> }) =>
    request<Collector>(`/collectors/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteCollector: (id: number) => request(`/collectors/${id}`, { method: 'DELETE' }),
  pollCollectorNow: (id: number) => request<{ status: string; access_points: number; clients: number }>(`/collectors/${id}/poll-now`, { method: 'POST' }),

  // -- Integrations (suite-token client of sibling pkt apps) -----------------------
  getIntegrations: () => request<Integration[]>('/integrations'),
  setIntegration: (appName: string, body: { base_url: string; suite_token: string; enabled: boolean }) =>
    request<Integration>(`/integrations/${appName}`, { method: 'PUT', body: JSON.stringify(body) }),
  testIntegration: (appName: string) => request<{ healthy: boolean; detail: string }>(`/integrations/${appName}/test`, { method: 'POST' }),

  // -- Suite (inbound — pktHub registering this app) --------------------------------
  getSuiteToken: () => request<{ suite_token: string; has_token: boolean }>('/suite/token'),
  regenerateSuiteToken: () => request<{ suite_token: string; status: string }>('/suite/regenerate', { method: 'POST' }),

  // -- Settings ---------------------------------------------------------------------
  getSettings: () => request<Record<string, unknown>>('/settings'),
  updateSettings: (values: Record<string, unknown>) => request('/settings', { method: 'PUT', body: JSON.stringify({ values }) }),

  // -- System ---------------------------------------------------------------------
  getSystemInfo: () => request<{ version: string; install_dir: string; port: number }>('/system/info'),
  listBackups: () => request<Array<{ name: string; path: string; size_bytes: number; files: string[] }>>('/system/backups'),
  runBackupNow: () => request<{ status: string; path: string; files: string[]; kept: number }>('/system/backups/run', { method: 'POST' }),
  restartService: () => request<{ status: string; message: string }>('/system/restart', { method: 'POST' }),
}

// -- Types -----------------------------------------------------------------------

export interface User {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  auth_provider: string
  created_at: string
  last_login: string | null
  has_password: boolean
}

export interface DevicesSummary {
  total: number
  online: number
  offline: number
  rogue: number
  by_vendor: Array<{ vendor: string; count: number }>
  total_clients: number
}

export interface Radio {
  id: number
  band: string
  channel: number | null
  channel_width_mhz: number | null
  tx_power_dbm: number | null
  utilization_pct: number | null
  noise_floor_dbm: number | null
  client_count: number
  updated_at: string
}

export interface AccessPoint {
  id: number
  collector_id: number | null
  external_id: string | null
  name: string
  mac_address: string | null
  ip_address: string | null
  vendor: string | null
  model: string | null
  firmware_version: string | null
  site: string | null
  floor: string | null
  status: string
  is_rogue: boolean
  uptime_seconds: number | null
  last_seen: string | null
  created_at: string
}

export interface WifiClient {
  id: number
  mac_address: string
  access_point_id: number | null
  radio_id: number | null
  hostname: string | null
  ip_address: string | null
  ssid: string | null
  band: string | null
  protocol: string | null
  rssi_dbm: number | null
  snr_db: number | null
  tx_rate_mbps: number | null
  rx_rate_mbps: number | null
  connected_at: string | null
  last_seen: string
}

export interface ClientEvent {
  id: number
  event_type: string
  from_ap_id: number | null
  to_ap_id: number | null
  details: Record<string, unknown>
  ts: string
}

export interface MetricPoint {
  ts: string
  channel: number | null
  channel_width_mhz: number | null
  tx_power_dbm: number | null
  utilization_pct: number | null
  noise_floor_dbm: number | null
  client_count: number | null
  tx_bytes: number | null
  rx_bytes: number | null
  retry_pct: number | null
  crc_error_pct: number | null
}

export type AlertConditionType = 'ap_down' | 'high_channel_util' | 'low_snr' | 'high_retry_rate' | 'high_client_count' | 'rogue_ap'

export interface AlertRule {
  id: number
  name: string
  condition_type: AlertConditionType
  threshold: number | null
  severity: 'info' | 'warning' | 'critical'
  enabled: boolean
  created_at: string
}

export interface AlertEvent {
  id: number
  rule_id: number | null
  access_point_id: number | null
  client_mac: string | null
  severity: string
  message: string
  value: number | null
  threshold: number | null
  active: boolean
  acked: boolean
  acked_by: string | null
  acked_at: string | null
  resolved: boolean
  auto_resolved: boolean
  resolved_at: string | null
  created_at: string
}

export interface AppLog {
  id: number
  level: string
  logger: string
  message: string
  exc_info: string | null
  created_at: string
}

export interface CollectorType {
  type: string
  label: string
  implemented: boolean
  fields: string[]
}

export interface Collector {
  id: number
  name: string
  collector_type: string
  poll_interval_sec: number
  enabled: boolean
  status: string
  last_poll_at: string | null
  last_error: string | null
  created_at: string
}

export interface Integration {
  app_name: string
  base_url: string
  has_token: boolean
  enabled: boolean
  health_status: string
  last_health_check: string | null
}
