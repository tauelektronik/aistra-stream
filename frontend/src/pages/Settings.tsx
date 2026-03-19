import { useEffect, useRef, useState } from 'react'
import { FiSave, FiAlertCircle, FiDownload, FiUpload, FiCheckCircle } from 'react-icons/fi'
import api from '../api'

interface SettingsData {
  telegram_bot_token?: string
  telegram_chat_id?: string
  watchdog_enabled?: boolean
  max_restarts?: number
  yt_refresh_hours?: number
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

export default function Settings() {
  const [form, setForm]       = useState<SettingsData>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving]   = useState(false)
  const [saved, setSaved]     = useState(false)
  const [error, setError]     = useState('')

  // Backup / restore state
  const [downloading, setDownloading]   = useState(false)
  const [restoring, setRestoring]       = useState(false)
  const [restoreResult, setRestoreResult] = useState<{ created: number; updated: number; skipped: number } | null>(null)
  const [restoreError, setRestoreError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get('/api/settings')
      .then(r => setForm(r.data || {}))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  function set(k: keyof SettingsData, v: any) {
    setForm(f => ({ ...f, [k]: v }))
  }

  async function save() {
    setSaving(true); setSaved(false); setError('')
    try {
      await api.put('/api/settings', form)
      setSaved(true)
      setTimeout(() => setSaved(false), 3000)
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Erro ao salvar')
    } finally {
      setSaving(false)
    }
  }

  async function downloadBackup() {
    setDownloading(true)
    try {
      const res = await fetch('/api/settings/backup', {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      const date = new Date().toISOString().slice(0, 10)
      a.href = url
      a.download = `aistra-backup-${date}.json`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError('Erro ao fazer download do backup')
    } finally {
      setDownloading(false)
    }
  }

  async function handleRestore(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    // Reset input so same file can be re-selected
    e.target.value = ''

    setRestoring(true); setRestoreResult(null); setRestoreError('')
    try {
      const text = await file.text()
      const json = JSON.parse(text)
      const res  = await api.post('/api/settings/restore', json)
      setRestoreResult(res.data)
      setTimeout(() => setRestoreResult(null), 6000)
    } catch (e: any) {
      setRestoreError(e.response?.data?.detail || 'Arquivo inválido ou erro ao restaurar')
      setTimeout(() => setRestoreError(''), 6000)
    } finally {
      setRestoring(false)
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

        {/* Telegram Notifications */}
        <div className="card" style={{ padding: 24, marginBottom: 16 }}>
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 16 }}>Notificações Telegram</h2>
          <Row
            label="Bot Token"
            hint="Token do bot criado via @BotFather. Deixe em branco para desativar."
          >
            <input
              type="password"
              value={form.telegram_bot_token ?? ''}
              onChange={e => set('telegram_bot_token', e.target.value)}
              placeholder="1234567890:ABCdefGhIJKlmNoPQRstu..."
              autoComplete="off"
            />
          </Row>
          <Row
            label="Chat ID"
            hint="ID do chat ou canal que receberá as notificações (ex: -1001234567890)."
          >
            <input
              value={form.telegram_chat_id ?? ''}
              onChange={e => set('telegram_chat_id', e.target.value)}
              placeholder="-1001234567890"
            />
          </Row>
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
          <h2 style={{ fontSize: 15, fontWeight: 600, marginBottom: 4 }}>Backup e Restauração</h2>
          <p style={{ fontSize: 13, color: 'var(--text3)', marginBottom: 16 }}>
            O backup inclui todos os streams cadastrados e as configurações do painel.
            O Token do Telegram <strong>não</strong> é incluído por segurança.
          </p>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <button
              className="btn btn-ghost"
              onClick={downloadBackup}
              disabled={downloading}
              style={{ gap: 6 }}
            >
              <FiDownload size={14} />
              {downloading ? 'Gerando…' : 'Baixar backup (.json)'}
            </button>

            <button
              className="btn btn-ghost"
              onClick={() => fileRef.current?.click()}
              disabled={restoring}
              style={{ gap: 6 }}
            >
              <FiUpload size={14} />
              {restoring ? 'Restaurando…' : 'Restaurar backup…'}
            </button>
            <input
              ref={fileRef}
              type="file"
              accept=".json,application/json"
              style={{ display: 'none' }}
              onChange={handleRestore}
            />
          </div>

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
      </div>
    </div>
  )
}
