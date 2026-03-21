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

const MAX_HIST = 60

const CORE_COLORS = [
  '#34d399', '#f87171', '#fbbf24', '#60a5fa', '#c084fc', '#fb923c',
  '#4ade80', '#e879f9', '#38bdf8', '#a3e635', '#f472b6', '#22d3ee',
  '#facc15', '#818cf8', '#2dd4bf', '#fb7185',
]

// ── SVG smooth path ────────────────────────────────────────────────────────────

function smoothPath(pts: [number, number][]): string {
  if (pts.length < 2) return ''
  const d: string[] = [`M ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)}`]
  for (let i = 1; i < pts.length; i++) {
    const [x0, y0] = pts[i - 1]
    const [x1, y1] = pts[i]
    const cx = ((x0 + x1) / 2).toFixed(1)
    d.push(`C ${cx} ${y0.toFixed(1)} ${cx} ${y1.toFixed(1)} ${x1.toFixed(1)} ${y1.toFixed(1)}`)
  }
  return d.join(' ')
}

// ── Chart ─────────────────────────────────────────────────────────────────────

interface Series {
  id: string
  label: string
  data: number[]   // 0–100
  color: string
  bold?: boolean
  fill?: boolean
}

function Chart({
  series, height = 140, yFmt = (v: number) => `${v}%`,
}: {
  series: Series[]; height?: number; yFmt?: (v: number) => string
}) {
  // SVG viewBox: full width W × H, no left padding — labels are HTML outside SVG
  const W = 500, H = height
  const PT = 5, PB = 5           // top/bottom padding inside SVG
  const LABEL_W = 42             // HTML label column width (px)
  const cH = H - PT - PB
  const nPts = Math.max(...series.map(s => s.data.length), 2)
  const xv = (i: number) => (i / Math.max(nPts - 1, 1)) * W
  const yv = (v: number) => PT + (1 - Math.min(Math.max(v, 0), 100) / 100) * cH

  // Y-axis grid values and their % position inside the container
  const gridVals = [100, 75, 50, 25, 0]
  const yPct = (v: number) => ((PT + (1 - v / 100) * cH) / H) * 100

  return (
    <div>
      {/* Chart row: HTML labels + SVG side by side */}
      <div style={{ display: 'flex', alignItems: 'stretch' }}>

        {/* Y-axis labels — pure HTML, never stretched */}
        <div style={{ position: 'relative', width: LABEL_W, flexShrink: 0, height }}>
          {gridVals.map(v => (
            <span key={v} style={{
              position: 'absolute',
              top: `${yPct(v)}%`,
              right: 6,
              transform: 'translateY(-50%)',
              fontSize: 10,
              color: 'var(--text3)',
              fontFamily: 'monospace',
              lineHeight: 1,
              whiteSpace: 'nowrap',
            }}>
              {yFmt(v)}
            </span>
          ))}
        </div>

        {/* SVG chart area — only lines, fills and grid (no text) */}
        <svg
          viewBox={`0 0 ${W} ${H}`}
          preserveAspectRatio="none"
          style={{ flex: 1, height, display: 'block' }}
        >
          <defs>
            {series.filter(s => s.fill).map(s => (
              <linearGradient key={s.id} id={`grad-${s.id}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%"   stopColor={s.color} stopOpacity="0.38" />
                <stop offset="80%"  stopColor={s.color} stopOpacity="0.05" />
                <stop offset="100%" stopColor={s.color} stopOpacity="0"    />
              </linearGradient>
            ))}
            <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="2" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            <clipPath id="chart-clip">
              <rect x={0} y={PT} width={W} height={cH} />
            </clipPath>
          </defs>

          {/* Background */}
          <rect x={0} y={PT} width={W} height={cH}
            fill="var(--bg)" rx="3"
            stroke="var(--border)" strokeWidth="0.6"
          />

          {/* Grid lines only — no text */}
          {gridVals.map(v => (
            <line key={v}
              x1={0} y1={yv(v)} x2={W} y2={yv(v)}
              stroke="var(--border)"
              strokeWidth={v === 0 || v === 100 ? '0.8' : '0.45'}
              strokeDasharray={v === 0 || v === 100 ? undefined : '4 5'}
            />
          ))}

          {/* Fills + lines */}
          <g clipPath="url(#chart-clip)">
            {series.filter(s => s.fill).map(s => {
              const d = s.data.length === 1 ? [s.data[0], s.data[0]] : s.data
              if (d.length < 2) return null
              const pts: [number, number][] = d.map((v, i) => [xv(i), yv(v)])
              const last = pts.length - 1
              const fillD =
                `M ${pts[0][0].toFixed(1)} ${yv(0).toFixed(1)} ` +
                `L ${pts[0][0].toFixed(1)} ${pts[0][1].toFixed(1)} ` +
                smoothPath(pts).replace(/^M [^ ]+ [^ ]+/, '') +
                ` L ${pts[last][0].toFixed(1)} ${yv(0).toFixed(1)} Z`
              return <path key={`fill-${s.id}`} d={fillD} fill={`url(#grad-${s.id})`} />
            })}

            {series.map(s => {
              const d = s.data.length === 1 ? [s.data[0], s.data[0]] : s.data
              if (d.length < 2) return null
              const pts: [number, number][] = d.map((v, i) => [xv(i), yv(v)])
              return (
                <path key={`line-${s.id}`}
                  d={smoothPath(pts)}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={s.bold ? '2' : '1'}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  filter={s.bold ? 'url(#glow)' : undefined}
                  opacity={s.bold ? 1 : 0.7}
                />
              )
            })}

            {series.filter(s => s.bold && s.data.length >= 1).map(s => (
              <circle key={`dot-${s.id}`}
                cx={xv(s.data.length - 1)} cy={yv(s.data[s.data.length - 1])}
                r="2.5" fill={s.color} filter="url(#glow)"
              />
            ))}
          </g>
        </svg>
      </div>

      {/* Time labels below — pure HTML, never stretched */}
      {nPts >= 4 && (
        <div style={{ display: 'flex', justifyContent: 'space-between', marginLeft: LABEL_W, marginTop: 3 }}>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>← 5 min</span>
          <span style={{ fontSize: 10, color: 'var(--text3)' }}>agora</span>
        </div>
      )}
    </div>
  )
}

// ── Legend ────────────────────────────────────────────────────────────────────

function Legend({ series }: { series: Series[] }) {
  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 14px', marginBottom: 8, paddingBottom: 8, borderBottom: '1px solid var(--border)' }}>
      {series.map(s => (
        <span key={s.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 10.5, color: 'var(--text2)' }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%',
            background: s.color,
            boxShadow: `0 0 5px ${s.color}88`,
            flexShrink: 0,
          }} />
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
      fontSize: 10, fontWeight: 700, padding: '2px 9px', borderRadius: 20,
      background: color + '18', color,
      border: `1px solid ${color}40`,
      letterSpacing: '0.01em',
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
    <div className="card" style={{ padding: '16px 18px', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        <span style={{ color: 'var(--text3)', display: 'flex' }}>{icon}</span>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)', letterSpacing: '0.01em' }}>{title}</span>
        <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginLeft: 2 }}>
          {badges}
        </div>
      </div>
      {children}
    </div>
  )
}

// ── Disk bar ──────────────────────────────────────────────────────────────────

function DiskBar({ pct, color }: { pct: number; color: string }) {
  return (
    <div style={{
      height: 10, borderRadius: 6,
      background: 'var(--bg)',
      border: '1px solid var(--border)',
      overflow: 'hidden',
    }}>
      <div style={{
        height: '100%',
        width: `${Math.min(pct, 100)}%`,
        background: `linear-gradient(90deg, ${color}cc, ${color})`,
        borderRadius: 6,
        transition: 'width .5s ease',
        boxShadow: `0 0 8px ${color}60`,
      }} />
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
  useEffect(() => { const t = setInterval(load, 15000);     return () => clearInterval(t) }, [load])
  useEffect(() => { const t = setInterval(loadStats, 5000); return () => clearInterval(t) }, [loadStats])

  const total      = streams.length
  const running    = streams.filter(s => s.status === 'running').length
  const stopped    = streams.filter(s => s.status === 'stopped').length
  const errors     = streams.filter(s => s.status === 'error').length
  const gpuStreams  = streams.filter(s =>
    s.status === 'running' && (s.video_codec.includes('nvenc') || s.video_codec.includes('qsv'))
  )

  function fmtNet(mbps: number) {
    const kbps = mbps * 1024
    if (kbps >= 1024) return `${mbps.toFixed(1)} Mbps`
    if (kbps >= 1)    return `${kbps.toFixed(0)} Kbps`
    return `${(kbps * 1024).toFixed(0)} bps`
  }

  // ── Series ──────────────────────────────────────────────────────────────────

  const coreCount = sysStats?.cpu_per_core?.length ?? 0

  const cpuSeries: Series[] = [
    ...CORE_COLORS.slice(0, coreCount).map((color, i) => ({
      id: `cpu-core-${i}`,
      label: `CPU${i} ${sysStats?.cpu_per_core?.[i] ?? 0}%`,
      data: history.map(h => h.cpu_per_core?.[i] ?? 0),
      color,
    })),
    {
      id: 'cpu-total',
      label: `Total ${sysStats?.cpu_pct ?? 0}%`,
      data: history.map(h => h.cpu_pct),
      color: '#e2e8f0',
      bold: true, fill: true,
    },
  ]

  const memSeries: Series[] = [
    {
      id: 'mem-ram',
      label: `Mem ${sysStats?.mem_pct ?? 0}%  —  ${sysStats?.mem_used_gb ?? 0} / ${sysStats?.mem_total_gb ?? 0} GiB`,
      data: history.map(h => h.mem_pct),
      color: '#34d399', bold: true, fill: true,
    },
    ...((sysStats?.mem_swap_total_gb ?? 0) > 0 ? [{
      id: 'mem-swap',
      label: `Swap ${sysStats?.mem_swap_pct ?? 0}%  —  ${sysStats?.mem_swap_used_gb ?? 0} / ${sysStats?.mem_swap_total_gb ?? 0} GiB`,
      data: history.map(h => h.mem_swap_pct ?? 0),
      color: '#fbbf24', fill: true,
    }] : []),
  ]

  const netPeak = Math.max(...history.map(h => Math.max(h.net_up_mbps, h.net_down_mbps)), 0.001)
  const netSeries: Series[] = [
    {
      id: 'net-up',
      label: `↑ ${fmtNet(sysStats?.net_up_mbps ?? 0)}  ·  ${sysStats?.net_up_total_gb ?? 0} GiB enviados`,
      data: history.map(h => (h.net_up_mbps / netPeak) * 100),
      color: '#60a5fa', bold: true, fill: true,
    },
    {
      id: 'net-down',
      label: `↓ ${fmtNet(sysStats?.net_down_mbps ?? 0)}  ·  ${sysStats?.net_down_total_gb ?? 0} GiB recebidos`,
      data: history.map(h => (h.net_down_mbps / netPeak) * 100),
      color: '#34d399', fill: true,
    },
  ]
  const netFmt = (pct: number) => fmtNet((pct / 100) * netPeak)

  const gpu = sysStats?.gpu ?? null
  const gpuMemPct = gpu ? Math.round(gpu.memory_used_mb / gpu.memory_total_mb * 100) : 0
  const gpuSeries: Series[] = gpu ? [
    {
      id: 'gpu-util',
      label: `GPU ${gpu.utilization_pct}%`,
      data: history.map(h => h.gpu?.utilization_pct ?? 0),
      color: '#c084fc', bold: true, fill: true,
    },
    {
      id: 'gpu-mem',
      label: `Mem ${gpuMemPct}%  —  ${(gpu.memory_used_mb / 1024).toFixed(2)} / ${(gpu.memory_total_mb / 1024).toFixed(0)} GiB`,
      data: history.map(h => h.gpu ? Math.round(h.gpu.memory_used_mb / h.gpu.memory_total_mb * 100) : 0),
      color: '#f87171', fill: true,
    },
    {
      id: 'gpu-enc',
      label: `Enc ${gpu.enc_pct ?? 0}%`,
      data: history.map(h => h.gpu?.enc_pct ?? 0),
      color: '#fbbf24',
    },
    {
      id: 'gpu-dec',
      label: `Dec ${gpu.dec_pct ?? 0}%`,
      data: history.map(h => h.gpu?.dec_pct ?? 0),
      color: '#a3e635',
    },
    {
      id: 'gpu-temp',
      label: `Temp ${gpu.temperature_c}°C`,
      data: history.map(h => h.gpu ? Math.round(h.gpu.temperature_c / 120 * 100) : 0),
      color: '#fb923c',
    },
  ] : []

  const diskColor = (sysStats?.disk_pct ?? 0) > 90 ? 'var(--danger)'
    : (sysStats?.disk_pct ?? 0) > 70 ? 'var(--warning)'
    : '#60a5fa'

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
            {/* ── Contadores ── */}
            <div className="stats-row">
              {[
                { icon: <FiVideo size={14} />,       value: total,   label: 'Total',    color: 'var(--accent)' },
                { icon: <FiPlay size={14} />,         value: running, label: 'Rodando',  color: 'var(--success)' },
                { icon: <FiSquare size={14} />,       value: stopped, label: 'Parado',   color: 'var(--text3)' },
                { icon: <FiAlertCircle size={14} />,  value: errors,  label: 'Erro',     color: errors > 0 ? 'var(--danger)' : 'var(--text3)' },
              ].map(({ icon, value, label, color }) => (
                <div key={label} className="stat-card">
                  <div className="stat-icon" style={{ color }}>{icon}</div>
                  <div className="stat-value" style={{ color }}>{value}</div>
                  <div className="stat-label">{label}</div>
                </div>
              ))}
            </div>

            {/* ── Monitoramento ── */}
            <div style={{ marginTop: 16 }}>
              {statsErr ? (
                <div className="card" style={{ padding: 16, color: 'var(--text3)', fontSize: 13 }}>
                  Não foi possível carregar dados do servidor.
                </div>
              ) : !sysStats ? (
                <div style={{ color: 'var(--text3)', fontSize: 13, marginTop: 8 }}>
                  Coletando dados…
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>

                  {/* ── CPU ── */}
                  <SectionCard
                    icon={<FiCpu size={14} />}
                    title={sysStats.cpu_name || 'CPU'}
                    badges={<>
                      <Badge color="#60a5fa">CPU {sysStats.cpu_pct}%</Badge>
                      {sysStats.cpu_temp_c != null && <Badge color="#fb923c">🌡 {sysStats.cpu_temp_c}°C</Badge>}
                      {sysStats.cpu_freq_mhz > 0 && <Badge color="#94a3b8">{sysStats.cpu_freq_mhz.toLocaleString()} MHz</Badge>}
                    </>}
                  >
                    <Legend series={cpuSeries} />
                    <Chart series={cpuSeries} height={140} />
                  </SectionCard>

                  {/* ── Memória + Rede ── */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 12 }}>

                    <SectionCard
                      icon={<FiMonitor size={14} />}
                      title="Memory Usage"
                      badges={<>
                        <Badge color="#34d399">Mem {sysStats.mem_pct}%</Badge>
                        {(sysStats.mem_swap_total_gb ?? 0) > 0 &&
                          <Badge color="#fbbf24">Swap {sysStats.mem_swap_pct}%</Badge>}
                      </>}
                    >
                      <Legend series={memSeries} />
                      <Chart series={memSeries} height={130} />
                    </SectionCard>

                    <SectionCard
                      icon={<FiWifi size={14} />}
                      title="Network Usage"
                      badges={<>
                        <Badge color="#60a5fa">↑ {fmtNet(sysStats.net_up_mbps)}</Badge>
                        <Badge color="#34d399">↓ {fmtNet(sysStats.net_down_mbps)}</Badge>
                      </>}
                    >
                      <Legend series={netSeries} />
                      <Chart series={netSeries} height={130} yFmt={netFmt} />
                    </SectionCard>
                  </div>

                  {/* ── Disco ── */}
                  <SectionCard
                    icon={<FiHardDrive size={14} />}
                    title="Disco"
                    badges={<>
                      <Badge color={diskColor}>{sysStats.disk_pct}%</Badge>
                      <Badge color="#94a3b8">{sysStats.disk_used_gb} / {sysStats.disk_total_gb} GB</Badge>
                    </>}
                  >
                    <DiskBar pct={sysStats.disk_pct} color={diskColor} />
                    <div style={{ marginTop: 7, fontSize: 11, color: 'var(--text3)' }}>
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
                        {gpuStreams.length > 0 && <Badge color="#34d399">Running: {gpuStreams.length}</Badge>}
                        {(gpu.enc_pct ?? 0) > 0 && <Badge color="#fbbf24">Enc {gpu.enc_pct}%</Badge>}
                        {(gpu.dec_pct ?? 0) > 0 && <Badge color="#a3e635">Dec {gpu.dec_pct}%</Badge>}
                        <Badge color="#fb923c">🌡 {gpu.temperature_c}°C</Badge>
                      </>}
                    >
                      <Legend series={gpuSeries} />
                      <Chart series={gpuSeries} height={140} />
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
