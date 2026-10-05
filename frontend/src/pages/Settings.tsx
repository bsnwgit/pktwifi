import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Collector,
  Integration,
  User,
  api,
} from '../api/client'
import HelpButton from '../components/HelpButton'
import { useAuth } from '../store/auth'
import { BrandLockup } from '../components/Brand'
import { ApiKeysTab } from './settings/ApiKeysTab'
import { ControllersTab } from './settings/ControllersTab'
import { CredentialsTab } from './settings/CredentialsTab'
import { SiblingIntegrations } from './settings/Integrations'
import { SitesTab } from './settings/SitesTab'
import { SslPanel } from './settings/SslPanel'
import { UsersTab } from './settings/UsersTab'
import { CertTextarea, LogForwardTester, MetadataPasteBox, PortField, ResonanceDiagnostics, ResonanceOriginField, RestartServiceRow, SendTestButton, SnapshotRestoreRow, SuiteTokenDisplay } from './settings/panels'
import { Field, NumberInput, Section, SelectInput, SettingsMap, TextInput, Toggle, useSave } from './settings/shared'

// -- Main page ---------------------------------------------------------------------
type TabId = 'general' | 'security' | 'data' | 'notifications' | 'resonance' | 'apikeys' | 'controllers' | 'credentials' | 'sites' | 'system'

// Tabs before gapBefore are the suite-common set every pkt app shares and make
// up the "Common" section; gapBefore and everything after it are
// pktWiFi-specific and make up the "pktWiFi" section: Controllers (the WiFi
// controller connections that used to be the top-level Collectors page) and
// Credentials (the named auth library those controller configs reference).
const TABS: Array<{ id: TabId; label: string; adminOnly?: boolean; gapBefore?: boolean }> = [
  { id: 'general',       label: 'General' },
  { id: 'security',      label: 'Security' },
  { id: 'data',          label: 'Data' },
  { id: 'notifications', label: 'Notifications' },
  { id: 'resonance',     label: 'Resonance', adminOnly: true },
  { id: 'apikeys',       label: 'User Keys' },
  { id: 'system',        label: 'System' },
  { id: 'controllers',   label: 'Controllers', adminOnly: true, gapBefore: true },
  { id: 'credentials',   label: 'Credentials', adminOnly: true },
  { id: 'sites',         label: 'Sites', adminOnly: true },
]

// ── Top-level sections — Common holds the tabs that used to sit left of the
// divider (gapBefore); the app-specific section holds gapBefore and everything
// after it. Split point is derived from TABS itself, not duplicated here.
type SectionId = 'common' | 'app'

const APP_SECTION_LABEL = 'pktWiFi'

const FIRST_APP_TAB_INDEX = TABS.findIndex(t => t.gapBefore)

const sectionOfTab = (id: TabId): SectionId => {
  const idx = TABS.findIndex(t => t.id === id)
  return idx >= 0 && idx < FIRST_APP_TAB_INDEX ? 'common' : 'app'
}

// ── Open-source packages actually used by this app (requirements.txt +
// frontend/package.json), for the System tab's Licenses & Copyright card ──
const OSS_NOTICES: Array<{ name: string; license: string }> = [
  { name: 'FastAPI',            license: 'MIT' },
  { name: 'Uvicorn',            license: 'BSD-3-Clause' },
  { name: 'python-multipart',   license: 'Apache-2.0' },
  { name: 'Pydantic',           license: 'MIT' },
  { name: 'aiosqlite',          license: 'MIT' },
  { name: 'python-jose',        license: 'MIT' },
  { name: 'passlib',            license: 'BSD-2-Clause' },
  { name: 'httpx',              license: 'BSD-3-Clause' },
  { name: 'python3-saml',       license: 'MIT' },
  { name: 'cryptography',       license: 'Apache-2.0 / BSD-3-Clause' },
  { name: 'PyYAML',             license: 'MIT' },
  { name: 'python-dotenv',      license: 'BSD-3-Clause' },
  { name: 'aiosmtplib',         license: 'MIT' },
  { name: 'Jinja2',             license: 'BSD-3-Clause' },
  { name: 'pysnmp-lextudio',    license: 'BSD-2-Clause' },
  { name: 'python-dateutil',    license: 'BSD / Apache-2.0' },
  { name: 'React',              license: 'MIT' },
  { name: 'React DOM',          license: 'MIT' },
  { name: 'React Router',       license: 'MIT' },
  { name: 'Recharts',           license: 'MIT' },
  { name: 'clsx',               license: 'MIT' },
  { name: 'Vite',               license: 'MIT' },
  { name: 'Tailwind CSS',       license: 'MIT' },
  { name: 'TypeScript',         license: 'Apache-2.0' },
]

// -- Security tab — its own left-hand vertical tab strip --------------------------
// No SSL/TLS sub-tab: that feature doesn't exist in pktWiFi yet.
// Suite Integration bundles both directions: the inbound Suite Token (pktHub
// calling into pktWiFi) and the outbound Sibling pkt Apps connections
// (pktWiFi calling into pktsnmp/pktflow/pktlog/pktpcap) — same pairing the
// old Integrations tab already had, just relocated as one unit.
type SecurityTabId = 'users' | 'auth' | 'suite' | 'ssl'

const SECURITY_TABS: Array<{ id: SecurityTabId; label: string; adminOnly?: boolean }> = [
  { id: 'users', label: 'Users', adminOnly: true },
  { id: 'auth',  label: 'Auth' },
  { id: 'suite', label: 'Suite Integration' },
  { id: 'ssl',   label: 'SSL / TLS' },
]

// -- Data tab — its own left-hand vertical tab strip -------------------------------
// Backups only: no storage-backend picker exists in pktWiFi yet (SQLite only).
type DataTabId = 'storage' | 'backups' | 'logforward'

const DATA_TABS: Array<{ id: DataTabId; label: string }> = [
  { id: 'storage', label: 'Storage' },
  { id: 'backups', label: 'Backups' },
  { id: 'logforward', label: 'Log Forwarding' },
]

export default function Settings() {
  // Settings is a desk surface — dense configuration grids and the widest
  // tables in the app. Below md it says so rather than collapsing badly,
  // but it does not lock the door: anything might matter at 2am.
  const [showOnPhone, setShowOnPhone] = useState(false)
  const { user: me } = useAuth()
  const isAdmin = me?.role === 'admin'
  // Deep-link support: /settings?tab=<id>. Accepts the current top-level tab
  // ids plus legacy pre-reorg ids (integrations/auth/users/ai/backup) so older
  // links keep working — IpLink still navigates to ?tab=integrations for the
  // Suite Integration pane, which now lives under Security.
  const [searchParams] = useSearchParams()
  const deepLink = ((): { tab: TabId; security?: SecurityTabId; data?: DataTabId } => {
    switch (searchParams.get('tab')) {
      case 'security': case 'data': case 'notifications': case 'apikeys':
      case 'controllers': case 'credentials': case 'sites': case 'system':
        return { tab: searchParams.get('tab') as TabId }
      case 'collectors':   return { tab: 'controllers' }
      case 'integrations': return { tab: 'security', security: 'suite' }
      case 'auth':         return { tab: 'security', security: 'auth' }
      case 'users':        return { tab: 'security', security: 'users' }
      case 'backup':       return { tab: 'data', data: 'backups' }
      default:             return { tab: 'general' }
    }
  })()
  const [tab, setTab] = useState<TabId>(deepLink.tab)
  const [section, setSection] = useState<SectionId>(sectionOfTab(deepLink.tab))
  const selectSection = (s: SectionId) => {
    setSection(s)
    const firstVisible = TABS.filter(t => !t.adminOnly || isAdmin).find(t => sectionOfTab(t.id) === s)
    if (firstVisible) setTab(firstVisible.id)
  }
  const [securityTab, setSecurityTab] = useState<SecurityTabId>(deepLink.security ?? (isAdmin ? 'users' : 'auth'))
  const [dataTab, setDataTab] = useState<DataTabId>(deepLink.data ?? 'storage')
  const [settings, setSettings] = useState<SettingsMap>({})
  const [loading, setLoading] = useState(true)
  const dirtyRef = useRef(false)

  const load = async () => {
    setLoading(true)
    try { setSettings(await api.getSettings()) } finally { setLoading(false); dirtyRef.current = false }
  }
  useEffect(() => { load() }, [])

  const set = (key: string, value: unknown) => { dirtyRef.current = true; setSettings(s => ({ ...s, [key]: value })) }
  const str  = (k: string, fallback = '') => (settings[k] as string) ?? fallback
  const num  = (k: string, fallback = 0)  => (settings[k] as number) ?? fallback
  const bool = (k: string, fallback = false) => (settings[k] as boolean) ?? fallback


  // Don't show the "remotely managed" lockout when pktHub itself is the one
  // viewing this page (via the proxy embed) — only for a real direct visit.
  const hubManaged = bool('hub_settings_managed', false) && me?.authProvider !== 'suite'

  // General tab's Port field lives in config.yaml (not the SQLite settings
  // blob) so it needs its own fetch, but saves through the same one button.
  const [portValue, setPortValue]   = useState(0)
  const [portLoaded, setPortLoaded] = useState(false)
  useEffect(() => {
    api.getPort().then((r: { port: number }) => setPortValue(r.port)).catch(() => {}).finally(() => setPortLoaded(true))
  }, [])

  const [generalSaving, setGeneralSaving] = useState(false)
  const [generalSaved, setGeneralSaved]   = useState(false)
  const [generalError, setGeneralError]   = useState('')

  const saveGeneral = async () => {
    if (portValue < 1 || portValue > 65535) { setGeneralError('Enter a port between 1 and 65535'); return }
    setGeneralSaving(true); setGeneralSaved(false); setGeneralError('')
    try {
      const subset: SettingsMap = {}
      for (const k of ['app_name', 'base_url', 'timezone']) if (k in settings) subset[k] = settings[k]
      await api.updateSettings(subset)
      await api.setPort(portValue)
      await load()
      setGeneralSaved(true)
      setTimeout(() => setGeneralSaved(false), 3000)
    } catch (e: any) {
      setGeneralError(e.message || 'Save failed')
    } finally {
      setGeneralSaving(false)
    }
  }
  const authSave = useSave([
    'auth_local_enabled', 'session_timeout_minutes', 'login_max_failed_attempts',
    'okta_saml_enabled', 'okta_saml_idp_entity_id', 'okta_saml_idp_sso_url',
    'okta_saml_idp_cert', 'okta_saml_sp_entity_id', 'okta_saml_sp_cert', 'okta_saml_sp_key',
  ], settings, load)
  const storageSave = useSave(['alert_event_retention_days', 'radio_metrics_retention_days', 'client_event_retention_days'], settings, load)
  const logForwardSave = useSave([
    'log_forward_enabled', 'log_forward_host', 'log_forward_port',
    'log_forward_protocol', 'log_forward_level', 'log_forward_app_name',
  ], settings, load)
  const backupSave = useSave(['backup_enabled', 'backup_interval_hours', 'backup_rotation_count', 'backup_path'], settings, load)
  const lucidSave = useSave(['lucid_api_token'], settings, load)
  const resonanceSave = useSave([
    'resonance_enabled', 'resonance_base_url', 'resonance_key', 'resonance_role_levels',
    'resonance_origin', 'resonance_ca_bundle',
    'resonance_style', 'resonance_target', 'resonance_label', 'resonance_side',
    'resonance_width', 'resonance_height', 'resonance_open', 'resonance_exclude_paths',
  ], settings, load)
  // What each role may do with the assistant. Anything unrecognised reads as
  // 'none', matching the server, so a hand-edited value fails closed here too.
  const RESONANCE_DEFAULT_LEVELS = { admin: 'read', analyst: 'read', viewer: 'read' }
  const resonanceLevels =
    (settings['resonance_role_levels'] as Record<string, string>) ?? RESONANCE_DEFAULT_LEVELS
  const resonanceLevel = (role: string) => {
    const level = resonanceLevels[role]
    return level === 'read' || level === 'write' ? level : 'none'
  }
  const setResonanceLevel = (role: string, level: string) =>
    set('resonance_role_levels', { ...resonanceLevels, [role]: level })

  const notifySave = useSave([
    'notify_slack_enabled', 'notify_slack_webhook_url', 'notify_slack_channel',
    'notify_email_enabled', 'notify_email_smtp_host', 'notify_email_smtp_port',
    'notify_email_smtp_tls', 'notify_email_username', 'notify_email_password',
    'notify_email_from', 'notify_email_default_to',
    'notify_pagerduty_enabled', 'notify_pagerduty_integration_key',
    'notify_webhook_enabled', 'notify_webhook_url',
    'notify_webhook_method', 'notify_webhook_payload_template',
    'notify_tracecat_enabled', 'notify_tracecat_webhook_url', 'notify_tracecat_api_token',
  ], settings, load)

  const [backupRunning, setBackupRunning] = useState(false)
  const [backupResult, setBackupResult] = useState<string | null>(null)
  const [backups, setBackups] = useState<Array<{ name: string; path: string; size_bytes: number; files: string[] }>>([])
  const [backupsLoaded, setBackupsLoaded] = useState(false)
  const [snapshotRestoreResult, setSnapshotRestoreResult] = useState<{ name: string; result: Record<string, string> } | null>(null)
  const ALL_BUNDLE_FILES = ['pktwifi.db', 'config.yaml']
  const [importFiles, setImportFiles] = useState<Set<string>>(new Set(ALL_BUNDLE_FILES))
  const [importFile, setImportFile] = useState<File | null>(null)
  const [importRunning, setImportRunning] = useState(false)
  const [importResult, setImportResult] = useState<Record<string, string> | null>(null)
  const [importError, setImportError] = useState<string | null>(null)
  const [exportRunning, setExportRunning] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  // Step-up re-auth before the bundle is generated — it carries config.yaml,
  // i.e. the key to every encrypted secret in the database, alongside it.
  const [exportPrompt, setExportPrompt] = useState(false)
  const [exportPassword, setExportPassword] = useState('')
  const [systemInfo, setSystemInfo] = useState<{
    app_name: string; version: string; install_dir: string
    github: string; license: string; developer: string; contact: string
  } | null>(null)

  useEffect(() => { api.getSystemInfo().then(setSystemInfo).catch(() => {}) }, [])

  const runBackupNow = async () => {
    setBackupRunning(true)
    setBackupResult(null)
    try {
      const r = await api.runBackupNow()
      setBackupResult(`Saved to ${r.path} — ${r.files.join(', ')}`)
      setBackups(await api.listBackups())
      setBackupsLoaded(true)
    } catch (e: any) {
      setBackupResult(`Error: ${e.message}`)
    } finally { setBackupRunning(false) }
  }
  const loadBackups = async () => {
    try { setBackups(await api.listBackups()); setBackupsLoaded(true) } catch {}
  }

  const runImport = async () => {
    if (!importFile) return
    setImportRunning(true)
    setImportResult(null)
    setImportError(null)
    try {
      const result = await api.importBundle(importFile, Array.from(importFiles))
      setImportResult(result)
    } catch (e: any) {
      setImportError(e.message || 'Import failed')
    } finally { setImportRunning(false) }
  }

  const runExport = async () => {
    setExportRunning(true)
    setExportError(null)
    try {
      const { blob, filename } = await api.exportConfig(exportPassword)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
      setExportPrompt(false)
      setExportPassword('')
    } catch (e: any) {
      setExportError(e.message || 'Export failed')
    } finally { setExportRunning(false) }
  }

  const [cleanupRunning, setCleanupRunning] = useState(false)
  const [cleanupResult, setCleanupResult] = useState<string | null>(null)
  const runCleanup = async () => {
    setCleanupRunning(true)
    setCleanupResult(null)
    try {
      const r = await api.runCleanup()
      const parts: string[] = []
      parts.push(r.alerts_deleted > 0 ? `${r.alerts_deleted} resolved alert(s) removed` : 'No alerts beyond retention threshold')
      parts.push(r.metrics_deleted > 0 ? `${r.metrics_deleted} RF metric row(s) removed` : 'No RF metrics beyond retention threshold')
      parts.push(r.client_events_deleted > 0 ? `${r.client_events_deleted} client event(s) removed` : 'No client events beyond retention threshold')
      setCleanupResult(parts.join(' · '))
    } catch (e: any) {
      setCleanupResult(`Error: ${e.message}`)
    } finally { setCleanupRunning(false) }
  }

  if (loading) {
    return <div className="flex items-center justify-center h-48 text-white"><p className="text-sm">Loading settings…</p></div>
  }

  return (
    <>
      {!showOnPhone && (
        <div className="md:hidden f-panel p-6 text-center space-y-3">
          <p className="f-lbl">Settings</p>
          <p className="text-sm text-white leading-relaxed">
            This page is built for a larger screen — dense configuration grids and
            the widest tables in the app.
          </p>
          <button onClick={() => setShowOnPhone(true)} className="f-chip f-chip-gold f-tap px-3">
            Show anyway
          </button>
        </div>
      )}

      <div className={showOnPhone ? 'space-y-4' : 'hidden md:block space-y-4'}>
      <h1 className="text-xl font-bold text-white">pktWiFi - Settings</h1>

      <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 rounded-xl p-1 w-fit">
        <button onClick={() => selectSection('common')}
          className={`text-sm px-4 py-1.5 rounded-lg whitespace-nowrap transition-colors ${section === 'common' ? 'bg-gray-700 text-white' : 'text-white hover:text-white'}`}>
          Common
        </button>
        {TABS.some(t => (!t.adminOnly || isAdmin) && sectionOfTab(t.id) === 'app') && (
          <button onClick={() => selectSection('app')}
            className={`text-sm px-4 py-1.5 rounded-lg whitespace-nowrap transition-colors ${section === 'app' ? 'bg-gray-700 text-white' : 'text-white hover:text-white'}`}>
            {APP_SECTION_LABEL}
          </button>
        )}
      </div>

      <div className="flex items-center gap-1 bg-gray-900 border border-gray-800 rounded-xl p-1 w-fit overflow-x-auto">
        {TABS.filter(t => (!t.adminOnly || isAdmin) && sectionOfTab(t.id) === section).map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`text-sm px-4 py-1.5 rounded-lg whitespace-nowrap transition-colors ${tab === t.id ? 'bg-gray-700 text-white' : 'text-white hover:text-white'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {hubManaged && (
        <div className="flex items-center gap-2 px-4 py-2.5 rounded-lg border border-amber-800/40 bg-amber-900/20 text-amber-300 text-sm">
          <span className="font-semibold">Remotely Managed</span>
          <span className="text-amber-300/80">— this app is registered with pktHub, which now controls Settings. Make changes from pktHub instead.</span>
        </div>
      )}

      <div className={hubManaged ? 'opacity-40 pointer-events-none select-none' : undefined}>

      {tab === 'general' && (
        <Section title="General" onSave={saveGeneral} saving={generalSaving} saved={generalSaved} error={generalError}
          help={{
            title: 'General — How It Works',
            content: <>
              <p><span className="text-gray-300 font-medium">Base URL</span> feeds the SAML ACS/metadata URLs on the Auth tab — set it to the actual externally-reachable address before configuring SSO, or those will point at the wrong place.</p>
              <p><span className="text-gray-300 font-medium">Port</span> only takes effect after a restart. Changing it moves the app to a new URL; the browser won't follow automatically.</p>
            </>,
          }}
        >
          <Field label="App name" hint="Displayed in browser tab and header">
            <TextInput value={str('app_name', 'pktWiFi')} onChange={v => set('app_name', v)} />
          </Field>
          <Field label="Timezone" hint="Affects display of timestamps in the UI">
            <SelectInput
              value={str('timezone', 'UTC')}
              onChange={v => set('timezone', v)}
              options={[
                { value: 'UTC', label: 'UTC' },
                { value: 'America/New_York', label: 'Eastern (ET)' },
                { value: 'America/Chicago', label: 'Central (CT)' },
                { value: 'America/Denver', label: 'Mountain (MT)' },
                { value: 'America/Los_Angeles', label: 'Pacific (PT)' },
              ]}
            />
          </Field>
          <PortField value={portValue} onChange={setPortValue} loaded={portLoaded} />
          <Field label="Base URL" hint="Used for SAML redirect URIs">
            <TextInput value={str('base_url')} onChange={v => set('base_url', v)} placeholder="http://SERVER-IP:8769" />
          </Field>
          <RestartServiceRow />
        </Section>
      )}

      {/* Security */}
      {tab === 'security' && (
        <div className="flex gap-4 items-start">
          <div className="flex flex-col gap-1.5 w-48 flex-shrink-0">
            {SECURITY_TABS.filter(st => !st.adminOnly || isAdmin).map(st => (
              <button
                key={st.id}
                onClick={() => setSecurityTab(st.id)}
                className={`text-sm px-4 py-2 rounded-lg border text-left whitespace-nowrap transition-colors ${
                  securityTab === st.id
                    ? 'bg-gray-800 border-sky-500 text-white'
                    : 'bg-gray-900 border-gray-800 text-white hover:border-gray-600'
                }`}
              >
                {st.label}
              </button>
            ))}
          </div>

          <div className="flex-1 min-w-0">
            {securityTab === 'users' && isAdmin && <UsersTab />}

            {securityTab === 'auth' && (
              <Section title="Authentication" onSave={authSave.save} saving={authSave.saving} saved={authSave.saved} error={authSave.error}
                help={{
                  title: 'Authentication — How It Works',
                  content: <>
                    <p><span className="text-gray-300 font-medium">Local auth</span> and <span className="text-gray-300 font-medium">SAML SSO</span> aren't mutually exclusive — both can be on at once.</p>
                    <p>SAML users are <span className="text-gray-300 font-medium">auto-provisioned</span> on first successful login — no separate "create user" step.</p>
                    <p>Paste your IdP's metadata XML to auto-fill the fields below, then register the <span className="text-gray-300 font-medium">ACS URL</span> shown here as the Single Sign-On URL in your IdP. Both the ACS URL and SP metadata link derive from <span className="text-gray-300 font-medium">Base URL</span> on the General tab — set that correctly first.</p>
                  </>,
                }}
              >
                <Field label="Local auth" hint="Username/password login using local accounts">
                  <Toggle value={bool('auth_local_enabled', true)} onChange={v => set('auth_local_enabled', v)} />
                </Field>
                <Field label="Session timeout">
                  <div className="flex items-center gap-3">
                    <NumberInput value={num('session_timeout_minutes', 480)} onChange={v => set('session_timeout_minutes', v)} min={5} max={10080} />
                    <span className="text-sm text-white">minutes</span>
                  </div>
                </Field>
                <Field label="Failed logins before lockout" hint="Consecutive failures that lock an account: 30 minutes the first time, until an admin unlocks it the second time. Applies to local accounts">
                  <div className="flex items-center gap-3">
                    <NumberInput value={num('login_max_failed_attempts', 3)} onChange={v => set('login_max_failed_attempts', v)} min={1} max={100} />
                    <span className="text-sm text-white">attempts</span>
                  </div>
                </Field>

                <div className="pt-4 pb-2">
                  <p className="text-xs font-semibold text-white uppercase tracking-wider">SAML 2.0 SSO</p>
                </div>
                <Field label="Enable SAML SSO">
                  <Toggle value={bool('okta_saml_enabled')} onChange={v => set('okta_saml_enabled', v)} />
                </Field>
                {bool('okta_saml_enabled') && (
                  <>
                    <Field label="Paste IdP Metadata XML" hint="Paste the full XML from your IdP's SAML app configuration. Fields below will auto-fill.">
                      <MetadataPasteBox onParsed={r => {
                        if (r.entity_id) set('okta_saml_idp_entity_id', r.entity_id)
                        if (r.sso_url) set('okta_saml_idp_sso_url', r.sso_url)
                        if (r.cert) set('okta_saml_idp_cert', r.cert)
                      }} />
                    </Field>
                    <Field label="IdP Entity ID">
                      <TextInput value={str('okta_saml_idp_entity_id')} onChange={v => set('okta_saml_idp_entity_id', v)} placeholder="https://idp.example.com/..." mono />
                    </Field>
                    <Field label="IdP SSO URL">
                      <TextInput value={str('okta_saml_idp_sso_url')} onChange={v => set('okta_saml_idp_sso_url', v)} placeholder="https://idp.example.com/sso/saml" mono />
                    </Field>
                    <Field label="IdP X.509 Certificate" hint="PEM headers are stripped automatically">
                      <CertTextarea value={str('okta_saml_idp_cert')} onChange={v => set('okta_saml_idp_cert', v)} rows={4} secret />
                    </Field>
                    <Field label="SP Entity ID" hint="Leave blank to use the auto-generated metadata URL">
                      <TextInput value={str('okta_saml_sp_entity_id')} onChange={v => set('okta_saml_sp_entity_id', v)} placeholder={`${str('base_url')}/api/auth/saml/metadata`} mono />
                    </Field>
                    <Field label="ACS URL (read-only)" hint="Register this URL as the Single Sign-On URL in your IdP">
                      <div className="flex items-center gap-2">
                        <input readOnly value={`${str('base_url')}/api/auth/saml/callback`}
                          className="flex-1 bg-gray-900 border border-gray-700 rounded-lg px-3 py-2 text-sm text-gray-400 font-mono cursor-default" />
                        <a href={`${str('base_url')}/api/auth/saml/metadata`} target="_blank" rel="noreferrer"
                          className="text-xs text-sky-400 hover:text-sky-300 whitespace-nowrap">View SP metadata ↗</a>
                      </div>
                    </Field>
                    <Field label="SP Certificate" hint="Optional: for signed authentication requests">
                      <CertTextarea value={str('okta_saml_sp_cert')} onChange={v => set('okta_saml_sp_cert', v)} rows={3} placeholder="Leave blank if not signing requests" secret />
                    </Field>
                    <Field label="SP Private Key" hint="Optional: private key for signing requests (kept secret)">
                      <CertTextarea value={str('okta_saml_sp_key')} onChange={v => set('okta_saml_sp_key', v)} rows={3} placeholder="Leave blank if not signing requests" secret />
                    </Field>
                  </>
                )}
              </Section>
            )}

            {securityTab === 'suite' && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-800 flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-white">Suite Integration</h2>
                  <HelpButton title="Suite Integration — How It Works">
                    <p><span className="text-gray-300 font-medium">Suite Token</span> is one-directional discovery: copy it into pktHub's App Manager when registering this app, so pktHub can proxy into it with users already signed in.</p>
                    <p><span className="text-gray-300 font-medium">Sibling pkt apps</span> below is the other direction: pktWiFi calling into pktsnmp/pktflow/pktlog/pktpcap to reuse data they've already collected. Paste each app's own suite token (from that app's Settings → Security → Suite Integration) here.</p>
                  </HelpButton>
                </div>
                <div className="px-6 py-2">
                  <SuiteTokenDisplay />
                  <div className="pt-4 pb-1">
                    <p className="text-xs font-semibold text-white uppercase tracking-wider">Sibling pkt Apps</p>
                  </div>
                  <SiblingIntegrations />
                </div>
              </div>
            )}

            {securityTab === 'ssl' && (
              <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-800 flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-white">SSL / TLS</h2>
                  <HelpButton title="SSL/TLS — How It Works">
                    <p>Accepts either a combined PFX/P12 file or a separate PEM cert+key pair — the running service auto-detects and loads whichever was uploaded at startup.</p>
                  </HelpButton>
                </div>
                <div className="px-6 py-4">
                  <SslPanel />
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Data */}
      {tab === 'data' && (
        <div className="flex gap-4 items-start">
          <div className="flex flex-col gap-1.5 w-48 flex-shrink-0">
            {DATA_TABS.map(dt => (
              <button
                key={dt.id}
                onClick={() => setDataTab(dt.id)}
                className={`text-sm px-4 py-2 rounded-lg border text-left whitespace-nowrap transition-colors ${
                  dataTab === dt.id
                    ? 'bg-gray-800 border-sky-500 text-white'
                    : 'bg-gray-900 border-gray-800 text-white hover:border-gray-600'
                }`}
              >
                {dt.label}
              </button>
            ))}
          </div>

          <div className="flex-1 min-w-0">
      {dataTab === 'storage' && (
        <Section title="Storage" onSave={storageSave.save} saving={storageSave.saving} saved={storageSave.saved} error={storageSave.error}
          help={{
            title: 'Storage — How It Works',
            content: <>
              <p>pktWiFi stores everything in <span className="text-gray-300 font-medium">SQLite</span> — there's no separate analytical backend to choose here, unlike some sibling apps.</p>
              <p>Retention windows control how long resolved alerts, client events and raw RF metric history stick around before a background job deletes them. <span className="text-gray-300 font-medium">Manual cleanup</span> applies the current thresholds immediately instead of waiting for the next scheduled pass (once daily).</p>
            </>,
          }}
        >
          <Field label="Alert event retention" hint="Days to keep resolved alert events">
            <div className="flex items-center gap-3">
              <NumberInput value={num('alert_event_retention_days', 90)} onChange={v => set('alert_event_retention_days', v)} min={1} max={3650} />
              <span className="text-sm text-white">days</span>
            </div>
          </Field>
          <Field label="RF metrics retention" hint="Days to keep raw radio/RF metric history">
            <div className="flex items-center gap-3">
              <NumberInput value={num('radio_metrics_retention_days', 30)} onChange={v => set('radio_metrics_retention_days', v)} min={1} max={3650} />
              <span className="text-sm text-white">days</span>
            </div>
          </Field>
          <Field label="Client event retention" hint="Days to keep client associate, roam and auth-failure events">
            <div className="flex items-center gap-3">
              <NumberInput value={num('client_event_retention_days', 90)} onChange={v => set('client_event_retention_days', v)} min={1} max={3650} />
              <span className="text-sm text-white">days</span>
            </div>
          </Field>
          <Field label="Manual cleanup" hint="Immediately apply current retention settings">
            <div className="flex items-center gap-3 flex-wrap">
              <button onClick={runCleanup} disabled={cleanupRunning}
                className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                {cleanupRunning ? 'Running…' : 'Run Cleanup Now'}
              </button>
              {cleanupResult && (
                <span className={`text-xs ${cleanupResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>
                  {cleanupResult}
                </span>
              )}
            </div>
          </Field>
        </Section>
      )}

      {dataTab === 'logforward' && (
        <Section title="Log Forwarding" onSave={logForwardSave.save} saving={logForwardSave.saving} saved={logForwardSave.saved} error={logForwardSave.error}
          help={{
            title: 'Log Forwarding — How It Works',
            content: <>
              <p>Ships pktWiFi's own application log to a syslog collector — normally <span className="text-gray-300 font-medium">pktLog</span>, which listens on port <code className="text-gray-400">5514</code> — so this app's logs sit alongside the rest of the estate instead of only in its local Logs page.</p>
              <p>Messages are sent as <span className="text-gray-300 font-medium">RFC 5424</span>. pktLog also parses RFC 3164, but 3164 timestamps carry no timezone and the collector has to guess the offset; 5424 carries a full offset so there is nothing to guess.</p>
              <p>Delivery is fire-and-forget on a background thread — if the collector is unreachable, lines are dropped and counted rather than blocking or crashing pktWiFi. Use <span className="text-gray-300 font-medium">Send test message</span> to confirm the path end to end.</p>
              <p><span className="text-amber-500 font-medium">pktLog drops syslog from unregistered sources.</span> This host's IP must also be present and enabled under pktLog's Settings → Collectors, or the messages are accepted on the wire and silently discarded.</p>
              <p>Local logging is unaffected: records continue to be written to the in-app Logs page regardless of this setting.</p>
            </>,
          }}
        >
          <Field label="Forward app logs" hint="Send this app's log records to a syslog collector (e.g. pktLog)">
            <Toggle value={bool('log_forward_enabled')} onChange={v => set('log_forward_enabled', v)} />
          </Field>
          <Field label="Collector host" hint="Hostname or IP of the pktLog / syslog collector">
            <TextInput value={str('log_forward_host')} onChange={v => set('log_forward_host', v)} placeholder="10.0.0.10" />
          </Field>
          <Field label="Port" hint="pktLog listens on 5514 by default">
            <NumberInput value={num('log_forward_port', 5514)} onChange={v => set('log_forward_port', v)} min={1} max={65535} />
          </Field>
          <Field label="Protocol" hint="UDP is fire-and-forget; TCP confirms delivery to the collector">
            <SelectInput value={str('log_forward_protocol') || 'udp'} onChange={v => set('log_forward_protocol', v)}
                    options={[{ value: 'udp', label: 'UDP' }, { value: 'tcp', label: 'TCP' }]} />
          </Field>
          <Field label="Minimum level" hint="Records below this level are not forwarded">
            <SelectInput value={str('log_forward_level') || 'INFO'} onChange={v => set('log_forward_level', v)}
                    options={[
                      { value: 'DEBUG', label: 'Debug' }, { value: 'INFO', label: 'Info' },
                      { value: 'WARNING', label: 'Warning' }, { value: 'ERROR', label: 'Error' },
                    ]} />
          </Field>
          <Field label="Application name" hint="Appears as the APP-NAME field in the syslog message">
            <TextInput value={str('log_forward_app_name') || 'pktwifi'} onChange={v => set('log_forward_app_name', v)} placeholder="pktwifi" />
          </Field>
          <LogForwardTester
            host={str('log_forward_host')}
            port={num('log_forward_port', 5514)}
            protocol={str('log_forward_protocol') || 'udp'}
          />
        </Section>
      )}

      {dataTab === 'backups' && (
        <Section title="Backup" onSave={backupSave.save} saving={backupSave.saving} saved={backupSave.saved} error={backupSave.error}
          help={{
            title: 'Backup — How It Works',
            content: <>
              <p>A backup includes the SQLite database (settings, access points, collectors, alert rules, users) and <code className="text-gray-400">config.yaml</code>.</p>
              <p><span className="text-gray-300 font-medium">Rotation count</span> caps how many snapshots stay on disk — the oldest is deleted automatically once you exceed it.</p>
              <p>Snapshots above can be restored directly from the server — no download/upload round trip needed. Both that and the bundle upload let you pick which files to restore instead of always restoring everything. <span className="text-amber-500 font-medium">Restore always requires a service restart</span> afterward for config changes to apply.</p>
            </>,
          }}
        >
          <Field label="Auto backup" hint="Run a scheduled backup on the server at the configured interval">
            <Toggle value={bool('backup_enabled')} onChange={v => set('backup_enabled', v)} />
          </Field>
          <Field label="Interval" hint="Hours between automatic backup runs">
            <div className="flex items-center gap-3">
              <NumberInput value={num('backup_interval_hours', 24)} onChange={v => set('backup_interval_hours', v)} min={1} max={720} />
              <span className="text-sm text-white">hours</span>
            </div>
          </Field>
          <Field label="Rotation count" hint="Number of snapshots to keep — oldest deleted when exceeded">
            <NumberInput value={num('backup_rotation_count', 5)} onChange={v => set('backup_rotation_count', v)} min={1} max={100} />
          </Field>
          <Field label="Backup path" hint="Directory on server where snapshots are stored">
            <TextInput value={str('backup_path')} onChange={v => set('backup_path', v)} mono placeholder="<install_dir>/backups" />
          </Field>
          <Field label="Manual backup" hint="Trigger a backup run immediately using current settings">
            <div className="space-y-3">
              <div className="flex items-center gap-3 flex-wrap">
                <button onClick={runBackupNow} disabled={backupRunning}
                  className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                  {backupRunning ? 'Running…' : 'Run Backup Now'}
                </button>
                {!backupsLoaded && !backupRunning && (
                  <button onClick={loadBackups} className="text-xs text-white hover:text-white underline">Show snapshots</button>
                )}
              </div>
              {backupResult && (
                <p className={`text-xs ${backupResult.startsWith('Error') ? 'text-red-400' : 'text-green-400'}`}>{backupResult}</p>
              )}
              {backupsLoaded && (
                <div className="space-y-1">
                  {backups.length === 0 ? <p className="text-xs text-white">No snapshots found.</p> : backups.map(b => (
                    <SnapshotRestoreRow key={b.name} snapshot={b} onRestored={(name, result) => setSnapshotRestoreResult({ name, result })} />
                  ))}
                </div>
              )}
              {snapshotRestoreResult && (
                <div className="text-xs space-y-1 bg-gray-800/60 rounded-lg p-3">
                  <p className="text-white">Restored from {snapshotRestoreResult.name}:</p>
                  {Object.entries(snapshotRestoreResult.result).map(([k, v]) => (
                    <p key={k}>
                      <span className="text-white">{k}:</span>{' '}
                      <span className={v.startsWith('error') || v.startsWith('not found') ? 'text-red-400' : 'text-green-400'}>{v}</span>
                    </p>
                  ))}
                  <p className="text-amber-400 mt-1">Restart the service to apply any config changes.</p>
                </div>
              )}
            </div>
          </Field>
          <Field label="Export bundle" hint="Download pktwifi.db + config.yaml as a .tar.gz">
            <div className="flex items-center gap-3 flex-wrap">
              {!exportPrompt ? (
                <button onClick={() => { setExportPassword(''); setExportError(null); setExportPrompt(true) }}
                  className="bg-gray-700 hover:bg-gray-600 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                  Download Export
                </button>
              ) : (
                <div className="flex flex-col gap-2 w-full">
                  <p className="text-xs text-amber-300/90">
                    This bundle contains the database <em>and</em> config.yaml — every encrypted secret plus the
                    key that decrypts them. Confirm your password to download it, then store it as carefully as
                    you would the secrets themselves.
                  </p>
                  <div className="flex items-center gap-2 flex-wrap">
                    <input type="password" value={exportPassword} autoComplete="current-password"
                      onChange={e => setExportPassword(e.target.value)}
                      onKeyDown={e => { if (e.key === 'Enter' && exportPassword) runExport() }}
                      placeholder="Your current password"
                      className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white" />
                    <button onClick={runExport} disabled={exportRunning || !exportPassword}
                      className="bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                      {exportRunning ? 'Generating…' : 'Confirm & Download'}
                    </button>
                    <button onClick={() => { setExportPrompt(false); setExportPassword(''); setExportError(null) }}
                      className="text-white hover:text-white text-sm border border-gray-700 rounded-lg px-4 py-2 transition-colors">
                      Cancel
                    </button>
                  </div>
                </div>
              )}
              {exportError && <span className="text-xs text-red-400">{exportError}</span>}
            </div>
          </Field>
          <Field label="Restore from bundle" hint="Upload a pktwifi export .tar.gz to restore SQLite and config. Restart service after restore.">
            <div className="space-y-3">
              <div className="flex items-center gap-3 flex-wrap">
                <label className="bg-gray-700 hover:bg-gray-600 text-white text-sm rounded-lg px-4 py-2 transition-colors cursor-pointer">
                  {importFile ? importFile.name : 'Choose .tar.gz…'}
                  <input
                    type="file"
                    accept=".tar.gz,.tgz"
                    className="hidden"
                    onChange={e => {
                      setImportFile(e.target.files?.[0] ?? null)
                      setImportResult(null)
                      setImportError(null)
                    }}
                  />
                </label>
                <button onClick={runImport} disabled={!importFile || importRunning || importFiles.size === 0}
                  className="bg-amber-700 hover:bg-amber-600 disabled:opacity-50 text-white text-sm rounded-lg px-4 py-2 transition-colors">
                  {importRunning ? 'Restoring…' : 'Restore'}
                </button>
              </div>
              <div className="flex flex-wrap gap-4 text-xs text-white">
                {ALL_BUNDLE_FILES.map(f => (
                  <label key={f} className="flex items-center gap-1.5 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={importFiles.has(f)}
                      onChange={() => setImportFiles(prev => {
                        const next = new Set(prev)
                        if (next.has(f)) next.delete(f); else next.add(f)
                        return next
                      })}
                      className="accent-amber-600"
                    />
                    <span className="font-mono">{f}</span>
                  </label>
                ))}
              </div>
              {importError && <p className="text-xs text-red-400">{importError}</p>}
              {importResult && (
                <div className="text-xs space-y-1">
                  {Object.entries(importResult).map(([k, v]) => (
                    <p key={k}>
                      <span className="text-white capitalize">{k}:</span>{' '}
                      <span className={v.startsWith('error') ? 'text-red-400' : 'text-green-400'}>{v}</span>
                    </p>
                  ))}
                  <p className="text-amber-400 mt-1">Restart the service to apply any config changes.</p>
                </div>
              )}
            </div>
          </Field>
        </Section>
      )}
          </div>
        </div>
      )}

      {/* Notifications */}
      {tab === 'notifications' && (
        <Section title="Notifications" onSave={notifySave.save} saving={notifySave.saving} saved={notifySave.saved} error={notifySave.error}
          help={{
            title: 'Notifications — How It Works',
            content: <>
              <p>These five channels — Slack, Email, PagerDuty, generic Webhook, and TraceCat SOAR — are what an <span className="text-gray-300 font-medium">Alert rule</span> (Alerts page) can dispatch to when it fires. Enabling a channel here doesn't send anything by itself; it makes the channel available.</p>
              <p><span className="text-gray-300 font-medium">Send Test</span> is a real dispatch, not a dry run — it posts to Slack, sends actual SMTP, fires a PagerDuty event, etc., using whatever's currently saved above.</p>
              <p><span className="text-gray-300 font-medium">Webhook payload template</span> is Jinja2 — reference <code className="text-gray-400">alert_name</code>, <code className="text-gray-400">message</code>, <code className="text-gray-400">severity</code>, and <code className="text-gray-400">fired_at</code>.</p>
            </>,
          }}
        >
          {/* Slack */}
          <div className="pt-2 pb-1">
            <p className="text-xs font-semibold text-white uppercase tracking-wider">Slack</p>
          </div>
          <Field label="Enable Slack">
            <Toggle value={bool('notify_slack_enabled')} onChange={v => set('notify_slack_enabled', v)} />
          </Field>
          {bool('notify_slack_enabled') && (
            <>
              <Field label="Webhook URL">
                <TextInput value={str('notify_slack_webhook_url')} onChange={v => set('notify_slack_webhook_url', v)} placeholder="https://hooks.slack.com/services/…" secret mono />
              </Field>
              <Field label="Channel" hint="Override channel (optional)">
                <TextInput value={str('notify_slack_channel', '#alerts')} onChange={v => set('notify_slack_channel', v)} placeholder="#alerts" />
              </Field>
              <SendTestButton channel="slack" />
            </>
          )}

          {/* Email */}
          <div className="pt-4 pb-1">
            <p className="text-xs font-semibold text-white uppercase tracking-wider">Email (SMTP)</p>
          </div>
          <Field label="Enable email">
            <Toggle value={bool('notify_email_enabled')} onChange={v => set('notify_email_enabled', v)} />
          </Field>
          {bool('notify_email_enabled') && (
            <>
              <Field label="SMTP host"><TextInput value={str('notify_email_smtp_host')} onChange={v => set('notify_email_smtp_host', v)} placeholder="smtp.yourorg.com" mono /></Field>
              <Field label="SMTP port"><NumberInput value={num('notify_email_smtp_port', 587)} onChange={v => set('notify_email_smtp_port', v)} min={1} max={65535} /></Field>
              <Field label="Use TLS"><Toggle value={bool('notify_email_smtp_tls', true)} onChange={v => set('notify_email_smtp_tls', v)} /></Field>
              <Field label="Username"><TextInput value={str('notify_email_username')} onChange={v => set('notify_email_username', v)} mono /></Field>
              <Field label="Password"><TextInput value={str('notify_email_password')} onChange={v => set('notify_email_password', v)} secret /></Field>
              <Field label="From address"><TextInput value={str('notify_email_from')} onChange={v => set('notify_email_from', v)} placeholder="pktwifi@yourorg.com" /></Field>
              <Field label="Default to" hint="Comma-separated email addresses">
                <TextInput
                  value={Array.isArray(settings['notify_email_default_to']) ? (settings['notify_email_default_to'] as string[]).join(', ') : ''}
                  onChange={v => set('notify_email_default_to', v.split(',').map(s => s.trim()).filter(Boolean))}
                  placeholder="noc@yourorg.com, security@yourorg.com"
                />
              </Field>
              <SendTestButton channel="email" />
            </>
          )}

          {/* PagerDuty */}
          <div className="pt-4 pb-1">
            <p className="text-xs font-semibold text-white uppercase tracking-wider">PagerDuty</p>
          </div>
          <Field label="Enable PagerDuty">
            <Toggle value={bool('notify_pagerduty_enabled')} onChange={v => set('notify_pagerduty_enabled', v)} />
          </Field>
          {bool('notify_pagerduty_enabled') && (
            <>
              <Field label="Integration key" hint="Events API v2 integration key">
                <TextInput value={str('notify_pagerduty_integration_key')} onChange={v => set('notify_pagerduty_integration_key', v)} secret mono />
              </Field>
              <SendTestButton channel="pagerduty" />
            </>
          )}

          {/* Webhook */}
          <div className="pt-4 pb-1">
            <p className="text-xs font-semibold text-white uppercase tracking-wider">Webhook</p>
          </div>
          <Field label="Enable webhook">
            <Toggle value={bool('notify_webhook_enabled')} onChange={v => set('notify_webhook_enabled', v)} />
          </Field>
          {bool('notify_webhook_enabled') && (
            <>
              <Field label="URL">
                <TextInput value={str('notify_webhook_url')} onChange={v => set('notify_webhook_url', v)} placeholder="https://yourservice.com/pktwifi-alert" mono />
              </Field>
              <Field label="Method">
                <SelectInput value={str('notify_webhook_method', 'POST')} onChange={v => set('notify_webhook_method', v)}
                  options={[{ value: 'POST', label: 'POST' }, { value: 'PUT', label: 'PUT' }]} />
              </Field>
              <Field label="Payload template" hint="Jinja2 template; vars: alert_name, message, severity, fired_at">
                <textarea value={str('notify_webhook_payload_template')} onChange={e => set('notify_webhook_payload_template', e.target.value)}
                  rows={4} className="w-full bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 text-sm text-white font-mono focus:outline-none focus:ring-2 focus:ring-sky-500" />
              </Field>
              <SendTestButton channel="webhook" />
            </>
          )}

          {/* TraceCat */}
          <div className="pt-2 pb-1">
            <p className="text-sm font-medium text-white">TraceCat SOAR</p>
          </div>
          <Field label="Enable TraceCat">
            <Toggle value={bool('notify_tracecat_enabled')} onChange={v => set('notify_tracecat_enabled', v)} />
          </Field>
          {bool('notify_tracecat_enabled') && (
            <>
              <Field label="Webhook URL" hint="Paste the workflow webhook URL from TraceCat → Workflow → Trigger">
                <TextInput value={str('notify_tracecat_webhook_url')} onChange={v => set('notify_tracecat_webhook_url', v)} placeholder="https://tracecat.yourorg.com/api/v1/webhooks/…" mono />
              </Field>
              <Field label="API token" hint="Bearer token for TraceCat API authentication (optional if webhook is public)">
                <TextInput value={str('notify_tracecat_api_token')} onChange={v => set('notify_tracecat_api_token', v)} secret />
              </Field>
              <SendTestButton channel="tracecat" />
            </>
          )}
        </Section>
      )}

      {/* User Keys */}
      {tab === 'resonance' && (
        <>
        <Section title="Resonance" onSave={resonanceSave.save} saving={resonanceSave.saving} saved={resonanceSave.saved} error={resonanceSave.error}
          help={{
            title: 'Resonance — How It Works',
            content: <>
              <p>Resonance is the shared assistant surface for the pkt suite. It mounts as a launcher in the corner of every page, but the assistant itself runs on the resonance server rather than inside pktWiFi.</p>
              <p><span className="text-gray-300 font-medium">Resonance AI Interface Server</span> is the interface resonance serves embeds from — <span className="text-amber-500 font-medium">not its admin portal</span>, which usually answers on a different address and will look almost right: it serves <code>embed.js</code> too, and only fails later with a &ldquo;not found&rdquo; on the session call. Whatever is typed into SETTINGS → ENROLL → Enroll Embed Server on resonance goes here character for character, because <code>embed.js</code> derives its own origin from that string. Leave the port off if it sits behind a reverse proxy.</p>
              <p><span className="text-gray-300 font-medium">pktWiFi&rsquo;s own address</span> is what a browser types to reach this app, and it is the string that has to appear on the resonance key&rsquo;s origins list. Leave it blank and pktWiFi works it out from the request — correct for a direct install, and wrong behind a reverse proxy, where it sees the internal address rather than the one users type.</p>
              <p><span className="text-gray-300 font-medium">pktWiFi never sends your login credentials.</span> It vouches for whoever is signed in and receives a short-lived, single-use code the browser spends on opening the widget. The key below never reaches the browser.</p>
              <p><span className="text-gray-300 font-medium">The panel&rsquo;s insides belong to resonance.</span> It is an iframe served from resonance&rsquo;s own origin, so pktWiFi cannot restyle it or move its controls — where the buttons sit is a resonance change. What pktWiFi can do is make the panel bigger, with <span className="text-gray-300 font-medium">Panel size</span>, which is usually what &ldquo;more room to read&rdquo; actually needs.</p>
              <p><span className="text-amber-500 font-medium">What the assistant will discuss is configured in resonance, not here.</span> The subjects it will engage with are set by the profile the key is authorised against.</p>
              <p><span className="text-gray-300 font-medium">The assistant can read this install&rsquo;s data.</span> The access points and one in full, the associated clients and their signal quality, the radios with their channels and congestion, the collectors, the estate summary, alert rules and the alerts they have fired, and pktWiFi&rsquo;s own diagnostic log. Each call is made by this page on the session of whoever is signed in, so it reaches only what that person could already open. The list is published at <code>/.well-known/resonance.json</code> and is fixed in the code rather than configurable — but it is inert unless <span className="text-gray-300 font-medium">Enabled</span> is on and the person&rsquo;s role is above <span className="text-gray-300 font-medium">No access</span> below.</p>
              <p><span className="text-amber-500 font-medium">No controller credential ever leaves through it</span> — a collector&rsquo;s stored configuration is not selected at all. Nothing it can call changes a channel or a transmit power, deauthenticates a client, or creates, edits or deletes an access point, SSID, radio or collector.</p>
              <p><span className="text-gray-300 font-medium">Read and write adds two operations, and no more.</span> Acknowledge one alert, and acknowledge all of them. pktWiFi&rsquo;s interface has no rule on/off switch, so the assistant has none either. Resonance stops and reads the real values back to the person before running either.</p>
              <p><span className="text-gray-300 font-medium">A level never exceeds the role.</span> Two checks have to agree: the level set here, and pktWiFi&rsquo;s own rule for the thing being done — acknowledging is an analyst&rsquo;s to do, so a viewer on <span className="text-gray-300 font-medium">Read and write</span> still cannot.</p>
              <p>Where no role is set to <span className="text-gray-300 font-medium">Read and write</span>, the write operations are withheld from the published grant altogether, so nothing at the resonance end can be ticked into offering them.</p>
              <p>Answers are capped so a conversation stays readable: a page plus the true count, trimmed again if it would be too large to carry, and the assistant is told when that happened so it narrows the question rather than showing half an answer. Documentation is published separately at <code>/api/resonance/docs</code>, so pointing resonance at it keeps what the assistant knows in step with the installed version.</p>
              <p>Resonance must be reachable from the <span className="text-gray-300 font-medium">browser</span>, over HTTPS, with a certificate those browsers already trust. An untrusted certificate produces an empty widget with nothing in the console to explain it.</p>
              <p><span className="text-gray-300 font-medium">pktWiFi also calls resonance directly</span>, server to server, so this host must be able to resolve resonance&rsquo;s name and trust its certificate — the browser doing both is not enough. Python verifies against its own bundled roots rather than the system store, so a certificate signed by an internal CA is trusted by every browser on the network and still rejected here. <span className="text-gray-300 font-medium">CA bundle</span> points it at the system store instead; on Debian and Ubuntu that is <code>/etc/ssl/certs/ca-certificates.crt</code>.</p>
            </>,
          }}
        >
          <Field label="Enabled" hint="Show the launcher to users. Separate from Test Connection on purpose.">
            <Toggle value={bool('resonance_enabled')} onChange={v => set('resonance_enabled', v)} />
          </Field>
          <Field label="Resonance AI Interface Server" hint="The interface server, not the admin portal — they are different addresses.">
            <TextInput value={str('resonance_base_url')} onChange={v => set('resonance_base_url', v)} placeholder="https://resonance.example.com" mono />
          </Field>
          <Field label="Key" hint="Issued by resonance, one per placement. Never sent to the browser.">
            <TextInput value={str('resonance_key')} onChange={v => set('resonance_key', v)} placeholder="e0000000000.…" secret mono />
          </Field>
          <Field label="pktWiFi's own address" hint="What browsers type to reach pktWiFi. Copy it onto the resonance key.">
            <ResonanceOriginField value={str('resonance_origin')} onChange={v => set('resonance_origin', v)} />
          </Field>
          <Field label="CA bundle" hint="Only needed if resonance uses an internal CA. Blank trusts public CAs only.">
            <TextInput value={str('resonance_ca_bundle')} onChange={v => set('resonance_ca_bundle', v)} placeholder="/etc/ssl/certs/ca-certificates.crt" mono />
          </Field>
          <Field label="What each role can do" hint="No access hides the launcher entirely. Read only lets the assistant look. Read and write also lets it act — never beyond what that role can already do in pktWiFi.">
            <div className="space-y-2">
              {['admin', 'analyst', 'viewer'].map(role => (
                <div key={role} className="flex items-center gap-3">
                  <span className="w-20 text-sm text-white">{role}</span>
                  <SelectInput
                    value={resonanceLevel(role)}
                    onChange={v => setResonanceLevel(role, v)}
                    options={[
                      { value: 'none',  label: 'No access' },
                      { value: 'read',  label: 'Read only' },
                      { value: 'write', label: 'Read and write' },
                    ]}
                  />
                </div>
              ))}
            </div>
          </Field>
          <Field label="Placement" hint="Bubble is a launcher in the corner. Inline renders into an element you name instead.">
            <SelectInput
              value={str('resonance_style', 'bubble')}
              onChange={v => set('resonance_style', v)}
              options={[{ value: 'bubble', label: 'Bubble' }, { value: 'inline', label: 'Inline' }]}
            />
          </Field>
          {str('resonance_style', 'bubble') === 'inline' && (
            <Field label="Target element" hint="id of an element that already exists. Without it nothing mounts.">
              <TextInput value={str('resonance_target')} onChange={v => set('resonance_target', v)} mono />
            </Field>
          )}
          <Field label="Side" hint="Which corner the launcher sits in.">
            <SelectInput
              value={str('resonance_side', 'right')}
              onChange={v => set('resonance_side', v)}
              options={[{ value: 'right', label: 'Right' }, { value: 'left', label: 'Left' }]}
            />
          </Field>
          <Field label="Label" hint="Optional text on the launcher.">
            <TextInput value={str('resonance_label')} onChange={v => set('resonance_label', v)} />
          </Field>
          <Field label="Panel size" hint="Width and height of the open panel. Blank uses resonance's defaults.">
            <div className="flex items-center gap-2">
              <TextInput value={str('resonance_width')} onChange={v => set('resonance_width', v)} placeholder="420" mono />
              <span className="text-xs text-gray-500">&times;</span>
              <TextInput value={str('resonance_height')} onChange={v => set('resonance_height', v)} placeholder="640" mono />
            </div>
          </Field>
          <Field label="Open on load" hint="Show the panel expanded rather than waiting for a click.">
            <Toggle value={bool('resonance_open')} onChange={v => set('resonance_open', v)} />
          </Field>
          <Field label="Hide on pages" hint="Comma-separated paths. Listing a page discards conversations on it.">
            <TextInput
              value={((settings['resonance_exclude_paths'] as string[]) ?? ['/login']).join(', ')}
              onChange={v => set('resonance_exclude_paths', v.split(',').map(x => x.trim()).filter(Boolean))}
              mono
            />
          </Field>
        </Section>
        <ResonanceDiagnostics baseUrl={str('resonance_base_url')} keyValue={str('resonance_key')} />
        </>
      )}

      {tab === 'apikeys' && (
        <ApiKeysTab
          lucidToken={str('lucid_api_token')}
          onLucidChange={v => set('lucid_api_token', v)}
          lucidSave={lucidSave}
        />
      )}

      {/* Controllers — pktWiFi-specific, right of the tab divider */}
      {tab === 'controllers' && isAdmin && <ControllersTab />}

      {/* Credentials — pktWiFi-specific, right of the tab divider */}
      {tab === 'credentials' && isAdmin && <CredentialsTab />}

      {/* Sites — pktWiFi-specific, right of the tab divider */}
      {tab === 'sites' && isAdmin && <SitesTab />}

      {/* System — version/about info */}
      {tab === 'system' && (
        <div className="space-y-4">
          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-800 grid grid-cols-3 gap-4 items-center">
              <h2 className="text-sm font-semibold text-white">System: {systemInfo?.app_name ?? 'pktWiFi'}</h2>
              <div className="col-span-2">
                <BrandLockup markSize={32} descriptor={null} />
              </div>
            </div>
            <div className="px-6 py-2">
              <Field label="Version">
                <p className="text-sm text-white font-mono">v{systemInfo?.version ?? '—'}</p>
              </Field>
              <Field label="Directory">
                <p className="text-sm text-white font-mono break-all">{systemInfo?.install_dir ?? '—'}</p>
              </Field>
              <Field label="Github">
                {systemInfo?.github ? (
                  <a href={systemInfo.github} target="_blank" rel="noreferrer"
                    className="text-sm text-blue-400 hover:text-blue-300 break-all">{systemInfo.github}</a>
                ) : <p className="text-sm text-white">—</p>}
              </Field>
              <Field label="License">
                <p className="text-sm text-white">{systemInfo?.license ?? '—'}</p>
              </Field>
              <Field label="Developer">
                <p className="text-sm text-white">{systemInfo?.developer ?? '—'}</p>
              </Field>
              <Field label="Contact">
                {systemInfo?.contact ? (
                  <a href={`mailto:${systemInfo.contact}`}
                    className="text-sm text-blue-400 hover:text-blue-300">{systemInfo.contact}</a>
                ) : <p className="text-sm text-white">—</p>}
              </Field>
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-800">
              <h2 className="text-sm font-semibold text-white">Licenses &amp; Copyright</h2>
            </div>
            <div className="px-6 py-4">
              <p className="text-xs text-gray-400 mb-3">
                {systemInfo?.app_name ?? 'pktWiFi'} is built with the following open-source software:
              </p>
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-x-6 gap-y-1 text-xs text-gray-300 font-mono">
                {OSS_NOTICES.map(n => (
                  <div key={n.name} className="flex justify-between gap-2">
                    <span>{n.name}</span>
                    <span className="text-gray-500">{n.license}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="bg-gray-900 border border-gray-800 rounded-xl overflow-hidden px-6 py-6 flex items-center justify-center">
            <img src="barsoftnetware-logo.png" alt="Barsoft Netware" className="h-56 w-auto" />
          </div>
        </div>
      )}
      </div>
    </div>
    </>

  )
}

// -- SSL certificate upload ---------------------------------------------------
