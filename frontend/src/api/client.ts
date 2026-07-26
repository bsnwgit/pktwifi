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
  // Deliberately bypasses request() for the same reason as login() above.
  autoLogin: async () => {
    const res = await fetch('/api/auth/auto-login', { method: 'POST' })
    if (!res.ok) throw new Error('Auto-login not available')
    return res.json() as Promise<{ access_token: string; role: string }>
  },
  logout: () => request('/auth/logout', { method: 'POST' }),
  getAuthConfig: () => request<{ saml_enabled: boolean; local_enabled: boolean }>('/auth/config'),

  // -- Users ---------------------------------------------------------------------
  getMe: () => request<User>('/users/me'),
  getUsers: () => request<User[]>('/users'),
  createUser: (body: UserIn) =>
    request<User>('/users', { method: 'POST', body: JSON.stringify(body) }),
  updateUser: (id: number, body: Partial<UserIn> & { is_active?: boolean }) =>
    request<User>(`/users/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteUser: (id: number) => request(`/users/${id}`, { method: 'DELETE' }),
  setDefaultAdmin: (id: number) => request(`/users/${id}/set-default-admin`, { method: 'PATCH' }),
  resetUserPassword: (id: number, newPassword: string) =>
    request(`/users/${id}/reset-password`, { method: 'PATCH', body: JSON.stringify({ new_password: newPassword }) }),
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
  getAlertEvents: (params?: { active?: boolean; acked?: boolean; limit?: number; since?: string; until?: string }) => {
    const q = new URLSearchParams()
    if (params?.active !== undefined) q.set('active', String(params.active))
    if (params?.acked !== undefined) q.set('acked', String(params.acked))
    if (params?.limit !== undefined) q.set('limit', String(params.limit))
    if (params?.since) q.set('since', params.since)
    if (params?.until) q.set('until', params.until)
    return request<AlertEvent[]>(`/alerts/events?${q}`)
  },
  ackAlertEvent: (id: number) => request(`/alerts/events/${id}/ack`, { method: 'POST' }),
  ackAllAlertEvents: () => request(`/alerts/events/ack-all`, { method: 'POST' }),
  resolveAlertEvent: (id: number) => request(`/alerts/events/${id}/resolve`, { method: 'POST' }),

  // -- Logs ---------------------------------------------------------------------
  getLogs: (params: LogQueryParams) =>
    request<LogResponse>(`/logs?${new URLSearchParams(params as Record<string, string>)}`),
  getLogStats: () => request<LogStats>('/logs/stats'),
  clearLogs: () => request('/logs', { method: 'DELETE' }),
  setLogLevel: (level: string) => request(`/logs/level?level=${level}`, { method: 'POST' }),
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

  // -- Sites ---------------------------------------------------------------------
  getSites: () => request<Site[]>('/sites'),
  createSite: (body: { name: string; description?: string | null }) => request<Site>('/sites', { method: 'POST', body: JSON.stringify(body) }),
  updateSite: (id: number, body: { name: string; description?: string | null }) => request<Site>(`/sites/${id}`, { method: 'PATCH', body: JSON.stringify(body) }),
  deleteSite: (id: number) => request(`/sites/${id}`, { method: 'DELETE' }),

  // -- Integrations (suite-token client of sibling pkt apps) -----------------------
  getIntegrations: () => request<Integration[]>('/integrations'),
  createIntegration: (body: IntegrationInput) =>
    request<Integration>('/integrations', { method: 'POST', body: JSON.stringify(body) }),
  updateIntegration: (id: number, body: Partial<IntegrationInput>) =>
    request<Integration>(`/integrations/${id}`, { method: 'PUT', body: JSON.stringify(body) }),
  deleteIntegration: (id: number) => request(`/integrations/${id}`, { method: 'DELETE' }),
  testIntegration: (id: number) => request<{ healthy: boolean; detail: string }>(`/integrations/${id}/test`, { method: 'POST' }),

  // -- Suite (inbound — pktHub registering this app) --------------------------------
  getSuiteToken: () => request<{ suite_token: string; has_token: boolean }>('/suite/token'),
  regenerateSuiteToken: () => request<{ suite_token: string; status: string }>('/suite/regenerate', { method: 'POST' }),

  // -- Settings ---------------------------------------------------------------------
  getSettings: () => request<Record<string, unknown>>('/settings'),
  updateSettings: (values: Record<string, unknown>) => request('/settings', { method: 'PUT', body: JSON.stringify({ values }) }),
  testNotification: (channel: string) =>
    request<{ status: string; detail?: string }>('/settings/test-notification', {
      method: 'POST',
      body: JSON.stringify({ channel }),
    }),

  // -- System ---------------------------------------------------------------------
  getSystemInfo: () => request<{ version: string; install_dir: string; port: number }>('/system/info'),
  listBackups: () => request<Array<{ name: string; path: string; size_bytes: number; files: string[] }>>('/system/backups'),
  runBackupNow: () => request<{ status: string; path: string; files: string[]; kept: number }>('/system/backups/run', { method: 'POST' }),
  runCleanup: () =>
    request<{ alerts_deleted: number; metrics_deleted: number; alert_retention_days: number; metrics_retention_days: number }>(
      '/system/cleanup', { method: 'POST' }
    ),
  restartService: () => request<{ status: string; message: string }>('/system/restart', { method: 'POST' }),
  getPort: () => request<{ port: number }>('/system/port'),
  setPort: (port: number) =>
    request<{ port: number; message: string }>('/system/port', {
      method: 'POST',
      body: JSON.stringify({ port }),
    }),

  // ── SSL ───────────────────────────────────────────────────────────────────
  getSslStatus: () => request<SslStatus>('/system/ssl/status'),
  uploadSsl: async (cert: File, key: File): Promise<SslStatus> => {
    const formData = new FormData()
    formData.append('cert', cert)
    formData.append('key', key)
    const headers: Record<string, string> = {}
    if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`
    const res = await fetch('/api/system/ssl/upload', { method: 'POST', headers, body: formData })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  },
  deleteSsl: () => request<SslStatus>('/system/ssl/cert', { method: 'DELETE' }),
  uploadSslPfx: async (pfx: File, passphrase: string): Promise<SslStatus> => {
    const formData = new FormData()
    formData.append('pfx', pfx)
    formData.append('passphrase', passphrase)
    const headers: Record<string, string> = {}
    if (_accessToken) headers['Authorization'] = `Bearer ${_accessToken}`
    const res = await fetch('/api/system/ssl/upload-pfx', { method: 'POST', headers, body: formData })
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }))
      throw new Error(err.detail || res.statusText)
    }
    return res.json()
  },

  // ── User API Keys / IP Info ─────────────────────────────────────────────
  getUserApiKeys: () => request<UserApiKey[]>('/user-api-keys'),
  setUserApiKey: (provider: string, api_key: string) =>
    request<UserApiKey>(`/user-api-keys/${provider}`, { method: 'PUT', body: JSON.stringify({ api_key }) }),
  testUserApiKey: (provider: string, api_key: string) =>
    request<{ status: string; detail: string }>(`/user-api-keys/${provider}/test`, { method: 'POST', body: JSON.stringify({ api_key }) }),
  setIpinfoFields: (enabled_fields: string[]) =>
    request<UserApiKey>('/user-api-keys/ipinfo/fields', { method: 'PUT', body: JSON.stringify({ enabled_fields }) }),
  setIpapiIsFields: (enabled_fields: string[]) =>
    request<UserApiKey>('/user-api-keys/ipapi_is/fields', { method: 'PUT', body: JSON.stringify({ enabled_fields }) }),
  setIpapiIsFreeTier: (free_tier: boolean) =>
    request<UserApiKey>('/user-api-keys/ipapi_is/free-tier', { method: 'PUT', body: JSON.stringify({ free_tier }) }),
  setMxtoolboxFields: (enabled_fields: string[]) =>
    request<UserApiKey>('/user-api-keys/mxtoolbox/fields', { method: 'PUT', body: JSON.stringify({ enabled_fields }) }),
  setProviderEnabled: (provider: string, enabled: boolean) =>
    request<UserApiKey>(`/user-api-keys/${provider}/enabled`, { method: 'PUT', body: JSON.stringify({ enabled }) }),
  getIpInfo: (ip: string) => request<IpInfoResult>(`/ip-info/${ip}`),
  getInternalIpInfo: (ip: string) => request<InternalIpInfoResult>(`/ip-info/internal/${ip}`),
}

export interface SslStatus {
  installed: boolean
  expires?: string
  expires_iso?: string
  days_until_expiry?: number
  subject?: string
  issuer?: string
  error?: string
  status?: string
}

// -- Types -----------------------------------------------------------------------

export interface UserIn {
  username: string
  email: string
  password?: string
  role: string
}

export interface UserApiKey {
  provider: string
  label: string
  api_key: string
  updated_at: string | null
  enabled_fields: string[] | null // ipinfo/ipapi_is/mxtoolbox only; null = not customized (all shown)
  free_tier: boolean // ipapi_is only — use its keyless free tier instead of api_key
  enabled: boolean // ipinfo/ipapi_is/abuseipdb/mxtoolbox only — show this provider's section in the IP Lookup modal at all
}

export interface IpInfoResult {
  ip: string
  ipinfo: Record<string, any> | null
  ipinfo_error: string | null
  ipinfo_enabled_fields: string[] | null
  ipinfo_enabled: boolean
  ipapi_is: Record<string, any> | null
  ipapi_is_error: string | null
  ipapi_is_enabled_fields: string[] | null
  ipapi_is_enabled: boolean
  abuseipdb: Record<string, any> | null
  abuseipdb_error: string | null
  abuseipdb_enabled: boolean
  mxtoolbox: Record<string, any> | null
  mxtoolbox_error: string | null
  mxtoolbox_enabled_fields: string[] | null
  mxtoolbox_enabled: boolean
}

export interface InternalIpInfoResult {
  ip: string
  configured: boolean
  found: boolean
  error: string | null
  subnet: { cidr: string; vlan_id: number | null; site: string | null; description: string | null; gateway: string | null } | null
  ip_address: { status: string; mac_address: string | null; hostname: string | null; description: string | null; owner: string | null; tags: string[] } | null
  dhcp_leases: { mac_address: string | null; hostname: string | null; state: string; starts_at: string | null; ends_at: string | null; last_seen: string }[]
  dns_records: { zone: string; name: string; record_type: string; ttl: number | null; last_seen: string }[]
  arp_entries: { device_label: string | null; mac_address: string | null; interface: string | null; vlan_tag: number | null; last_seen: string }[]
}

export interface User {
  id: number
  username: string
  email: string
  role: string
  is_active: boolean
  is_default_admin: boolean
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

export interface LogRecord {
  id: number
  ts: string
  level: string
  level_no: number
  logger: string
  message: string
  exc_info: string | null
}

export interface LogResponse {
  total: number
  limit: number
  offset: number
  records: LogRecord[]
}

export interface LogStats {
  total: number
  by_level: Record<string, number>
  loggers: string[]
  latest_ts: string | null
  capture_level?: string
}

export type LogQueryParams = {
  level?: string
  logger?: string
  search?: string
  since?: string
  until?: string
  limit?: string
  offset?: string
}

export type FieldType = 'text' | 'password' | 'number' | 'toggle' | 'select' | 'multiselect' | 'string_list' | 'host_list' | 'site_select'

export interface FieldOption {
  value: string
  label: string
}

export interface FieldShowIf {
  key: string
  equals: string
}

export interface FieldSchema {
  key: string
  label: string
  type: FieldType
  required?: boolean
  placeholder?: string
  help?: string
  default?: unknown
  options?: FieldOption[]        // select | multiselect
  sub_fields?: FieldSchema[]     // host_list — columns per row
  item_placeholder?: string      // string_list
  show_if?: FieldShowIf          // only render when another field in the same form equals a value
}

export interface Site {
  id: number
  name: string
  description: string | null
  created_at: string
}

export interface CollectorType {
  type: string
  label: string
  implemented: boolean
  fields: FieldSchema[]
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
  id: number
  name: string
  app_name: string
  base_url: string
  has_token: boolean
  enabled: boolean
  health_status: string
  last_health_check: string | null
}

export interface IntegrationInput {
  name: string
  app_name?: string
  base_url: string
  suite_token: string
  enabled?: boolean
}
