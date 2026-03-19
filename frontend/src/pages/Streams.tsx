import { useEffect, useRef, useState, useCallback } from 'react'
import Hls from 'hls.js'
import {
  FiPlay, FiSquare, FiEdit2, FiTrash2, FiPlus, FiX, FiRefreshCw,
  FiExternalLink, FiVideo, FiAlertCircle, FiTerminal, FiCircle,
  FiDownload, FiImage,
} from 'react-icons/fi'
import api, { getHlsUrl } from '../api'

// ─── types ────────────────────────────────────────────────────────────────────

interface Stream {
  id: string; name: string; url: string
  drm_type: string; drm_keys?: string; drm_kid?: string; drm_key?: string
  stream_type: string
  video_codec: string; video_preset: string; video_crf: number
  video_maxrate: string; video_resolution: string
  audio_codec: string; audio_bitrate: string
  hls_time: number; hls_list_size: number; buffer_seconds: number
  output_rtmp?: string; output_udp?: string
  proxy?: string; user_agent?: string; backup_urls?: string
  output_qualities?: string; audio_track?: number
  category?: string
  enabled: boolean; status: string
  created_at: string; updated_at: string
}

interface Category {
  id: number; name: string; logo_path: string | null
}

interface StreamStats {
  running: boolean; uptime_s: number
  fps: string; bitrate_kbps: number; frame: string; speed: string
}

const BLANK: Omit<Stream, 'status'|'created_at'|'updated_at'> = {
  id:'', name:'', url:'', drm_type:'none', drm_keys:'', drm_kid:'', drm_key:'',
  stream_type:'live', video_codec:'libx264', video_preset:'ultrafast',
  video_crf:26, video_maxrate:'', video_resolution:'original',
  audio_codec:'aac', audio_bitrate:'128k',
  hls_time:4, hls_list_size:8, buffer_seconds:20,
  output_rtmp:'', output_udp:'',
  proxy:'', user_agent:'', backup_urls:'',
  output_qualities:'', audio_track:0,
  category:'',
  enabled:true,
}

// ─── Player component ─────────────────────────────────────────────────────────

function StreamPlayer({ streamId, bufferSeconds, onClose }: {
  streamId: string; bufferSeconds: number; onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef   = useRef<Hls | null>(null)
  const [status, setStatus] = useState('Iniciando stream… (pode levar até 20s)')

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const url       = getHlsUrl(streamId)
    const seg       = 4
    const syncCount = Math.max(2, Math.round(bufferSeconds / seg))

    if (Hls.isSupported()) {
      const hls = new Hls({
        liveSyncDurationCount:       syncCount,
        liveMaxLatencyDurationCount: syncCount * 3,
        maxBufferLength:             Math.max(60, bufferSeconds * 2),
        maxMaxBufferLength:          Math.max(120, bufferSeconds * 4),
        backBufferLength:            0,
        lowLatencyMode:              false,
        startFragPrefetch:           true,
        enableWorker:                true,
        abrEwmaFastLive:             3.0,
        abrEwmaSlowLive:             9.0,
        manifestLoadingTimeOut:      60000,
        manifestLoadingMaxRetry:     5,
        manifestLoadingRetryDelay:   3000,
        levelLoadingTimeOut:         30000,
        levelLoadingMaxRetry:        4,
        fragLoadingTimeOut:          30000,
      })
      hlsRef.current = hls
      hls.on(Hls.Events.MANIFEST_PARSED, () => { setStatus(''); video.play().catch(() => {}) })
      hls.on(Hls.Events.ERROR, (_e, d) => {
        if (d.fatal) setStatus(`Erro: ${d.details}`)
        else if (d.type !== Hls.ErrorTypes.MEDIA_ERROR) return
      })
      hls.loadSource(url)
      hls.attachMedia(video)
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = url
      video.play().catch(() => {})
    }
    return () => { hlsRef.current?.destroy(); hlsRef.current = null }
  }, [streamId, bufferSeconds])

  return (
    <div style={{ position:'fixed', inset:0, background:'rgba(0,0,0,.85)', zIndex:200, display:'flex', alignItems:'center', justifyContent:'center' }}>
      <div style={{ width:'min(900px,95vw)', display:'flex', flexDirection:'column', gap:12 }}>
        <div style={{ display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <span style={{ color:'var(--text2)', fontSize:13 }}>{streamId}</span>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /> Fechar</button>
        </div>
        <div className="player-wrap">
          <video ref={videoRef} controls style={{ width:'100%', maxHeight:'70vh' }} />
          {status && <div className="player-overlay">{status}</div>}
        </div>
        <div style={{ fontSize:11, color:'var(--text3)', textAlign:'center' }}>
          Buffer: {bufferSeconds}s · Modo: ao vivo
        </div>
      </div>
    </div>
  )
}

// ─── Live log modal ───────────────────────────────────────────────────────────

function LogModal({ streamId, onClose }: { streamId: string; onClose: () => void }) {
  const [lines, setLines]    = useState<string[]>([])
  const bottomRef            = useRef<HTMLDivElement>(null)
  const esRef                = useRef<EventSource | null>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    const token = localStorage.getItem('token')
    const url   = `/api/streams/${streamId}/log/live`
    // Use fetch-based SSE with auth header (EventSource doesn't support headers)
    let closed = false
    const ctrl = new AbortController()

    async function connect() {
      try {
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        })
        if (!res.body) return
        const reader = res.body.getReader()
        const dec    = new TextDecoder()
        let buf      = ''
        while (!closed) {
          const { value, done } = await reader.read()
          if (done) break
          buf += dec.decode(value, { stream: true })
          const parts = buf.split('\n')
          buf = parts.pop() ?? ''
          for (const part of parts) {
            if (part.startsWith('data: ')) {
              const line = part.slice(6)
              setLines(prev => [...prev.slice(-499), line])
            }
          }
        }
      } catch {
        // closed
      }
    }

    connect()
    return () => { closed = true; ctrl.abort(); esRef.current?.close() }
  }, [streamId])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lines])

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth:860, width:'95vw' }}>
        <div className="modal-header">
          <h2 style={{ fontSize:15, fontWeight:600 }}>Log ao vivo — {streamId}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /></button>
        </div>
        <div style={{
          fontFamily:'monospace', fontSize:11, background:'#0d1117', color:'#c9d1d9',
          padding:12, height:420, overflowY:'auto', borderRadius:6, margin:'0 16px 16px',
        }}>
          {lines.length === 0
            ? <span style={{ color:'#666' }}>Aguardando log…</span>
            : lines.map((l, i) => {
                const color = l.includes('Error') || l.includes('error') ? '#f85149'
                            : l.includes('--- live ---') ? '#58a6ff'
                            : l.startsWith('frame=') ? '#3fb950'
                            : '#c9d1d9'
                return <div key={i} style={{ color, lineHeight:1.5 }}>{l}</div>
              })
          }
          <div ref={bottomRef} />
        </div>
      </div>
    </div>
  )
}

// ─── Tip: button tooltip ──────────────────────────────────────────────────────

function Tip({ text, children }: { text: string; children: React.ReactNode }) {
  return (
    <span className="btn-tip">
      {children}
      <span className="tip-box">{text}</span>
    </span>
  )
}

// ─── Form helpers ─────────────────────────────────────────────────────────────

function Row({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) {
  return (
    <div className="form-group">
      <label>
        {label}
        {hint && (
          <span className="tooltip-wrap">
            <span className="tooltip-icon">?</span>
            <span className="tooltip-box">{hint}</span>
          </span>
        )}
      </label>
      {children}
    </div>
  )
}

function Sel({ k, opts, form, set }: { k: string; opts: [string, string][]; form: any; set: (k: string, v: any) => void }) {
  return (
    <select value={form[k]} onChange={e => set(k, e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
}

function Num({ k, min, max, step=1, form, set }: { k: string; min: number; max: number; step?: number; form: any; set: (k: string, v: any) => void }) {
  return (
    <div style={{ display:'flex', gap:8, alignItems:'center' }}>
      <input type="range" min={min} max={max} step={step} value={form[k]}
             onChange={e => set(k, Number(e.target.value))}
             style={{ flex:1, padding:0, border:'none', background:'transparent', accentColor:'var(--accent)' }} />
      <span style={{ minWidth:36, color:'var(--text2)', fontSize:13 }}>{form[k]}</span>
    </div>
  )
}

// ─── Stream form modal ────────────────────────────────────────────────────────

function StreamModal({ stream, onSave, onClose }: {
  stream: Partial<Stream> | null; onSave: () => void; onClose: () => void
}) {
  const isNew = !stream?.id
  const [tab, setTab]       = useState<'source'|'video'|'audio'|'hls'>('source')
  const [form, setForm]     = useState<any>(stream ? { ...BLANK, ...stream } : { ...BLANK })
  const [saving, setSaving] = useState(false)
  const [error, setError]   = useState('')

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  function set(k: string, v: any) { setForm((f: any) => ({ ...f, [k]: v })) }

  async function save() {
    setSaving(true); setError('')
    try {
      const payload = { ...form }
      if (isNew && (!payload.id || payload.id.length < 2)) {
        payload.id = payload.name
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, '_')
          .replace(/^_+|_+$/g, '')
          .slice(0, 50) || 'stream_' + Date.now()
      }
      if (isNew) await api.post('/api/streams', payload)
      else       await api.put(`/api/streams/${stream!.id}`, payload)
      onSave()
    } catch(e: any) {
      const detail = e.response?.data?.detail
      if (Array.isArray(detail)) {
        setError(detail.map((d: any) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(' | '))
      } else {
        setError(detail || 'Erro ao salvar')
      }
    } finally { setSaving(false) }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal">
        <div className="modal-header">
          <h2 style={{ fontSize:16, fontWeight:600 }}>{isNew ? 'Novo Stream' : `Editar: ${stream!.name}`}</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /></button>
        </div>

        <div style={{ padding:'0 24px' }}>
          <div className="tabs">
            {(['source','video','audio','hls'] as const).map(t => (
              <button key={t} className={`tab${tab===t?' active':''}`} onClick={() => setTab(t)}>
                {{ source:'Fonte', video:'Vídeo', audio:'Áudio', hls:'HLS / Player' }[t]}
              </button>
            ))}
          </div>
        </div>

        <div className="modal-body">
          {tab === 'source' && <>
            <Row label="ID do Stream" hint="Apenas letras, números, _ e - (não pode alterar depois de criado)">
              <input value={form.id} onChange={e => set('id', e.target.value)}
                     disabled={!isNew} placeholder="globo_hd" />
            </Row>
            <Row label="Nome"><input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Globo HD" /></Row>
            <Row label="Categoria" hint="Agrupa os streams por categoria (ex: Esportes, Notícias, Filmes)">
              <input value={form.category ?? ''} onChange={e => set('category', e.target.value)} placeholder="Ex: Esportes" />
            </Row>
            <Row label="URL" hint="HLS (.m3u8), MPEG-TS, YouTube, CENC/CMAF">
              <textarea value={form.url} onChange={e => set('url', e.target.value)} rows={3} placeholder="https://..." />
            </Row>
            <Row label="Tipo de stream">
              <Sel form={form} set={set} k="stream_type" opts={[['live','Ao vivo'],['vod','VOD / Arquivo']]} />
            </Row>
            <Row label="DRM">
              <Sel form={form} set={set} k="drm_type" opts={[['none','Sem DRM'],['cenc-ctr','CENC-CTR (Disney+, etc.)']]} />
            </Row>
            {form.drm_type === 'cenc-ctr' && <>
              <Row label="Keys / CDM Script" hint="Um par KID:KEY por linha — formato de saída de CDM tools">
                <textarea
                  rows={5}
                  value={form.drm_keys||''}
                  onChange={e => set('drm_keys', e.target.value)}
                  placeholder={'c2e511d926db4f209e8cd856656e6bb1:4d67d0f698ad334072056dfbf61d4a99\n...'}
                  style={{ fontFamily:'monospace', fontSize:12, resize:'vertical' }}
                />
              </Row>
            </>}
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <input type="checkbox" id="enabled" checked={form.enabled} onChange={e => set('enabled', e.target.checked)} style={{ width:'auto' }} />
              <label htmlFor="enabled" style={{ fontSize:13, color:'var(--text2)', cursor:'pointer' }}>Stream ativo</label>
            </div>

            <div style={{ marginTop:8, borderTop:'1px solid var(--border)', paddingTop:16 }}>
              <div style={{ fontSize:11, fontWeight:600, color:'var(--text3)', marginBottom:12, textTransform:'uppercase', letterSpacing:'0.05em' }}>
                Rede / Proxy
              </div>
              <Row label="Proxy" hint="http://, https://, socks4://, socks5:// — ex: http://user:pass@host:3128">
                <input value={form.proxy||''} onChange={e => set('proxy', e.target.value)} placeholder="http://proxy:3128" />
              </Row>
              <Row label="User-Agent" hint="Deixe vazio para usar o padrão">
                <input value={form.user_agent||''} onChange={e => set('user_agent', e.target.value)} placeholder="Mozilla/5.0 ..." />
              </Row>
              <Row label="URLs de Backup / Balance" hint="Uma URL por linha — rodízio automático em caso de falha">
                <textarea
                  rows={4}
                  value={form.backup_urls||''}
                  onChange={e => set('backup_urls', e.target.value)}
                  placeholder={'https://cdn2.example.com/live.m3u8\nhttps://cdn3.example.com/live.m3u8'}
                  style={{ fontFamily:'monospace', fontSize:12, resize:'vertical' }}
                />
              </Row>
            </div>
          </>}

          {tab === 'video' && <>
            <Row label="Codec de vídeo">
              <Sel form={form} set={set} k="video_codec" opts={[
                ['copy','Copy (sem transcode — mais rápido)'],
                ['libx264','libx264 (CPU — qualidade alta)'],
                ['h264_nvenc','h264_nvenc (GPU NVIDIA)'],
              ]} />
            </Row>

            {form.video_codec === 'copy' && (
              <Row label="Resolução preferida"
                   hint="Para streams HLS multi-qualidade: escolhe o variant mais próximo da resolução selecionada">
                <Sel form={form} set={set} k="video_resolution" opts={[
                  ['original','Original (melhor disponível)'],
                  ['1920x1080','1080p — 1920×1080'],
                  ['1280x720', '720p — 1280×720'],
                  ['854x480',  '480p — 854×480'],
                ]} />
              </Row>
            )}

            {form.video_codec !== 'copy' && (
              <Row label="Qualidades de saída / ABR"
                   hint="Selecione 1 qualidade para saída fixa ou múltiplas para HLS adaptativo (ABR)">
                <div style={{ display:'flex', gap:20, flexWrap:'wrap', padding:'6px 0' }}>
                  {([
                    { q:'1080p', vbr:'4500k', res:'1920×1080' },
                    { q:'720p',  vbr:'2800k', res:'1280×720'  },
                    { q:'480p',  vbr:'1400k', res:'854×480'   },
                    { q:'360p',  vbr:'800k',  res:'640×360'   },
                  ] as const).map(({ q, vbr, res }) => {
                    const sel     = (form.output_qualities||'').split(',').filter(Boolean)
                    const checked = sel.includes(q)
                    const ORDER   = ['1080p','720p','480p','360p']
                    return (
                      <label key={q} style={{ display:'flex', alignItems:'center', gap:6, cursor:'pointer', userSelect:'none' }}>
                        <input type="checkbox" checked={checked} style={{ width:'auto', accentColor:'var(--accent)' }}
                          onChange={e => {
                            let qs = sel.filter((x: string) => x !== q)
                            if (e.target.checked) qs = [...qs, q]
                            qs = ORDER.filter((x: string) => qs.includes(x))
                            set('output_qualities', qs.join(','))
                          }} />
                        <span style={{ fontWeight:600, fontSize:13 }}>{q}</span>
                        <span style={{ color:'var(--text3)', fontSize:11 }}>{res} · {vbr}</span>
                      </label>
                    )
                  })}
                </div>
                {!form.output_qualities && (
                  <span style={{ fontSize:11, color:'var(--text3)' }}>
                    Nenhuma selecionada → usa configuração de resolução abaixo
                  </span>
                )}
              </Row>
            )}

            {form.video_codec !== 'copy' && <>
              <Row label="Preset (velocidade × qualidade)" hint="Mais rápido = menos CPU, menor qualidade">
                <Sel form={form} set={set} k="video_preset" opts={[
                  ['ultrafast','ultrafast'],['superfast','superfast'],['veryfast','veryfast'],
                  ['faster','faster'],['fast','fast'],['medium','medium'],
                ]} />
              </Row>
              {!form.output_qualities && <>
                <Row label={`CRF: ${form.video_crf} — qualidade (menor = melhor)`}>
                  <Num form={form} set={set} k="video_crf" min={0} max={51} />
                </Row>
                <Row label="Resolução">
                  <Sel form={form} set={set} k="video_resolution" opts={[
                    ['original','Original'],['1920x1080','1080p'],['1280x720','720p'],['854x480','480p'],
                  ]} />
                </Row>
                <Row label="Bitrate máximo (opcional)" hint='Ex: "4000k" ou deixe vazio para sem limite'>
                  <input value={form.video_maxrate||''} onChange={e => set('video_maxrate', e.target.value)} placeholder="4000k" />
                </Row>
              </>}
            </>}
          </>}

          {tab === 'audio' && <>
            <Row label="Faixa de áudio" hint="Índice da faixa de entrada: 0 = primeira, 1 = segunda, etc.">
              <select value={form.audio_track ?? 0} onChange={e => set('audio_track', Number(e.target.value))}>
                <option value={0}>0 — Primeira faixa (padrão)</option>
                <option value={1}>1 — Segunda faixa</option>
                <option value={2}>2 — Terceira faixa</option>
                <option value={3}>3 — Quarta faixa</option>
                <option value={4}>4 — Quinta faixa</option>
              </select>
            </Row>
            <Row label="Codec de áudio">
              <Sel form={form} set={set} k="audio_codec" opts={[['copy','Copy'],['aac','AAC (transcode)']]} />
            </Row>
            {form.audio_codec !== 'copy' && (
              <Row label="Bitrate de áudio">
                <Sel form={form} set={set} k="audio_bitrate" opts={[['96k','96k'],['128k','128k'],['192k','192k'],['256k','256k']]} />
              </Row>
            )}
          </>}

          {tab === 'hls' && <>
            <Row label={`Duração do segmento HLS: ${form.hls_time}s`} hint="Menor = menor latência, maior = mais estável">
              <Num form={form} set={set} k="hls_time" min={1} max={10} />
            </Row>
            <Row label={`Segmentos na playlist: ${form.hls_list_size}`} hint="Quantos segmentos ficam no disco ao mesmo tempo. 8 = 32s (ideal para live). Mais = mais armazenamento usado.">
              <Num form={form} set={set} k="hls_list_size" min={3} max={30} />
            </Row>
            <Row label={`Buffer do player: ${form.buffer_seconds}s`} hint="Atraso em relação ao vivo — mais = mais suave">
              <Num form={form} set={set} k="buffer_seconds" min={5} max={120} step={5} />
            </Row>
            <div className="card" style={{ background:'var(--bg3)', padding:14, fontSize:12, color:'var(--text3)' }}>
              <strong style={{ color:'var(--text2)' }}>Janela disponível:</strong>{' '}
              {form.hls_list_size * form.hls_time}s &nbsp;|&nbsp;
              <strong style={{ color:'var(--text2)' }}>Buffer alvo:</strong>{' '}
              {form.buffer_seconds}s &nbsp;|&nbsp;
              <strong style={{ color:'var(--text2)' }}>Segmentos de buffer:</strong>{' '}
              {Math.max(2, Math.round(form.buffer_seconds / form.hls_time))}
            </div>

            <div style={{ marginTop:16, borderTop:'1px solid var(--border)', paddingTop:16 }}>
              <div style={{ fontSize:12, fontWeight:600, color:'var(--text2)', marginBottom:12, textTransform:'uppercase', letterSpacing:'0.05em' }}>
                Saídas Adicionais (opcional)
              </div>
              <Row label="Saída RTMP" hint='Ex: rtmp://live.twitch.tv/live/STREAM_KEY'>
                <input value={form.output_rtmp||''} onChange={e => set('output_rtmp', e.target.value)} placeholder="rtmp://..." />
              </Row>
              <Row label="Saída UDP / Multicast" hint='Ex: udp://239.0.0.1:1234 ou udp://127.0.0.1:5000'>
                <input value={form.output_udp||''} onChange={e => set('output_udp', e.target.value)} placeholder="udp://..." />
              </Row>
            </div>
          </>}

          {error && <div style={{ color:'var(--danger)', fontSize:13 }}>{error}</div>}
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            {saving ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Recordings modal ─────────────────────────────────────────────────────────

function RecordingsModal({ onClose }: { onClose: () => void }) {
  const [recs, setRecs]         = useState<any[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [downloading, setDl]    = useState<string | null>(null)

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  useEffect(() => {
    api.get('/api/recordings')
      .then(r => setRecs(r.data))
      .catch(() => setError('Erro ao carregar gravações. Verifique se você tem permissão.'))
      .finally(() => setLoading(false))
  }, [])

  function fmt(bytes: number) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  async function download(filename: string) {
    setDl(filename)
    try {
      const res = await fetch(`/api/recordings/${filename}`, {
        headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
      })
      if (!res.ok) { alert('Erro ao baixar: ' + res.status); return }
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href = url; a.download = filename; a.click()
      URL.revokeObjectURL(url)
    } finally { setDl(null) }
  }

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth:700 }}>
        <div className="modal-header">
          <h2 style={{ fontSize:15, fontWeight:600 }}>Gravações</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /></button>
        </div>
        <div className="modal-body" style={{ minHeight:200 }}>
          {loading ? (
            <div style={{ color:'var(--text3)', textAlign:'center', padding:32 }}>Carregando…</div>
          ) : error ? (
            <div style={{ color:'var(--danger)', textAlign:'center', padding:32, fontSize:13 }}>{error}</div>
          ) : recs.length === 0 ? (
            <div style={{ color:'var(--text3)', textAlign:'center', padding:32 }}>
              <div style={{ fontSize:28, marginBottom:8 }}>📼</div>
              Nenhuma gravação encontrada.<br />
              <span style={{ fontSize:12 }}>Inicie uma gravação clicando no botão <FiCircle size={11} style={{ verticalAlign:'middle' }} /> em um stream ao vivo.</span>
            </div>
          ) : (
            <table style={{ width:'100%', borderCollapse:'collapse', fontSize:13 }}>
              <thead>
                <tr>
                  <th style={{ textAlign:'left', padding:'6px 8px', color:'var(--text3)' }}>Arquivo</th>
                  <th style={{ textAlign:'right', padding:'6px 8px', color:'var(--text3)' }}>Tamanho</th>
                  <th style={{ textAlign:'right', padding:'6px 8px', color:'var(--text3)' }}>Data</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {recs.map(r => (
                  <tr key={r.filename} style={{ borderTop:'1px solid var(--border)' }}>
                    <td style={{ padding:'8px 8px', fontFamily:'monospace', fontSize:11, color:'var(--text2)' }}>{r.filename}</td>
                    <td style={{ padding:'8px 8px', textAlign:'right', color:'var(--text3)' }}>{fmt(r.size_bytes)}</td>
                    <td style={{ padding:'8px 8px', textAlign:'right', color:'var(--text3)', fontSize:11 }}>
                      {new Date(r.created_at).toLocaleString('pt-BR')}
                    </td>
                    <td style={{ padding:'8px 8px', textAlign:'right' }}>
                      <button
                        className="btn btn-ghost btn-sm"
                        title="Baixar"
                        disabled={downloading === r.filename}
                        onClick={() => download(r.filename)}
                      >
                        {downloading === r.filename ? '…' : <FiDownload size={12} />}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Streams() {
  const [streams, setStreams]         = useState<Stream[]>([])
  const [loading, setLoading]         = useState(true)
  const [refreshing, setRefreshing]   = useState(false)
  const [editing, setEditing]         = useState<Stream | null | 'new'>(null)
  const [playing, setPlaying]         = useState<Stream | null>(null)
  const [logStream, setLogStream]     = useState<string | null>(null)
  const [showRecs, setShowRecs]       = useState(false)
  const [recording, setRecording]     = useState<Record<string, boolean>>({})
  const [stats, setStats]             = useState<Record<string, StreamStats>>({})
  const [thumbnails, setThumbnails]   = useState<Record<string, string>>({})
  const [search, setSearch]               = useState('')
  const [activeCategory, setActiveCategory] = useState<string | null>(null)
  const [m3uError, setM3uError]           = useState('')
  const [catMeta, setCatMeta]             = useState<Category[]>([])

  const user    = JSON.parse(localStorage.getItem('user') || '{}')
  const canEdit = user.role === 'admin' || user.role === 'operator'

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true)
    try {
      const r = await api.get('/api/streams')
      setStreams(r.data)
    } finally {
      setLoading(false)
      if (manual) setRefreshing(false)
    }
  }, [])

  useEffect(() => { load() }, [load])
  useEffect(() => { const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])

  // Load category metadata (logos) once
  useEffect(() => {
    api.get('/api/categories').then(r => setCatMeta(r.data)).catch(() => {})
  }, [])

  // When streams list changes, load thumbnails + recording status for running streams immediately
  useEffect(() => {
    if (streams.length === 0) return
    const token = localStorage.getItem('token') ?? ''

    // Load thumbnails immediately for running streams (not already cached)
    const running = streams.filter(s => s.status === 'running')
    for (const s of running) {
      if (thumbnails[s.id]) continue   // already cached
      fetch(`/api/streams/${s.id}/thumbnail?t=${Date.now()}`, {
        headers: { Authorization: `Bearer ${token}` },
      }).then(async r => {
        if (r.ok) {
          const blob = await r.blob()
          setThumbnails(prev => ({ ...prev, [s.id]: URL.createObjectURL(blob) }))
        }
      }).catch(() => {})
    }

    // Restore recording status
    for (const s of running) {
      api.get(`/api/streams/${s.id}/record/status`).then(r => {
        if (r.data?.recording) setRecording(prev => ({ ...prev, [s.id]: true }))
      }).catch(() => {})
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streams])

  // Poll stats for running streams every 5s
  useEffect(() => {
    const t = setInterval(async () => {
      const running = streams.filter(s => s.status === 'running')
      if (running.length === 0) return
      const results = await Promise.allSettled(
        running.map(s => api.get(`/api/streams/${s.id}/stats`))
      )
      const next: Record<string, StreamStats> = {}
      running.forEach((s, i) => {
        const r = results[i]
        if (r.status === 'fulfilled') next[s.id] = r.value.data
      })
      setStats(prev => ({ ...prev, ...next }))
    }, 5000)
    return () => clearInterval(t)
  }, [streams])

  // Refresh thumbnails for running streams every 15s
  useEffect(() => {
    const t = setInterval(async () => {
      const token   = localStorage.getItem('token') ?? ''
      const running = streams.filter(s => s.status === 'running')
      for (const s of running) {
        try {
          const r = await fetch(`/api/streams/${s.id}/thumbnail?t=${Date.now()}`, {
            headers: { Authorization: `Bearer ${token}` },
          })
          if (r.ok) {
            const blob = await r.blob()
            setThumbnails(prev => ({ ...prev, [s.id]: URL.createObjectURL(blob) }))
          }
        } catch { /* ignore */ }
      }
    }, 15000)
    return () => clearInterval(t)
  }, [streams])

  async function stopStream(id: string) {
    await api.post(`/api/streams/${id}/stop`)
    load()
  }

  async function deleteStream(id: string) {
    if (!window.confirm(`Deletar stream "${id}"?`)) return
    await api.delete(`/api/streams/${id}`)
    load()
  }

  async function toggleRecord(id: string) {
    if (recording[id]) {
      await api.delete(`/api/streams/${id}/record`)
      setRecording(prev => ({ ...prev, [id]: false }))
    } else {
      await api.post(`/api/streams/${id}/record`)
      setRecording(prev => ({ ...prev, [id]: true }))
    }
  }

  // Derived: categories list + filtered streams
  const categories = Array.from(new Set(streams.map(s => s.category || '').filter(Boolean))).sort()
  const filteredStreams = streams.filter(s => {
    const matchSearch   = !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.id.toLowerCase().includes(search.toLowerCase())
    const matchCategory = !activeCategory || (s.category || '') === activeCategory
    return matchSearch && matchCategory
  })

  function StatusBadge({ status }: { status: string }) {
    const cls = status === 'running' ? 'badge-running' : status === 'error' ? 'badge-error' : 'badge-stopped'
    const dot = status === 'running' ? '●' : status === 'error' ? '●' : '○'
    return <span className={`badge ${cls}`}>{dot} {status}</span>
  }

  function StatsLine({ id }: { id: string }) {
    const s = stats[id]
    if (!s || !s.running) return null
    const kbps = s.bitrate_kbps
    const mbps = kbps > 0 ? (kbps > 1000 ? `${(kbps/1000).toFixed(1)} Mbps` : `${kbps} kbps`) : null
    const fps  = s.fps && s.fps !== '0' ? `${s.fps} fps` : null
    if (!mbps && !fps) return null
    return (
      <div style={{ fontSize:10, color:'var(--success)', marginTop:2 }}>
        ⚡ {[mbps, fps].filter(Boolean).join(' · ')}
      </div>
    )
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Streams</h1>
        <div className="page-header-actions">
          <Tip text="Ver e baixar gravações feitas de streams ao vivo">
            <button className="btn btn-ghost btn-sm" onClick={() => setShowRecs(true)}>
              <FiDownload size={13} /> Gravações
            </button>
          </Tip>
          <Tip text={m3uError || "Baixar lista M3U com todos os streams ativos. Use em players como VLC, Kodi, TiviMate."}>
            <button className="btn btn-ghost btn-sm"
              onClick={async () => {
                setM3uError('')
                try {
                  const res = await fetch('/api/streams/export.m3u', {
                    headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
                  })
                  if (!res.ok) { setM3uError(`Erro ${res.status} ao gerar M3U`); return }
                  const blob = await res.blob()
                  const url  = URL.createObjectURL(blob)
                  const a    = document.createElement('a')
                  a.href = url; a.download = 'aistra.m3u'; a.click()
                  URL.revokeObjectURL(url)
                } catch { setM3uError('Falha ao baixar M3U') }
              }}
              style={m3uError ? { color: 'var(--danger)' } : undefined}>
              <FiExternalLink size={13} /> M3U
            </button>
          </Tip>
          <Tip text="Recarregar a lista de streams e status de cada um">
            <button className="btn btn-ghost btn-sm" onClick={() => load(true)} disabled={refreshing}>
              <FiRefreshCw size={13} style={refreshing ? { animation:'spin 1s linear infinite' } : undefined} />
              {refreshing ? 'Atualizando…' : 'Atualizar'}
            </button>
          </Tip>
          {canEdit && (
            <Tip text="Adicionar um novo stream ao painel">
              <button className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>
                <FiPlus size={13} /> Novo Stream
              </button>
            </Tip>
          )}
        </div>
      </div>

      {/* Search + Categories */}
      <div style={{ marginBottom:12 }}>
        <div style={{ display:'flex', gap:8, alignItems:'center', flexWrap:'wrap', marginBottom: categories.length > 0 ? 8 : 0 }}>
          <input
            type="search"
            placeholder="Buscar stream por nome ou ID…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{ flex:1, minWidth:200, maxWidth:380 }}
          />
        </div>
        {/* Category tabs — always show row so user knows the feature exists */}
        <div style={{ display:'flex', gap:6, flexWrap:'wrap', alignItems:'center' }}>
          <button
            className={`btn btn-sm${!activeCategory ? ' btn-primary' : ' btn-ghost'}`}
            onClick={() => setActiveCategory(null)}
            style={{ fontSize:12 }}
          >
            Todas ({streams.length})
          </button>
          {categories.map(cat => {
            const meta = catMeta.find(c => c.name === cat)
            return (
              <button
                key={cat}
                className={`btn btn-sm${activeCategory === cat ? ' btn-primary' : ' btn-ghost'}`}
                onClick={() => setActiveCategory(activeCategory === cat ? null : cat)}
                style={{ fontSize:12, display:'flex', alignItems:'center', gap:5 }}
              >
                {meta?.logo_path && (
                  <img
                    src={`/api/categories/${meta.id}/logo?t=${meta.logo_path}`}
                    alt=""
                    style={{ width:16, height:16, objectFit:'contain', borderRadius:2 }}
                  />
                )}
                {cat} ({streams.filter(s => s.category === cat).length})
              </button>
            )
          })}
          {canEdit && categories.length === 0 && streams.length > 0 && (
            <span style={{ fontSize:11, color:'var(--text3)', fontStyle:'italic' }}>
              Edite um stream e defina uma Categoria para filtrar aqui
            </span>
          )}
        </div>
      </div>

      <div className="page-content">
        {!loading && streams.length > 0 && (() => {
          const total   = streams.length
          const running = streams.filter(s => s.status === 'running').length
          const stopped = streams.filter(s => s.status === 'stopped').length
          const errors  = streams.filter(s => s.status === 'error').length
          return (
            <div className="stats-row">
              <div className="stat-card">
                <div className="stat-icon" style={{ color:'var(--accent)' }}><FiVideo size={14} /></div>
                <div className="stat-value" style={{ color:'var(--accent)' }}>{total}</div>
                <div className="stat-label">Total</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon" style={{ color:'var(--success)' }}><FiPlay size={14} /></div>
                <div className="stat-value" style={{ color:'var(--success)' }}>{running}</div>
                <div className="stat-label">Rodando</div>
              </div>
              <div className="stat-card">
                <div className="stat-icon" style={{ color:'var(--text3)' }}><FiSquare size={14} /></div>
                <div className="stat-value" style={{ color:'var(--text3)' }}>{stopped}</div>
                <div className="stat-label">Parado</div>
              </div>
              {errors > 0 ? (
                <div className="stat-card">
                  <div className="stat-icon" style={{ color:'var(--danger)' }}><FiAlertCircle size={14} /></div>
                  <div className="stat-value" style={{ color:'var(--danger)' }}>{errors}</div>
                  <div className="stat-label">Erro</div>
                </div>
              ) : (
                <div className="stat-card" style={{ opacity:0.4 }}>
                  <div className="stat-icon" style={{ color:'var(--danger)' }}><FiAlertCircle size={14} /></div>
                  <div className="stat-value" style={{ color:'var(--danger)' }}>0</div>
                  <div className="stat-label">Erro</div>
                </div>
              )}
            </div>
          )
        })()}

        {loading ? (
          <div style={{ color:'var(--text3)', textAlign:'center', padding:40 }}>Carregando…</div>
        ) : streams.length === 0 ? (
          <div className="card" style={{ textAlign:'center', padding:48, color:'var(--text3)' }}>
            <div style={{ fontSize:32, marginBottom:12 }}>📡</div>
            <p>Nenhum stream cadastrado.</p>
            {canEdit && (
              <button className="btn btn-primary" style={{ marginTop:16 }} onClick={() => setEditing('new')}>
                <FiPlus /> Criar primeiro stream
              </button>
            )}
          </div>
        ) : (
          <div className="card" style={{ padding:0, overflow:'hidden' }}>
            <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th style={{ width:40 }}></th>
                  <th>Nome</th>
                  <th className="col-hide-xs">ID</th>
                  <th className="col-hide-xs">DRM</th>
                  <th className="col-hide-xs">Codec</th>
                  <th className="col-hide-xs">Buffer</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {filteredStreams.length === 0 ? (
                  <tr><td colSpan={8} style={{ textAlign:'center', padding:32, color:'var(--text3)' }}>
                    Nenhum stream encontrado
                  </td></tr>
                ) : filteredStreams.map(s => (
                  <tr key={s.id}>
                    {/* Thumbnail */}
                    <td style={{ padding:'4px 8px' }}>
                      {thumbnails[s.id] ? (
                        <img src={thumbnails[s.id]} alt="" style={{ width:40, height:24, objectFit:'cover', borderRadius:3, background:'#000' }} />
                      ) : (
                        <div style={{ width:40, height:24, borderRadius:3, background:'var(--bg3)', display:'flex', alignItems:'center', justifyContent:'center' }}>
                          <FiImage size={10} color="var(--text3)" />
                        </div>
                      )}
                    </td>
                    <td>
                      <div style={{ fontWeight:500, color:'var(--text)', display:'flex', alignItems:'center', gap:6 }}>
                        {s.name}
                        {s.category && (
                          <span style={{ fontSize:10, padding:'1px 6px', borderRadius:10, background:'var(--bg3)', color:'var(--text2)', fontWeight:400 }}>
                            {s.category}
                          </span>
                        )}
                      </div>
                      <div style={{ fontSize:11, color:'var(--text3)', marginTop:1, maxWidth:260, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                        {s.url.length > 55 ? s.url.slice(0,55)+'…' : s.url}
                      </div>
                      <StatsLine id={s.id} />
                    </td>
                    <td className="col-hide-xs"><code style={{ fontSize:12, color:'var(--text2)' }}>{s.id}</code></td>
                    <td className="col-hide-xs">
                      {s.drm_type === 'cenc-ctr'
                        ? <span className="badge" style={{ background:'#1e1b4b', color:'#818cf8' }}>CENC-CTR</span>
                        : <span style={{ color:'var(--text3)', fontSize:12 }}>—</span>
                      }
                    </td>
                    <td className="col-hide-xs">
                      <span style={{ fontSize:12, color:'var(--text2)' }}>
                        {s.video_codec === 'copy' ? 'copy' : `${s.video_codec} ${s.video_preset}`}
                      </span>
                    </td>
                    <td className="col-hide-xs"><span style={{ fontSize:12, color:'var(--text2)' }}>{s.buffer_seconds}s</span></td>
                    <td><StatusBadge status={s.status} /></td>
                    <td>
                      <div style={{ display:'flex', gap:5, flexWrap:'wrap' }}>
                        <Tip text="Assistir o stream no player integrado (inicia o processamento se necessário)">
                          <button className="btn btn-success btn-sm" onClick={() => setPlaying(s)}>
                            <FiPlay size={12} />
                          </button>
                        </Tip>
                        {s.status === 'running' && (
                          <Tip text="Parar o processamento deste stream (libera recursos do servidor)">
                            <button className="btn btn-ghost btn-sm" onClick={() => stopStream(s.id)}>
                              <FiSquare size={12} />
                            </button>
                          </Tip>
                        )}
                        <Tip text="Ver o log em tempo real do ffmpeg — útil para diagnosticar erros de stream">
                          <button className="btn btn-ghost btn-sm" onClick={() => setLogStream(s.id)}>
                            <FiTerminal size={12} />
                          </button>
                        </Tip>
                        {canEdit && s.status === 'running' && (
                          <Tip text={recording[s.id] ? 'Parar a gravação e salvar o arquivo MP4' : 'Gravar o stream em arquivo MP4 no servidor'}>
                            <button
                              className="btn btn-sm"
                              style={{ background: recording[s.id] ? 'rgba(239,68,68,.15)' : undefined, color: recording[s.id] ? 'var(--danger)' : undefined }}
                              onClick={() => toggleRecord(s.id)}
                            >
                              <FiCircle size={12} style={{ fill: recording[s.id] ? 'currentColor' : 'none' }} />
                            </button>
                          </Tip>
                        )}
                        <Tip text="Copiar / abrir a URL HLS direta (.m3u8) — use em VLC ou outros players">
                          <a href={getHlsUrl(s.id)} target="_blank" rel="noreferrer"
                             className="btn btn-ghost btn-sm">
                            <FiExternalLink size={12} />
                          </a>
                        </Tip>
                        {canEdit && <>
                          <Tip text="Editar configurações do stream (fonte, codec, DRM, buffer, etc.)">
                            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(s)}>
                              <FiEdit2 size={12} />
                            </button>
                          </Tip>
                          <Tip text="Deletar este stream permanentemente">
                            <button className="btn btn-danger btn-sm" onClick={() => deleteStream(s.id)}>
                              <FiTrash2 size={12} />
                            </button>
                          </Tip>
                        </>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            </div>
          </div>
        )}
      </div>

      {playing && (
        <StreamPlayer
          streamId={playing.id}
          bufferSeconds={playing.buffer_seconds}
          onClose={() => { setPlaying(null); load() }}
        />
      )}

      {logStream && <LogModal streamId={logStream} onClose={() => setLogStream(null)} />}

      {showRecs && <RecordingsModal onClose={() => setShowRecs(false)} />}

      {editing && (
        <StreamModal
          stream={editing === 'new' ? null : editing}
          onSave={() => { setEditing(null); load() }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
