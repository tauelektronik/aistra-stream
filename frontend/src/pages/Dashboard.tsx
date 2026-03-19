import { useEffect, useState, useCallback } from 'react'
import {
  FiVideo, FiPlay, FiSquare, FiAlertCircle, FiRefreshCw, FiArrowRight,
  FiCpu, FiHardDrive, FiWifi, FiMonitor,
} from 'react-icons/fi'
import { NavLink } from 'react-router-dom'
import api from '../api'

interface Stream {
  id: string
  name: string
  status: string
  video_codec: string
  url: string
}

interface ServerStats {
  cpu_pct: number
  mem_used_gb: number
  mem_total_gb: number
  mem_pct: number
  disk_used_gb: number
  disk_total_gb: number
  disk_pct: number
  net_up_mbps: number
  net_down_mbps: number
  gpu: {
    name: string
    utilization_pct: number
    memory_used_mb: number
    memory_total_mb: number
    temperature_c: number
  } | null
}

// ─── Progress bar ─────────────────────────────────────────────────────────────

function Bar({ pct, color = 'var(--accent)' }: { pct: number; color?: string }) {
  const c = pct > 90 ? 'var(--danger)' : pct > 70 ? 'var(--warning)' : color
  return (
    <div style={{ height: 5, borderRadius: 3, background: 'var(--bg4)', overflow: 'hidden', marginTop: 6 }}>
      <div style={{ height: '100%', width: `${Math.min(pct, 100)}%`, background: c, borderRadius: 3, transition: 'width .4s' }} />
    </div>
  )
}

// ─── Stat resource card ───────────────────────────────────────────────────────

function ResCard({ icon, title, value, sub, pct, color }: {
  icon: React.ReactNode; title: string; value: string; sub: string; pct: number; color?: string
}) {
  return (
    <div className="card" style={{ padding: '14px 16px', minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
        <span style={{ color: color || 'var(--accent)' }}>{icon}</span>
        <span style={{ fontSize: 12, color: 'var(--text3)', fontWeight: 500 }}>{title}</span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: 'var(--text)', lineHeight: 1 }}>{value}</div>
      <div style={{ fontSize: 11, color: 'var(--text3)', marginTop: 3 }}>{sub}</div>
      <Bar pct={pct} color={color} />
    </div>
  )
}

export default function Dashboard() {
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const [streams, setStreams]     = useState<Stream[]>([])
  const [loading, setLoading]     = useState(true)
  const [sysStats, setSysStats]   = useState<ServerStats | null>(null)
  const [statsErr, setStatsErr]   = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await api.get('/api/streams')
      setStreams(r.data)
    } finally {
      setLoading(false)
    }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const r = await api.get('/api/server/stats')
      setSysStats(r.data)
      setStatsErr(false)
    } catch {
      setStatsErr(true)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { const t = setInterval(load, 15000);    return () => clearInterval(t) }, [load])
  useEffect(() => { const t = setInterval(loadStats, 5000); return () => clearInterval(t) }, [loadStats])

  const total         = streams.length
  const running       = streams.filter(s => s.status === 'running').length
  const stopped       = streams.filter(s => s.status === 'stopped').length
  const errors        = streams.filter(s => s.status === 'error').length
  const runningStreams = streams.filter(s => s.status === 'running')
  const gpuStreams     = runningStreams.filter(s => s.video_codec.includes('nvenc') || s.video_codec.includes('qsv'))

  function fmtNet(mbps: number) {
    if (mbps >= 1000) return `${(mbps / 1000).toFixed(1)} Gbps`
    if (mbps >= 1)    return `${mbps.toFixed(1)} Mbps`
    return `${(mbps * 1024).toFixed(0)} kbps`
  }

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
          <button className="btn btn-ghost btn-sm" onClick={() => { load(); loadStats() }}>
            <FiRefreshCw size={13} /> Atualizar
          </button>
        </div>
      </div>

      <div className="page-content">
        {loading ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 48 }}>Carregando…</div>
        ) : (
          <>
            {/* ── Streams stats row ── */}
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

            {/* ── Server resources ── */}
            <div style={{ marginTop: 20, marginBottom: 8 }}>
              <div className="section-title">Recursos do Servidor</div>
              {statsErr ? (
                <div style={{ color: 'var(--text3)', fontSize: 13 }}>Não foi possível carregar os dados do servidor.</div>
              ) : !sysStats ? (
                <div style={{ color: 'var(--text3)', fontSize: 13 }}>Carregando…</div>
              ) : (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
                    {/* CPU */}
                    <ResCard
                      icon={<FiCpu size={15} />}
                      title="CPU"
                      value={`${sysStats.cpu_pct}%`}
                      sub="Uso atual"
                      pct={sysStats.cpu_pct}
                    />

                    {/* RAM */}
                    <ResCard
                      icon={<FiMonitor size={15} />}
                      title="Memória RAM"
                      value={`${sysStats.mem_used_gb} GB`}
                      sub={`de ${sysStats.mem_total_gb} GB — ${sysStats.mem_pct}%`}
                      pct={sysStats.mem_pct}
                      color="var(--success)"
                    />

                    {/* Disk */}
                    <ResCard
                      icon={<FiHardDrive size={15} />}
                      title="Disco (HD)"
                      value={`${sysStats.disk_used_gb} GB`}
                      sub={`de ${sysStats.disk_total_gb} GB — ${sysStats.disk_pct}%`}
                      pct={sysStats.disk_pct}
                      color="var(--warning)"
                    />

                    {/* Network UP */}
                    <div className="card" style={{ padding: '14px 16px', minWidth: 0 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                        <span style={{ color: 'var(--accent)' }}><FiWifi size={15} /></span>
                        <span style={{ fontSize: 12, color: 'var(--text3)', fontWeight: 500 }}>Rede</span>
                      </div>
                      <div style={{ display: 'flex', gap: 16 }}>
                        <div>
                          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>▲ Upload</div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{fmtNet(sysStats.net_up_mbps)}</div>
                        </div>
                        <div>
                          <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 2 }}>▼ Download</div>
                          <div style={{ fontSize: 16, fontWeight: 700, color: 'var(--text)' }}>{fmtNet(sysStats.net_down_mbps)}</div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* GPU section */}
                  {sysStats.gpu && (
                    <div className="card" style={{ marginTop: 10, padding: '14px 16px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                        <span style={{ color: '#a78bfa' }}><FiMonitor size={15} /></span>
                        <span style={{ fontWeight: 600, fontSize: 13 }}>GPU — {sysStats.gpu.name}</span>
                        <span style={{ marginLeft: 'auto', fontSize: 11, color: 'var(--text3)' }}>
                          🌡️ {sysStats.gpu.temperature_c}°C
                        </span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
                        <div>
                          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Utilização GPU</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: '#a78bfa' }}>{sysStats.gpu.utilization_pct}%</div>
                          <Bar pct={sysStats.gpu.utilization_pct} color="#a78bfa" />
                        </div>
                        <div>
                          <div style={{ fontSize: 11, color: 'var(--text3)' }}>Memória GPU</div>
                          <div style={{ fontSize: 18, fontWeight: 700, color: '#a78bfa' }}>
                            {(sysStats.gpu.memory_used_mb / 1024).toFixed(1)} GB
                          </div>
                          <div style={{ fontSize: 11, color: 'var(--text3)' }}>
                            de {(sysStats.gpu.memory_total_mb / 1024).toFixed(0)} GB
                          </div>
                          <Bar pct={Math.round(sysStats.gpu.memory_used_mb / sysStats.gpu.memory_total_mb * 100)} color="#a78bfa" />
                        </div>
                        {gpuStreams.length > 0 && (
                          <div>
                            <div style={{ fontSize: 11, color: 'var(--text3)', marginBottom: 4 }}>Streams em GPU ({gpuStreams.length})</div>
                            {gpuStreams.map(s => (
                              <div key={s.id} style={{ fontSize: 12, color: 'var(--text2)', display: 'flex', alignItems: 'center', gap: 5, marginBottom: 3 }}>
                                <span style={{ color: 'var(--success)', fontSize: 9 }}>●</span>
                                {s.name}
                                <span style={{ fontSize: 10, color: 'var(--text3)' }}>({s.video_codec})</span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>

            {/* ── Running streams ── */}
            <div style={{ marginTop: 16 }}>
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

            {/* ── Error streams ── */}
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
