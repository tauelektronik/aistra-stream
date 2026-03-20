import { useEffect, useState, useCallback } from 'react'
import { FiRefreshCw, FiTrash2, FiCheckCircle, FiXCircle, FiSearch } from 'react-icons/fi'
import api from '../api'

interface LogEntry {
  id: number
  username: string
  ip: string
  user_agent: string | null
  success: boolean
  created_at: string
}

function parseUA(ua: string | null) {
  if (!ua) return '—'
  if (/Mobile|Android|iPhone|iPad/.test(ua)) return '📱 Mobile'
  if (/Chrome/.test(ua)) return 'Chrome'
  if (/Firefox/.test(ua)) return 'Firefox'
  if (/Safari/.test(ua)) return 'Safari'
  if (/Edge/.test(ua)) return 'Edge'
  return ua.slice(0, 40)
}

function timeAgo(iso: string) {
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000)
  if (diff < 60)  return `${diff}s atrás`
  if (diff < 3600) return `${Math.floor(diff/60)}m atrás`
  if (diff < 86400) return `${Math.floor(diff/3600)}h atrás`
  return `${Math.floor(diff/86400)}d atrás`
}

export default function ConnectionLogs() {
  const [logs, setLogs]           = useState<LogEntry[]>([])
  const [loading, setLoading]     = useState(true)
  const [filter, setFilter]       = useState('')
  const [statusFilter, setStatus] = useState<'all'|'ok'|'fail'>('all')
  const [clearing, setClearing]   = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get('/api/connection-logs?limit=500')
      setLogs(r.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  async function clearLogs() {
    if (!confirm('Apagar todo o histórico de conexões?')) return
    setClearing(true)
    try {
      await api.delete('/api/connection-logs')
      setLogs([])
    } catch { /* ignore */ }
    finally { setClearing(false) }
  }

  const filtered = logs.filter(l => {
    if (statusFilter === 'ok'   && !l.success) return false
    if (statusFilter === 'fail' && l.success)  return false
    if (filter) {
      const q = filter.toLowerCase()
      return l.username.toLowerCase().includes(q) || l.ip.includes(q)
    }
    return true
  })

  const total   = logs.length
  const success = logs.filter(l => l.success).length
  const failed  = total - success

  return (
    <div className="page">
      <div className="page-header">
        <h1>Registro de Conexões</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button className="btn btn-ghost btn-sm" onClick={load} disabled={loading}>
            <FiRefreshCw size={13} className={loading ? 'spin' : ''} /> Atualizar
          </button>
          <button className="btn btn-danger btn-sm" onClick={clearLogs} disabled={clearing}>
            <FiTrash2 size={13} /> Limpar
          </button>
        </div>
      </div>

      <div className="page-content">
        {/* Stats */}
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, flexWrap: 'wrap' }}>
          {[
            { label: 'Total', value: total, color: 'var(--accent)' },
            { label: 'Sucesso', value: success, color: '#22c55e' },
            { label: 'Falha', value: failed, color: '#ef4444' },
          ].map(s => (
            <div key={s.label} className="card" style={{ padding: '10px 20px', display: 'flex', flexDirection: 'column', alignItems: 'center', minWidth: 90 }}>
              <span style={{ fontSize: 22, fontWeight: 700, color: s.color }}>{s.value}</span>
              <span style={{ fontSize: 12, color: 'var(--text3)' }}>{s.label}</span>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div className="card" style={{ padding: '12px 16px', marginBottom: 12, display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
          <div style={{ position: 'relative', flex: 1, minWidth: 180 }}>
            <FiSearch size={13} style={{ position:'absolute', left:9, top:'50%', transform:'translateY(-50%)', color:'var(--text3)' }} />
            <input
              value={filter}
              onChange={e => setFilter(e.target.value)}
              placeholder="Filtrar por usuário ou IP…"
              style={{ paddingLeft: 28, width: '100%' }}
            />
          </div>
          <div style={{ display: 'flex', gap: 6 }}>
            {(['all','ok','fail'] as const).map(s => (
              <button
                key={s}
                className={`btn btn-sm ${statusFilter === s ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setStatus(s)}
              >
                {s === 'all' ? 'Todos' : s === 'ok' ? 'Sucesso' : 'Falha'}
              </button>
            ))}
          </div>
        </div>

        {/* Table */}
        <div className="card" style={{ overflow: 'hidden', padding: 0 }}>
          {loading ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Carregando…</div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: 'center', color: 'var(--text3)' }}>Nenhum registro encontrado.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border)', background: 'var(--bg3)' }}>
                    {['Status', 'Usuário', 'IP', 'Navegador', 'Quando'].map(h => (
                      <th key={h} style={{ padding: '10px 14px', textAlign: 'left', fontWeight: 600, color: 'var(--text2)', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((l, i) => (
                    <tr key={l.id} style={{ borderBottom: '1px solid var(--border)', background: i % 2 === 0 ? 'transparent' : 'var(--bg2)' }}>
                      <td style={{ padding: '9px 14px' }}>
                        {l.success
                          ? <FiCheckCircle size={15} color="#22c55e" title="Sucesso" />
                          : <FiXCircle    size={15} color="#ef4444" title="Falha" />}
                      </td>
                      <td style={{ padding: '9px 14px', fontWeight: 500, color: 'var(--text)' }}>{l.username}</td>
                      <td style={{ padding: '9px 14px', fontFamily: 'monospace', color: 'var(--text2)' }}>{l.ip}</td>
                      <td style={{ padding: '9px 14px', color: 'var(--text3)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
                          title={l.user_agent ?? undefined}>
                        {parseUA(l.user_agent)}
                      </td>
                      <td style={{ padding: '9px 14px', color: 'var(--text3)', whiteSpace: 'nowrap' }}
                          title={new Date(l.created_at).toLocaleString('pt-BR')}>
                        {timeAgo(l.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
        {filtered.length > 0 && (
          <div style={{ marginTop: 8, fontSize: 12, color: 'var(--text3)', textAlign: 'right' }}>
            {filtered.length} registro{filtered.length !== 1 ? 's' : ''}
          </div>
        )}
      </div>
    </div>
  )
}
