import { useEffect, useRef, useState } from 'react'
import { FiSave, FiAlertCircle, FiDownload, FiUpload, FiCheckCircle, FiPlus, FiTrash2, FiChevronDown, FiChevronUp, FiList, FiRefreshCw, FiArchive, FiGitPullRequest } from 'react-icons/fi'
import api from '../api'

interface SettingsData {
  telegram_bot_token?: string
  telegram_chat_id?: string
  watchdog_enabled?: boolean
  max_restarts?: number
  yt_refresh_hours?: number
  backup_auto_enabled?: boolean
  backup_interval_hours?: number
  backup_retention?: number
}

interface BackupFile {
  filename: string
  size: number
  created_at: string
  type: 'auto' | 'manual'
}

function Row({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="form-group">
      <label style={{ fontWeight: 500 }}>{label}</label>
      {hint && <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 4 }}>{hint}</div>}
      {children}
    </div>
  )
}

// ── Tutorial expansível ────────────────────────────────────────────────────
function TelegramTutorial() {
  const [open, setOpen] = useState(false)
  return (
    <div style={{
      border: '1px solid var(--border)', borderRadius: 8,
      overflow: 'hidden', marginBottom: 16,
    }}>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          padding: '10px 14px', background: 'var(--bg3)', border: 'none', cursor: 'pointer',
          color: 'var(--text2)', fontSize: 13, fontWeight: 500,
        }}
      >
        <span>📖 Como configurar o Telegram — passo a passo</span>
        {open ? <FiChevronUp size={14} /> : <FiChevronDown size={14} />}
      </button>

      {open && (
        <div style={{ padding: '16px 14px', display: 'flex', flexDirection: 'column', gap: 14, fontSize: 13 }}>

          {/* Token */}
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
              Passo 1 — Criar o Bot e obter o Token
            </div>
            <ol style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 5, color: 'var(--text2)' }}>
              <li>Abra o Telegram e busque por <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>@BotFather</code></li>
              <li>Envie o comando <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>/newbot</code></li>
              <li>Digite um <strong>nome</strong> para o bot (ex: <em>Aistra Notificações</em>)</li>
              <li>Digite um <strong>username</strong> para o bot — deve terminar em <em>bot</em> (ex: <em>aistra_notif_bot</em>)</li>
              <li>O BotFather devolverá o <strong>Token</strong> no formato:<br />
                <code style={{ background:'var(--bg4)', padding:'3px 8px', borderRadius:4, display:'inline-block', marginTop:4 }}>
                  1234567890:ABCdefGhIJKlmNoPQRstuvwXYZ
                </code>
              </li>
              <li>Cole esse token no campo <strong>Bot Token</strong> acima e salve.</li>
            </ol>
          </div>

          <div style={{ borderTop: '1px solid var(--border)' }} />

          {/* Chat ID pessoal */}
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
              Passo 2 — Obter seu Chat ID pessoal
            </div>
            <ol style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 5, color: 'var(--text2)' }}>
              <li>No Telegram, busque pelo bot que você criou e clique em <strong>Start / Iniciar</strong></li>
              <li>Busque por <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>@userinfobot</code> e envie <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>/start</code> — ele mostrará seu ID numérico</li>
              <li>Ou acesse no browser (substitua TOKEN pelo seu token):<br />
                <code style={{ background:'var(--bg4)', padding:'3px 8px', borderRadius:4, display:'block', marginTop:4, wordBreak:'break-all' }}>
                  https://api.telegram.org/botTOKEN/getUpdates
                </code>
              </li>
              <li>Envie uma mensagem para o seu bot e recarregue a URL acima — procure por <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>message.chat.id</code></li>
              <li>O ID pessoal é um número positivo (ex: <em>987654321</em>)</li>
            </ol>
          </div>

          <div style={{ borderTop: '1px solid var(--border)' }} />

          {/* Grupo ou canal */}
          <div>
            <div style={{ fontWeight: 600, color: 'var(--text)', marginBottom: 6 }}>
              Passo 3 — Usar um Grupo ou Canal (opcional)
            </div>
            <ol style={{ paddingLeft: 18, display: 'flex', flexDirection: 'column', gap: 5, color: 'var(--text2)' }}>
              <li>Crie um grupo ou canal no Telegram</li>
              <li>Adicione o seu bot como <strong>administrador</strong> do grupo/canal</li>
              <li>Envie uma mensagem no grupo e acesse a URL <code style={{ background:'var(--bg4)', padding:'1px 5px', borderRadius:4 }}>getUpdates</code> acima</li>
              <li>O ID de grupo/canal começa com <strong>-100</strong> (ex: <em>-1001234567890</em>)</li>
            </ol>
          </div>

          <div style={{ background: 'var(--accent-glow)', border: '1px solid var(--accent)', borderRadius: 6, padding: '8px 12px', color: 'var(--accent)', fontSize: 12 }}>
            💡 <strong>Dica:</strong> Você pode adicionar múltiplos Chat IDs abaixo para enviar notificações para várias pessoas ou grupos ao mesmo tempo.
          </div>
        </div>
      )}
    </div>
  )
}

export default function Settings() {
  const [form, setForm]       = useState<SettingsData>({})
  const [chatIds, setChatIds] = useState<string[]>([''])  // multiple chat IDs
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [error, setError]     = useState('')
  const [logoSize, setLogoSize] = useState<number>(
    () => Number(localStorage.getItem('sidebar_logo_size') || 22)
  )

  function changeLogoSize(v: number) {
    setLogoSize(v)
    localStorage.setItem('sidebar_logo_size', String(v))
    window.dispatchEvent(new Event('sidebar_logo_size'))
  }

  // Backup state
  const [backups, setBackups]           = useState<BackupFile[]>([])
  const [backupsLoading, setBackupsLoading] = useState(false)
  const [creatingBackup, setCreatingBackup] = useState(false)
  const [backupMsg, setBackupMsg]       = useState('')
  const [backupError, setBackupError]   = useState('')
  const [restoringFile, setRestoringFile] = useState<string | null>(null)
  const [restoreResult, setRestoreResult] = useState<{ created: number; updated: number; skipped: number } | null>(null)
  const [restoreError, setRestoreError] = useState('')
  const zipFileRef = useRef<HTMLInputElement>(null)
  // Legacy JSON restore
  const fileRef = useRef<HTMLInputElement>(null)
  const [restoring, setRestoring]       = useState(false)

  // M3U import state
  const [m3uImporting, setM3uImporting] = useState(false)
  const [m3uOverwrite, setM3uOverwrite] = useState(false)
  const [m3uResult, setM3uResult]       = useState<{ created: number; updated: number; skipped: number; errors: number } | null>(null)
  const [m3uError, setM3uError]         = useState('')
  const m3uRef = useRef<HTMLInputElement>(null)

  // Update state
  type UpdateInfo = {
    current: string
    update_available: boolean | null
    gh_token_configured: boolean
    message?: string
    latest?: string
    latest_message?: string
    latest_date?: string
    latest_author?: string
  }
  const [updateInfo, setUpdateInfo]       = useState<UpdateInfo | null>(null)
  const [updateChecking, setUpdateChecking] = useState(false)
  const [updateApplying, setUpdateApplying] = useState(false)
  const [updateLog, setUpdateLog]         = useState<string[]>([])
  const [updateLogOpen, setUpdateLogOpen] = useState(false)
  const [updateMsg, setUpdateMsg]         = useState('')
  const updateLogRef = useRef<HTMLDivElement>(null)

  async function checkUpdates() {
    setUpdateChecking(true)
    setUpdateInfo(null)
    try {
      const res = await api.get('/api/update/check')
      setUpdateInfo(res.data)
    } catch {
      setUpdateInfo(null)
    } finally {
      setUpdateChecking(false)
    }
  }

  async function applyUpdate() {
    if (!confirm('Iniciar atualização?\n\nO painel ficará offline ~30 segundos enquanto o serviço reinicia.\nAposição a página irá recarregar automaticamente quando voltar.')) return
    setUpdateApplying(true)
    setUpdateMsg('')
    setUpdateLog([])
    setUpdateLogOpen(true)
    try {
      const res = await api.post('/api/update/apply')
      setUpdateMsg(res.data.message)
      // Poll log every 2s while applying, then reload when service comes back
      let attempts = 0
      const poll = setInterval(async () => {
        attempts++
        try {
          const logRes = await api.get('/api/update/log')
          setUpdateLog(logRes.data.lines || [])
          if (updateLogRef.current) {
            updateLogRef.current.scrollTop = updateLogRef.current.scrollHeight
          }
        } catch {
          // service restarting — wait and reload
          clearInterval(poll)
          setTimeout(() => window.location.reload(), 5000)
        }
        if (attempts > 60) clearInterval(poll)
      }, 2000)
    } catch (e: any) {
      setUpdateMsg(e.response?.data?.detail || 'Erro ao iniciar atualização')
      setUpdateApplying(false)
    }
  }

  useEffect(() => {
    api.get('/api/settings')
      .then(r => {
        const data = r.data || {}
        setForm(data)
        const ids = (data.telegram_chat_id || '').split(',').map((s: string) => s.trim()).filter(Boolean)
        setChatIds(ids.length > 0 ? ids : [''])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
    loadBackups()
  }, [])

  async function loadBackups() {
    setBackupsLoading(true)
    try {
      const res = await api.get('/api/backup/list')
      setBackups(res.data || [])
    } catch { /* ignore */ }
    finally { setBackupsLoading(false) }
  }

  async function createBackup() {
    setCreatingBackup(true); setBackupMsg(''); setBackupError('')
    try {
      const res = await api.post('/api/backup/create')
      setBackupMsg(`Backup criado: ${res.data.filename} (${(res.data.size / 1024).toFixed(0)} KB)`)
      setTimeout(() => setBackupMsg(''), 6000)
      await loadBackups()
    } catch (e: any) {
      setBackupError(e.response?.data?.detail || 'Erro ao criar backup')
      setTimeout(() => setBackupError(''), 6000)
    } finally { setCreatingBackup(false) }
  }

  async function downloadZipBackup(filename: string) {
    const res = await fetch(`/api/backup/download/${encodeURIComponent(filename)}`, {
      headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
    })
    if (!res.ok) return
    const blob = await res.blob()
    const url  = URL.createObjectURL(blob)
    const a    = document.createElement('a')
    a.href = url; a.download = filename; a.click()
    URL.revokeObjectURL(url)
  }

  async function deleteBackup(filename: string) {
    if (!confirm(`Deletar backup "${filename}"?`)) return
    try {
      await api.delete(`/api/backup/${encodeURIComponent(filename)}`)
      await loadBackups()
    } catch (e: any) {
      setBackupError(e.response?.data?.detail || 'Erro ao deletar')
      setTimeout(() => setBackupError(''), 4000)
    }
  }

  async function restoreFromServer(filename: string) {
    if (!confirm(`Restaurar backup "${filename}"?\nIsso irá sobrescrever dados existentes.`)) return
    setRestoringFile(filename); setRestoreResult(null); setRestoreError('')
    try {
      const res = await api.post(`/api/backup/restore/${encodeURIComponent(filename)}`)
      setRestoreResult(res.data)
      setTimeout(() => setRestoreResult(null), 8000)
    } catch (e: any) {
      setRestoreError(e.response?.data?.detail || 'Erro ao restaurar')
      setTimeout(() => setRestoreError(''), 6000)
    } finally { setRestoringFile(null) }
  }

  async function handleZipRestore(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setRestoringFile('upload'); setRestoreResult(null); setRestoreError('')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await api.post('/api/backup/restore-upload', formData, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setRestoreResult(res.data)
      setTimeout(() => setRestoreResult(null), 8000)
    } catch (e: any) {
      setRestoreError(e.response?.data?.detail || 'Arquivo inválido ou erro ao restaurar')
      setTimeout(() => setRestoreError(''), 6000)
    } finally { setRestoringFile(null) }
  }

  function set(k: keyof SettingsData, v: any) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function save() {
    setSaving(true); setSaved(false); setError('')
    try {
      // Join non-empty chat IDs as comma-separated string
      const ids = chatIds.map(s => s.trim()).filter(Boolean).join(',')
      await api.put('/api/settings', { ...form, telegram_chat_id: ids })
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Erro ao salvar')
    } finally {
      setSaving(false)
    }
  }

  async function handleLegacyRestore(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setRestoring(true); setRestoreResult(null); setRestoreError('')
    try {
      const text = await file.text()
      const body = JSON.parse(text)
      const res  = await api.post('/api/settings/restore', body)
      setRestoreResult(res.data)
      setTimeout(() => setRestoreResult(null), 6000)
    } catch (e: any) {
      setRestoreError(e.response?.data?.detail || 'Arquivo inválido ou erro ao restaurar')
      setTimeout(() => setRestoreError(''), 6000)
    } finally { setRestoring(false) }
  }

  async function handleM3uImport(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    e.target.value = ''
    setM3uImporting(true); setM3uResult(null); setM3uError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await api.post(`/api/streams/import-m3u?overwrite=${m3uOverwrite}`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setM3uResult(res.data)
      setTimeout(() => setM3uResult(null), 8000)
    } catch (e: any) {
      setM3uError(e.response?.data?.detail || 'Erro ao importar M3U')
      setTimeout(() => setM3uError(''), 6000)
    } finally {
      setM3uImporting(false)
    }
  }

  if (loading) return (
    <div className="page">
      <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 60 }}>Carregando…</div>
    </div>
  )

  return (
    <div className="page">
      <div className="page-header">
        <h1>Configurações</h1>
      </div>

      <div className="page-content" style={{ maxWidth: 640 }}>

        {/* Interface */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Interface</h2>
          <Row label="Tamanho dos logos na barra lateral" hint="Tamanho dos ícones de categoria exibidos no menu lateral.">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="range" min={14} max={48} step={2}
                value={logoSize}
                onChange={e => changeLogoSize(Number(e.target.value))}
                style={{ flex: 1, padding: 0, border: 'none', background: 'transparent', accentColor: 'var(--accent)' }}
              />
              <span style={{ minWidth: 38, color: 'var(--text2)', fontSize: 13 }}>{logoSize}px</span>
            </div>
          </Row>
        </div>

        {/* Telegram Notifications */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Notificações Telegram</h2>

          <TelegramTutorial />

          <Row
            label="Bot Token"
            hint="Token do bot criado via @BotFather. Deixe em branco para desativar as notificações."
          >
            <input
              type="password"
              value={form.telegram_bot_token ?? ''}
              onChange={e => set('telegram_bot_token', e.target.value)}
              placeholder="1234567890:ABCdefGhIJKlmNoPQRstu..."
              autoComplete="off"
            />
          </Row>

          <div className="form-group" style={{ marginTop: 8 }}>
            <label style={{ fontWeight: 500 }}>Chat IDs de destino</label>
            <div style={{ fontSize: 12, color: 'var(--text3)', marginBottom: 8 }}>
              Adicione um ou mais IDs de chat, grupo ou canal. Cada um receberá as notificações.
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {chatIds.map((id, i) => (
                <div key={i} style={{ display: 'flex', gap: 6 }}>
                  <input
                    value={id}
                    onChange={e => {
                      const next = [...chatIds]
                      next[i] = e.target.value
                      setChatIds(next)
                    }}
                    placeholder={i === 0 ? 'Ex: 987654321 (pessoal)' : 'Ex: -1001234567890 (grupo/canal)'}
                    style={{ flex: 1 }}
                  />
                  {chatIds.length > 1 && (
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => setChatIds(chatIds.filter((_, j) => j !== i))}
                      title="Remover"
                    >
                      <FiTrash2 size={13} />
                    </button>
                  )}
                </div>
              ))}
            </div>
            <button
              className="btn btn-ghost btn-sm"
              style={{ marginTop: 6, alignSelf: 'flex-start' }}
              onClick={() => setChatIds([...chatIds, ''])}
            >
              <FiPlus size={13} /> Adicionar destinatário
            </button>
          </div>
        </div>

        {/* Watchdog */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Watchdog de Streams</h2>
          <Row label="Reinicialização automática" hint="Reinicia streams que caírem ou travarem (0 kbps por 3 checagens seguidas).">
            <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
              <input
                type="checkbox"
                checked={form.watchdog_enabled !== false}
                onChange={e => set('watchdog_enabled', e.target.checked)}
              />
              <span style={{ fontSize: 14 }}>Ativado</span>
            </label>
          </Row>
          <Row label="Máximo de reinicializações" hint="Após atingir o limite, o stream fica em estado de erro.">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="range" min={1} max={20}
                value={form.max_restarts ?? 5}
                onChange={e => set('max_restarts', Number(e.target.value))}
                style={{ flex: 1, padding: 0, border: 'none', background: 'transparent', accentColor: 'var(--accent)' }}
              />
              <span style={{ minWidth: 30, color: 'var(--text2)', fontSize: 13 }}>{form.max_restarts ?? 5}×</span>
            </div>
          </Row>
          <Row label="Renovação de URL YouTube (horas)" hint="A cada N horas renova automaticamente as URLs de streams do YouTube via yt-dlp.">
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <input
                type="range" min={1} max={24}
                value={form.yt_refresh_hours ?? 4}
                onChange={e => set('yt_refresh_hours', Number(e.target.value))}
                style={{ flex: 1, padding: 0, border: 'none', background: 'transparent', accentColor: 'var(--accent)' }}
              />
              <span style={{ minWidth: 36, color: 'var(--text2)', fontSize: 13 }}>{form.yt_refresh_hours ?? 4}h</span>
            </div>
          </Row>
        </div>

        {/* Backup & Restore */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Backup Profissional</h2>
          <p style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 16 }}>
            Backup completo em ZIP: streams, usuários, categorias, configurações e logos.
            O Token do Telegram <strong>não</strong> é incluído por segurança.
          </p>

          {/* Auto-backup config */}
          <div style={{ background: 'var(--bg3)', borderRadius: 8, padding: '14px 16px', marginBottom: 16 }}>
            <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 12 }}>Backup Automático</div>
            <Row label="Ativar backup automático">
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer' }}>
                <input
                  type="checkbox"
                  checked={form.backup_auto_enabled === true}
                  onChange={e => set('backup_auto_enabled', e.target.checked)}
                />
                <span style={{ fontSize: 14 }}>Ativado</span>
              </label>
            </Row>
            <Row label="Intervalo (horas)" hint="A cada quantas horas um backup automático é gerado.">
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range" min={1} max={168} step={1}
                  value={form.backup_interval_hours ?? 24}
                  onChange={e => set('backup_interval_hours', Number(e.target.value))}
                  style={{ flex: 1, padding: 0, border: 'none', background: 'transparent', accentColor: 'var(--accent)' }}
                />
                <span style={{ minWidth: 42, color: 'var(--text2)', fontSize: 13 }}>{form.backup_interval_hours ?? 24}h</span>
              </div>
            </Row>
            <Row label="Retenção (backups automáticos)" hint="Quantos backups automáticos manter. Os mais antigos são deletados.">
              <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                <input
                  type="range" min={1} max={30} step={1}
                  value={form.backup_retention ?? 7}
                  onChange={e => set('backup_retention', Number(e.target.value))}
                  style={{ flex: 1, padding: 0, border: 'none', background: 'transparent', accentColor: 'var(--accent)' }}
                />
                <span style={{ minWidth: 36, color: 'var(--text2)', fontSize: 13 }}>{form.backup_retention ?? 7}</span>
              </div>
            </Row>
          </div>

          {/* Manual create */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 16 }}>
            <button
              className="btn btn-primary"
              onClick={createBackup}
              disabled={creatingBackup}
              style={{ gap: 6 }}
            >
              <FiArchive size={14} />
              {creatingBackup ? 'Criando…' : 'Criar backup agora'}
            </button>

            <button
              className="btn btn-ghost"
              onClick={() => zipFileRef.current?.click()}
              disabled={restoringFile !== null}
              style={{ gap: 6 }}
            >
              <FiUpload size={14} />
              {restoringFile === 'upload' ? 'Restaurando…' : 'Restaurar de arquivo ZIP…'}
            </button>
            <input ref={zipFileRef} type="file" accept=".zip,application/zip" style={{ display: 'none' }} onChange={handleZipRestore} />

            <button className="btn btn-ghost" onClick={loadBackups} disabled={backupsLoading} style={{ gap: 6 }}>
              <FiRefreshCw size={13} style={{ animation: backupsLoading ? 'spin 1s linear infinite' : undefined }} />
              Atualizar lista
            </button>
          </div>

          {backupMsg && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, color: 'var(--success)', fontSize: 13 }}>
              <FiCheckCircle size={14} /> {backupMsg}
            </div>
          )}
          {backupError && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, color: 'var(--danger)', fontSize: 13 }}>
              <FiAlertCircle size={14} /> {backupError}
            </div>
          )}

          {/* Backup list */}
          {backups.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text3)', marginBottom: 2 }}>
                Backups armazenados no servidor ({backups.length})
              </div>
              {backups.map(b => (
                <div key={b.filename} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  background: 'var(--bg3)', borderRadius: 6, padding: '8px 12px',
                  fontSize: 12,
                }}>
                  <span style={{
                    background: b.type === 'auto' ? 'var(--bg4)' : 'var(--accent-glow)',
                    color: b.type === 'auto' ? 'var(--text3)' : 'var(--accent)',
                    borderRadius: 4, padding: '1px 6px', fontSize: 11, fontWeight: 600,
                  }}>
                    {b.type === 'auto' ? 'AUTO' : 'MANUAL'}
                  </span>
                  <span style={{ flex: 1, color: 'var(--text2)', fontFamily: 'monospace' }}>{b.filename}</span>
                  <span style={{ color: 'var(--text3)', whiteSpace: 'nowrap' }}>
                    {new Date(b.created_at).toLocaleString('pt-BR')} · {(b.size / 1024).toFixed(0)} KB
                  </span>
                  <button
                    className="btn btn-ghost btn-sm"
                    title="Baixar"
                    onClick={() => downloadZipBackup(b.filename)}
                    style={{ padding: '4px 8px' }}
                  >
                    <FiDownload size={12} />
                  </button>
                  <button
                    className="btn btn-ghost btn-sm"
                    title="Restaurar este backup"
                    disabled={restoringFile !== null}
                    onClick={() => restoreFromServer(b.filename)}
                    style={{ padding: '4px 8px' }}
                  >
                    {restoringFile === b.filename ? '…' : <FiUpload size={12} />}
                  </button>
                  <button
                    className="btn btn-danger btn-sm"
                    title="Deletar"
                    onClick={() => deleteBackup(b.filename)}
                    style={{ padding: '4px 8px' }}
                  >
                    <FiTrash2 size={12} />
                  </button>
                </div>
              ))}
            </div>
          ) : (
            !backupsLoading && (
              <div style={{ fontSize: 13, color: 'var(--text3)', fontStyle: 'italic' }}>
                Nenhum backup armazenado. Clique em "Criar backup agora" para gerar o primeiro.
              </div>
            )
          )}

          {restoreResult && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, color: 'var(--success)', fontSize: 13 }}>
              <FiCheckCircle size={14} />
              Restaurado: {restoreResult.created} criados · {restoreResult.updated} atualizados · {restoreResult.skipped} ignorados
            </div>
          )}
          {restoreError && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, color: 'var(--danger)', fontSize: 13 }}>
              <FiAlertCircle size={14} /> {restoreError}
            </div>
          )}

          {/* Legacy JSON backup */}
          <details style={{ marginTop: 20 }}>
            <summary style={{ fontSize: 12, color: 'var(--text3)', cursor: 'pointer' }}>
              Backup legado (JSON) — compatibilidade com versões anteriores
            </summary>
            <div style={{ paddingTop: 10, display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <a
                href="/api/settings/backup"
                target="_blank"
                rel="noopener noreferrer"
                className="btn btn-ghost btn-sm"
                style={{ gap: 6, textDecoration: 'none' }}
                onClick={e => {
                  // Add auth header via fetch+blob instead of direct link
                  e.preventDefault()
                  fetch('/api/settings/backup', { headers: { Authorization: `Bearer ${localStorage.getItem('token')}` } })
                    .then(r => r.blob()).then(blob => {
                      const url = URL.createObjectURL(blob)
                      const a = document.createElement('a')
                      a.href = url; a.download = `aistra-backup-${new Date().toISOString().slice(0,10)}.json`; a.click()
                      URL.revokeObjectURL(url)
                    })
                }}
              >
                <FiDownload size={12} /> Baixar JSON
              </a>
              <button className="btn btn-ghost btn-sm" onClick={() => fileRef.current?.click()} disabled={restoring} style={{ gap: 6 }}>
                <FiUpload size={12} /> {restoring ? 'Restaurando…' : 'Restaurar JSON…'}
              </button>
              <input ref={fileRef} type="file" accept=".json,application/json" style={{ display: 'none' }} onChange={handleLegacyRestore} />
            </div>
          </details>
        </div>

        {/* M3U Import */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Importar Playlist M3U</h2>
          <p style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 16 }}>
            Importe canais em lote a partir de um arquivo <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>.m3u</code> ou <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>.m3u8</code>.
            Os campos <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>tvg-id</code>, <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>tvg-name</code> e <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>group-title</code> são lidos automaticamente.
          </p>

          <label style={{ display: 'flex', alignItems: 'center', gap: 8, cursor: 'pointer', marginBottom: 14, fontSize: 13 }}>
            <input
              type="checkbox"
              checked={m3uOverwrite}
              onChange={e => setM3uOverwrite(e.target.checked)}
            />
            <span>Sobrescrever streams já existentes (mesmo ID)</span>
          </label>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              className="btn btn-ghost"
              onClick={() => m3uRef.current?.click()}
              disabled={m3uImporting}
              style={{ gap: 6 }}
            >
              <FiList size={14} />
              {m3uImporting ? 'Importando…' : 'Selecionar arquivo M3U…'}
            </button>
            <input
              ref={m3uRef}
              type="file"
              accept=".m3u,.m3u8,application/x-mpegurl,audio/x-mpegurl"
              style={{ display: 'none' }}
              onChange={handleM3uImport}
            />
          </div>

          {m3uResult && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, color: 'var(--success)', fontSize: 13 }}>
              <FiCheckCircle size={14} />
              Importado: {m3uResult.created} criados · {m3uResult.updated} atualizados · {m3uResult.skipped} ignorados · {m3uResult.errors} erros
            </div>
          )}
          {m3uError && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 12, color: 'var(--danger)', fontSize: 13 }}>
              <FiAlertCircle size={14} /> {m3uError}
            </div>
          )}
        </div>

        {error && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--danger)', fontSize: 13, marginBottom: 12 }}>
            <FiAlertCircle size={14} /> {error}
          </div>
        )}

        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            <FiSave size={14} /> {saving ? 'Salvando…' : 'Salvar configurações'}
          </button>
          {saved && <span style={{ fontSize: 13, color: 'var(--success)' }}>✓ Salvo com sucesso</span>}
        </div>

        {/* ── Atualizações ──────────────────────────────────────────── */}
        <div className="card" style={{ padding: 24, marginTop: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4, display: 'flex', alignItems: 'center', gap: 8 }}>
            <FiGitPullRequest size={16} /> Atualizações do Sistema
          </h2>
          <p style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 16 }}>
            Verifica se há uma versão mais recente disponível no GitHub e aplica a atualização automaticamente.
            Requer <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>GH_TOKEN=ghp_xxxx</code> configurado no <code style={{ background: 'var(--bg4)', padding: '1px 5px', borderRadius: 4 }}>.env</code>.
          </p>

          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <button
              className="btn btn-ghost"
              onClick={checkUpdates}
              disabled={updateChecking || updateApplying}
              style={{ gap: 6 }}
            >
              <FiRefreshCw size={14} className={updateChecking ? 'spin' : ''} />
              {updateChecking ? 'Verificando…' : 'Verificar atualizações'}
            </button>

            {updateInfo?.update_available === true && (
              <button
                className="btn btn-primary"
                onClick={applyUpdate}
                disabled={updateApplying}
                style={{ gap: 6 }}
              >
                <FiDownload size={14} />
                {updateApplying ? 'Atualizando…' : 'Atualizar agora'}
              </button>
            )}
          </div>

          {/* Status card */}
          {updateInfo && (
            <div style={{
              marginTop: 14, padding: '12px 14px', borderRadius: 8,
              background: updateInfo.update_available === true
                ? 'rgba(var(--accent-rgb,59,130,246),0.08)'
                : updateInfo.update_available === false
                ? 'rgba(var(--success-rgb,34,197,94),0.08)'
                : 'var(--bg3)',
              border: `1px solid ${updateInfo.update_available === true ? 'var(--accent)' : updateInfo.update_available === false ? 'var(--success)' : 'var(--border)'}`,
              fontSize: 13,
            }}>
              <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap' }}>
                <span>Versão atual: <strong>{updateInfo.current}</strong></span>
                {updateInfo.latest && (
                  <span>Última versão: <strong>{updateInfo.latest}</strong></span>
                )}
              </div>
              {updateInfo.update_available === true && updateInfo.latest_message && (
                <div style={{ marginTop: 6, color: 'var(--text2)' }}>
                  <strong>Novidade:</strong> {updateInfo.latest_message}
                  {updateInfo.latest_author && (
                    <span style={{ color: 'var(--text3)', marginLeft: 8 }}>— {updateInfo.latest_author}</span>
                  )}
                </div>
              )}
              {updateInfo.update_available === false && (
                <div style={{ marginTop: 4, color: 'var(--success)' }}>✓ O sistema está atualizado.</div>
              )}
              {updateInfo.update_available === null && updateInfo.message && (
                <div style={{ marginTop: 4, color: 'var(--text3)' }}>{updateInfo.message}</div>
              )}
            </div>
          )}

          {/* Mensagem de início de update */}
          {updateMsg && (
            <div style={{ marginTop: 10, fontSize: 13, color: 'var(--accent)' }}>
              ℹ️ {updateMsg}
            </div>
          )}

          {/* Log expansível */}
          {updateLogOpen && (
            <div style={{ marginTop: 12 }}>
              <button
                onClick={() => setUpdateLogOpen(o => !o)}
                style={{
                  background: 'none', border: 'none', cursor: 'pointer',
                  color: 'var(--text3)', fontSize: 12, display: 'flex', alignItems: 'center', gap: 4, marginBottom: 6,
                }}
              >
                {updateLogOpen ? <FiChevronUp size={12} /> : <FiChevronDown size={12} />}
                Log de atualização
              </button>
              <div
                ref={updateLogRef}
                style={{
                  background: 'var(--bg1)', borderRadius: 6, padding: '10px 12px',
                  fontFamily: 'monospace', fontSize: 11, maxHeight: 220,
                  overflowY: 'auto', whiteSpace: 'pre-wrap', color: 'var(--text2)',
                  border: '1px solid var(--border)',
                }}
              >
                {updateLog.length > 0
                  ? updateLog.join('')
                  : <span style={{ color: 'var(--text3)' }}>Aguardando saída…</span>
                }
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
