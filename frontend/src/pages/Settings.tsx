import { useEffect, useRef, useState } from 'react'
import { FiSave, FiAlertCircle, FiDownload, FiUpload, FiCheckCircle, FiPlus, FiTrash2, FiChevronDown, FiChevronUp } from 'react-icons/fi'
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

  // Backup / restore state
  const [downloading, setDownloading]   = useState(false)
  const [restoring, setRestoring]       = useState(false)
  const [restoreResult, setRestoreResult] = useState<{ created: number; updated: number; skipped: number } | null>(null)
  const [restoreError, setRestoreError] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    api.get('/api/settings')
      .then(r => {
        const data = r.data || {}
        setForm(data)
        // Parse comma-separated chat IDs into array
        const ids = (data.telegram_chat_id || '').split(',').map((s: string) => s.trim()).filter(Boolean)
        setChatIds(ids.length > 0 ? ids : [''])
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

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
