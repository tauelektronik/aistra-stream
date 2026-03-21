import { useEffect, useState, useCallback } from 'react'
import {
  FiVideo, FiPlay, FiSquare, FiAlertCircle, FiRefreshCw,
  FiCpu, FiHardDrive, FiWifi, FiMonitor,
} from 'react-icons/fi'
import api from '../api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface Stream {
  id: string; name: string; status: string; video_codec: string; url: string
}

interface ServerStats {
  cpu_pct: number
  cpu_per_core: number[]
  cpu_name: string
  cpu_freq_mhz: number
  cpu_temp_c: number | null
  mem_used_gb: number; mem_total_gb: number; mem_pct: number
  mem_swap_pct: number; mem_swap_used_gb: number; mem_swap_total_gb: number
  disk_used_gb: number; disk_total_gb: number; disk_pct: number
  net_up_mbps: number; net_down_mbps: number
  net_up_total_gb: number; net_down_total_gb: number
  gpu: {
    name: string
    utilization_pct: number
    enc_pct: number
    dec_pct: number
    memory_used_mb: number; memory_total_mb: number
    temperature_c: number
  } | null
}

// ── Constants ─────────────────────────────────────────────────────────────────

const MAX_HIST = 60  // 5 min @ 5 s/sample

// 16 distinct colors for CPU cores
const CORE_COLORS = [
  '#4ade80', '#f87171', '#facc15', '#60a5fa', '#c084fc', '#fb923c',
  '#34d399', '#e879f9', '#38bdf8', '#a3e635', '#f472b6', '#22d3ee',
  '#fbbf24', '#818cf8', '#2dd4bf', '#fb7185',
]

// ── SVG Chart ─────────────────────────────────────────────────────────────────

interface Series { label: string; data: number[]; color: string; bold?: boolean; fill?: boolean }

function Chart({
  series, height = 130, yFmt = (v: number) => `${v}%`,
}: {
  series: Series[]; height?: number; yFmt?: (v: number) => string
}) {
  // viewBox fixed at 500×height — preserveAspectRatio="none" stretches to container
  const W = 500, H = height
  const PL = 28, PR = 4, PT = 4, PB = 14
  const cW = W - PL - PR, cH = H - PT - PB
  const maxPts = Math.max(...series.map(s => s.data.length), 2)
  const xv = (i: number) => PL + (i / Math.max(maxPts - 1, 1)) * cW
  const yv = (v: number) => PT + (1 - Math.min(Math.max(v, 0), 100) / 100) * cH

  const gridVals = [0, 20, 40, 60, 80, 100]

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ width: '100%', height, display: 'block' }}
    >
      {/* Background */}
      <rect x={PL} y={PT} width={cW} height={cH} fill="var(--bg)" rx="2" />

      {/* Grid lines + Y labels */}
      {gridVals.map(v => (
        <g key={v}>
          <line
            x1={PL} y1={yv(v)} x2={W - PR} y2={yv(v)}
            stroke="var(--border)"
            strokeWidth={v === 0 || v === 100 ? '0.8' : '0.4'}
          />
          <text x={PL - 2} y={yv(v) + 3} textAnchor="end" fontSize="6" fill="var(--text3)">
            {yFmt(v)}
          </text>
        </g>
      ))}

      {/* "← 5 min" / "agora →" axis hints */}
      {maxPts >= 2 && (
        <>
          <text x={PL + 2} y={H - 2} fontSize="5.5" fill="var(--text3)">← 5min</text>
          <text x={W - PR - 2} y={H - 2} textAnchor="end" fontSize="5.5" fill="var(--text3)">agora</text>
        </>
      )}

      {/* Data: fill then line (order matters for layering) */}
      {series.map(s => {
        const d = s.data.length === 1 ? [s.data[0], s.data[0]] : s.data
        if (d.length < 2) return null
        const pts = d.map((v, i) => `${xv(i).toFixed(1)},${yv(v).toFixed(1)}`).join(' ')
        const last = d.length - 1
        const fillPts =
          `${xv(0).toFixed(1)},${yv(0).toFixed(1)} ` + pts +
          ` ${xv(last).toFixed(1)},${yv(0).toFixed(1)}`
        return (
          <g key={s.label}>
            {s.fill && (
              <polygon points={fillPts} fill={s.color} fillOpacity={0.12} />
            )}
            <polyline
              points={pts}
              fill="none"
              stroke={s.color}
              strokeWidth={s.bold ? '2' : '1'}
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </g>
        )
      })}
    </svg>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend({ series }: { series: Series[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '3px 10px', marginBottom: 6 }}>
      {series.map(s => (
        <span key={s.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 10, color: 'var(--text3)' }}>
          <span style={{ width: 14, height: 2, background: s.color, borderRadius: 1, flexShrink: 0, display: 'inline-block' }} />
          {s.label}
        </span>
      ))}
    </div>
  )
}

// ── Badge ─────────────────────────────────────────────────────────────────────

function Badge({ children, color }: { children: React.ReactNode; color: string }) {
  return (
    <span style={{
      fontSize: 10, fontWeight: 600, padding: '2px 8px', borderRadius: 10,
      background: color + '25', color, border: `1px solid ${color}50`,
      display: 'inline-flex', alignItems: 'center', gap: 3,
    }}>
      {children}
    </span>
  )
}

// ── Section card ──────────────────────────────────────────────────────────────

function SectionCard({ icon, title, badges, children }: {
  icon: React.ReactNode; title: string; badges?: React.ReactNode; children: React.ReactNode
}) {
  return (
    <div className="card" style={{ padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--text3)' }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>{title}</span>
        {badges}
      </div>
      {children}
    </div>
  )
}

// ── Dashboard ─────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const [streams, setStreams]   = useState<Stream[]>([])
  const [loading, setLoading]  = useState(true)
  const [sysStats, setSysStats] = useState<ServerStats | null>(null)
  const [statsErr, setStatsErr] = useState(false)
  const [history, setHistory]  = useState<ServerStats[]>([])

  const load = useCallback(async () => {
    try { const r = await api.get('/api/streams'); setStreams(r.data) }
    finally { setLoading(false) }
  }, [])

  const loadStats = useCallback(async () => {
    try {
      const r = await api.get('/api/server/stats')
      if (!r.data.error) {
        setSysStats(r.data)
        setHistory(prev => {
          const next = [...prev, r.data as ServerStats]
          return next.length > MAX_HIST ? next.slice(-MAX_HIST) : next
        })
      }
      setStatsErr(false)
    } catch { setStatsErr(true) }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { loadStats() }, [loadStats])
  useEffect(() => { const t = setInterval(load, 15000);    return () => clearInterval(t) }, [load])
  useEffect(() => { const t = setInterval(loadStats, 5000); return () => clearInterval(t) }, [loadStats])

  // ── Stream counts ───────────────────────────────────────────────────────────
  const total   = streams.length
  const running = streams.filter(s => s.status === 'running').length
  const stopped = streams.filter(s => s.status === 'stopped').length
  const errors  = streams.filter(s => s.status === 'error').length
  const gpuStreams = streams.filter(s =>
    s.status === 'running' && (s.video_codec.includes('nvenc') || s.video_codec.includes('qsv'))
  )

  // ── Helpers ─────────────────────────────────────────────────────────────────
  function fmtNet(mbps: number) {
    const kbps = mbps * 1024
    if (kbps >= 1024) return `${mbps.toFixed(1)} Mbps`
    if (kbps >= 1)    return `${kbps.toFixed(0)} Kbps`
    return `${(kbps * 1024).toFixed(0)} bps`
  }

  // ── Derived chart series ────────────────────────────────────────────────────
  const coreCount = sysStats?.cpu_per_core?.length ?? 0

  const cpuSeries: Series[] = [
    ...CORE_COLORS.slice(0, coreCount).map((color, i) => ({
      label: `CPU${i} ${sysStats?.cpu_per_core?.[i] ?? 0}%`,
      data:  history.map(h => h.cpu_per_core?.[i] ?? 0),
      color,
    })),
    {
      label: `Total ${sysStats?.cpu_pct ?? 0}%`,
      data:  history.map(h => h.cpu_pct),
      color: '#e2e8f0',
      bold:  true,
      fill:  true,
    },
  ]

  const memSeries: Series[] = [
    {
      label: `Mem ${sysStats?.mem_pct ?? 0}%  ${sysStats?.mem_used_gb ?? 0} / ${sysStats?.mem_total_gb ?? 0} GiB`,
      data:  history.map(h => h.mem_pct),
      color: '#4ade80', bold: true, fill: true,
    },
    ...(( sysStats?.mem_swap_total_gb ?? 0) > 0 ? [{
      label: `Swap ${sysStats?.mem_swap_pct ?? 0}%  ${sysStats?.mem_swap_used_gb ?? 0} / ${sysStats?.mem_swap_total_gb ?? 0} GiB`,
      data:  history.map(h => h.mem_swap_pct ?? 0),
      color: '#facc15',
    }] : []),
  ]

  const netPeak  = Math.max(...history.map(h => Math.max(h.net_up_mbps, h.net_down_mbps)), 0.001)
  const netSeries: Series[] = [
    {
      label: `↑ ${fmtNet(sysStats?.net_up_mbps ?? 0)}  ·  ${sysStats?.net_up_total_gb ?? 0} GiB enviados`,
      data:  history.map(h => (h.net_up_mbps / netPeak) * 100),
      color: '#60a5fa', bold: true,
    },
    {
      label: `↓ ${fmtNet(sysStats?.net_down_mbps ?? 0)}  ·  ${sysStats?.net_down_total_gb ?? 0} GiB recebidos`,
      data:  history.map(h => (h.net_down_mbps / netPeak) * 100),
      color: '#4ade80',
    },
  ]
  const netFmt = (pct: number) => fmtNet((pct / 100) * netPeak)

  const gpu = sysStats?.gpu ?? null
  const gpuMemPct = gpu ? Math.round(gpu.memory_used_mb / gpu.memory_total_mb * 100) : 0
  const gpuSeries: Series[] = gpu ? [
    {
      label: `GPU ${gpu.utilization_pct}%`,
      data:  history.map(h => h.gpu?.utilization_pct ?? 0),
      color: '#c084fc', bold: true, fill: true,
    },
    {
      label: `Mem ${gpuMemPct}%  ${(gpu.memory_used_mb / 1024).toFixed(2)} / ${(gpu.memory_total_mb / 1024).toFixed(0)} GiB`,
      data:  history.map(h => h.gpu ? Math.round(h.gpu.memory_used_mb / h.gpu.memory_total_mb * 100) : 0),
      color: '#f87171',
    },
    {
      label: `Enc ${gpu.enc_pct ?? 0}%`,
      data:  history.map(h => h.gpu?.enc_pct ?? 0),
      color: '#facc15',
    },
    {
      label: `Dec ${gpu.dec_pct ?? 0}%`,
      data:  history.map(h => h.gpu?.dec_pct ?? 0),
      color: '#a3e635',
    },
    {
      // temperature scaled to 120 °C max so it fits the 0-100 chart axis
      label: `Temp ${gpu.temperature_c}°C`,
      data:  history.map(h => h.gpu ? Math.round(h.gpu.temperature_c / 120 * 100) : 0),
      color: '#fb923c',
    },
  ] : []

  // ── Render ──────────────────────────────────────────────────────────────────
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
            {/* ── Contadores de streams ── */}
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

            {/* ── Monitoramento do servidor ── */}
            <div style={{ marginTop: 16 }}>
              {statsErr ? (
                <div className="card" style={{ padding: 16, color: 'var(--text3)', fontSize: 13 }}>
                  Não foi possível carregar dados do servidor.
                </div>
              ) : !sysStats ? (
                <div style={{ color: 'var(--text3)', fontSize: 13 }}>Coletando dados do servidor…</div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>

                  {/* ── CPU ── */}
                  <SectionCard
                    icon={<FiCpu size={14} />}
                    title={sysStats.cpu_name || 'CPU'}
                    badges={<>
                      <Badge color="var(--accent)">CPU {sysStats.cpu_pct}%</Badge>
                      {sysStats.cpu_temp_c != null && (
                        <Badge color="#fb923c">Temp {sysStats.cpu_temp_c}°C</Badge>
                      )}
                      {sysStats.cpu_freq_mhz > 0 && (
                        <Badge color="var(--text2)">Freq {sysStats.cpu_freq_mhz.toLocaleString()} MHz</Badge>
                      )}
                    </>}
                  >
                    <Legend series={cpuSeries} />
                    <Chart series={cpuSeries} height={130} />
                  </SectionCard>

                  {/* ── Memória + Rede ── */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 10 }}>

                    {/* Memória */}
                    <SectionCard
                      icon={<FiMonitor size={14} />}
                      title="Memory Usage"
                      badges={<>
                        <Badge color="#4ade80">Mem {sysStats.mem_pct}%</Badge>
                        {(sysStats.mem_swap_total_gb ?? 0) > 0 && (
                          <Badge color="#facc15">Swap {sysStats.mem_swap_pct}%</Badge>
                        )}
                      </>}
                    >
                      <Legend series={memSeries} />
                      <Chart series={memSeries} height={120} />
                    </SectionCard>

                    {/* Rede */}
                    <SectionCard
                      icon={<FiWifi size={14} />}
                      title="Network Usage"
                      badges={<>
                        <Badge color="#60a5fa">↑ {fmtNet(sysStats.net_up_mbps)}</Badge>
                        <Badge color="#4ade80">↓ {fmtNet(sysStats.net_down_mbps)}</Badge>
                      </>}
                    >
                      <Legend series={netSeries} />
                      <Chart series={netSeries} height={120} yFmt={netFmt} />
                    </SectionCard>
                  </div>

                  {/* ── Disco ── */}
                  <SectionCard
                    icon={<FiHardDrive size={14} />}
                    title="Disco"
                    badges={<>
                      <Badge color={sysStats.disk_pct > 90 ? 'var(--danger)' : sysStats.disk_pct > 70 ? 'var(--warning)' : 'var(--text2)'}>
                        {sysStats.disk_pct}%
                      </Badge>
                      <Badge color="var(--text3)">
                        {sysStats.disk_used_gb} / {sysStats.disk_total_gb} GB
                      </Badge>
                    </>}
                  >
                    <div style={{ height: 10, borderRadius: 5, background: 'var(--bg4)', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%',
                        width: `${Math.min(sysStats.disk_pct, 100)}%`,
                        background: sysStats.disk_pct > 90 ? 'var(--danger)' : sysStats.disk_pct > 70 ? 'var(--warning)' : 'var(--accent)',
                        borderRadius: 5,
                        transition: 'width .4s',
                      }} />
                    </div>
                    <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text3)' }}>
                      {sysStats.disk_used_gb} GB usados de {sysStats.disk_total_gb} GB ({sysStats.disk_pct}%)
                    </div>
                  </SectionCard>

                  {/* ── GPU ── */}
                  {gpu && (
                    <SectionCard
                      icon={<FiMonitor size={14} />}
                      title={`${gpu.name} ${(gpu.memory_total_mb / 1024).toFixed(0)}GB`}
                      badges={<>
                        <Badge color="#c084fc">GPU {gpu.utilization_pct}%</Badge>
                        {gpuStreams.length > 0 && (
                          <Badge color="var(--success)">Running: {gpuStreams.length}</Badge>
                        )}
                        {(gpu.enc_pct ?? 0) > 0 && <Badge color="#facc15">Enc {gpu.enc_pct}%</Badge>}
                        {(gpu.dec_pct ?? 0) > 0 && <Badge color="#a3e635">Dec {gpu.dec_pct}%</Badge>}
                        <Badge color="#fb923c">🌡 {gpu.temperature_c}°C</Badge>
                      </>}
                    >
                      <Legend series={gpuSeries} />
                      <Chart series={gpuSeries} height={130} />
                    </SectionCard>
                  )}

                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
