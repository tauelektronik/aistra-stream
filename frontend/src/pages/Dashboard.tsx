import { useEffect, useState, useCallback } from 'react'
import { FiVideo, FiPlay, FiSquare, FiAlertCircle, FiRefreshCw, FiArrowRight } from 'react-icons/fi'
import { NavLink } from 'react-router-dom'
import api from '../api'

interface Stream {
  id: string
  name: string
  status: string
  video_codec: string
  url: string
}

export default function Dashboard() {
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const [streams, setStreams]   = useState<Stream[]>([])
  const [loading, setLoading]   = useState(true)

  const load = useCallback(async () => {
    try {
      const r = await api.get('/api/streams')
      setStreams(r.data)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 15000); return () => clearInterval(t) }, [load])

  const total   = streams.length
  const running = streams.filter(s => s.status === 'running').length
  const stopped = streams.filter(s => s.status === 'stopped').length
  const errors  = streams.filter(s => s.status === 'error').length
  const runningStreams = streams.filter(s => s.status === 'running')

  return (
    <div className="page">
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p style={{ fontSize: 12, color: 'var(--text3)', marginTop: 3 }}>
            Bem-vindo, <span style={{ color: 'var(--text2)', fontWeight: 500 }}>{user.username || 'usuário'}</span>
          </p>
        </div>
        <div className="page-header-actions">
          <button className="btn btn-ghost btn-sm" onClick={load}>
            <FiRefreshCw size={13} /> Atualizar
          </button>
        </div>
      </div>

      <div className="page-content">
        {loading ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 48 }}>Carregando…</div>
        ) : (
          <>
            {/* Stats row */}
            <div className="stats-row">
              <div className="stat-card">
                <div className="stat-icon" style={{ color: 'var(--accent)' }}><FiVideo size={14} /></div>
                <div className="stat-value" style={{ color: 'var(--accent)' }}>{total}</div>
                <div className="stat-label">Total de Streams</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon" style={{ color: 'var(--success)' }}><FiPlay size={14} /></div>
                <div className="stat-value" style={{ color: 'var(--success)' }}>{running}</div>
                <div className="stat-label">Rodando</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon" style={{ color: 'var(--text3)' }}><FiSquare size={14} /></div>
                <div className="stat-value" style={{ color: 'var(--text3)' }}>{stopped}</div>
                <div className="stat-label">Parado</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon" style={{ color: errors > 0 ? 'var(--danger)' : 'var(--text3)' }}>
                  <FiAlertCircle size={14} />
                </div>
                <div className="stat-value" style={{ color: errors > 0 ? 'var(--danger)' : 'var(--text3)' }}>{errors}</div>
                <div className="stat-label">Erro</div>
              </div>
            </div>

            {/* Running streams */}
            <div style={{ marginTop: 8 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
                <div className="section-title" style={{ marginBottom: 0 }}>Streams ativos</div>
                <NavLink to="/streams" style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: 'var(--accent)' }}>
                  Ver todos <FiArrowRight size={12} />
                </NavLink>
              </div>

              {runningStreams.length === 0 ? (
                <div className="card" style={{ padding: 0 }}>
                  <div className="empty-state">
                    <FiVideo size={48} color="var(--text3)" style={{ opacity: 0.4 }} />
                    <p>Nenhum stream ativo no momento.</p>
                    <NavLink to="/streams" className="btn btn-ghost btn-sm">
                      Gerenciar Streams
                    </NavLink>
                  </div>
                </div>
              ) : (
                <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Nome</th>
                          <th className="col-hide-xs">ID</th>
                          <th className="col-hide-xs">Codec</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runningStreams.map(s => (
                          <tr key={s.id}>
                            <td>
                              <div style={{ fontWeight: 500, color: 'var(--text)' }}>{s.name}</div>
                              <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 2, maxWidth: 260, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                                {s.url.length > 60 ? s.url.slice(0, 60) + '…' : s.url}
                              </div>
                            </td>
                            <td className="col-hide-xs">
                              <code style={{ fontSize: 12, color: 'var(--text2)' }}>{s.id}</code>
                            </td>
                            <td className="col-hide-xs">
                              <span style={{ fontSize: 12, color: 'var(--text2)' }}>{s.video_codec}</span>
                            </td>
                            <td>
                              <span className="badge badge-running">running</span>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>

            {/* Error streams */}
            {errors > 0 && (
              <div style={{ marginTop: 20 }}>
                <div className="section-title">Streams com erro</div>
                <div className="card" style={{ padding: 0, overflow: 'hidden', borderColor: 'rgba(239,68,68,.3)' }}>
                  <div className="table-wrap">
                    <table>
                      <thead>
                        <tr>
                          <th>Nome</th>
                          <th className="col-hide-xs">ID</th>
                          <th>Status</th>
                        </tr>
                      </thead>
                      <tbody>
                        {streams.filter(s => s.status === 'error').map(s => (
                          <tr key={s.id}>
                            <td style={{ fontWeight: 500, color: 'var(--text)' }}>{s.name}</td>
                            <td className="col-hide-xs">
                              <code style={{ fontSize: 12, color: 'var(--text2)' }}>{s.id}</code>
                            </td>
                            <td><span className="badge badge-error">● error</span></td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
