import { useEffect, useRef, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import Hls from 'hls.js'
import {
  FiPlay, FiSquare, FiEdit2, FiTrash2, FiPlus, FiX, FiRefreshCw,
  FiExternalLink, FiVideo, FiAlertCircle, FiTerminal, FiCircle,
  FiDownload, FiImage, FiSlash,
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
  category?: string; channel_num?: number | null
  enabled: boolean; status: string
  created_at: string; updated_at: string
}

interface StreamStats {
  running: boolean; uptime_s: number
  fps: string; bitrate_kbps: number; frame: string; speed: string
  drop_frames: number; dup_frames: number; total_size_mb: number
  ban_detected: boolean; ban_http_code: number; ban_count: number; ban_at: number | null
}

const BLANK: Omit<Stream, 'status'|'created_at'|'updated_at'> = {
  id:'', name:'', url:'', drm_type:'none', drm_keys:'', drm_kid:'', drm_key:'',
  stream_type:'live', video_codec:'libx264', video_preset:'ultrafast',
  video_crf:26, video_maxrate:'', video_resolution:'original',
  audio_codec:'aac', audio_bitrate:'128k',
  hls_time:15, hls_list_size:15, buffer_seconds:20,
  output_rtmp:'', output_udp:'',
  proxy:'', user_agent:'', backup_urls:'',
  output_qualities:'', audio_track:0,
  category:'', channel_num: null,
  enabled:true,
}

// ─── Player component ─────────────────────────────────────────────────────────

function StreamPlayer({ streamId, bufferSeconds, hlsTime, hlsListSize, onClose }: {
  streamId: string; bufferSeconds: number
  hlsTime: number; hlsListSize: number; onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef   = useRef<Hls | null>(null)
  const [status, setStatus] = useState('Iniciando stream… (pode levar até 30s)')

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const url      = getHlsUrl(streamId)
    const seg      = hlsTime || 15
    const listSize = hlsListSize || 15
    // Sync to 2 segments behind live edge; max latency = half the playlist window
    const syncCount  = 2
    const maxLatency = Math.max(syncCount + 2, Math.round(listSize / 2))
    // Buffer enough for the full playlist window to prevent stall/loop
    const bufMs = seg * listSize * 1000

    if (Hls.isSupported()) {
      const hls = new Hls({
        liveSyncDurationCount:       syncCount,
        liveMaxLatencyDurationCount: maxLatency,
        maxBufferLength:             seg * listSize,   // full window ahead
        maxMaxBufferLength:          seg * listSize * 2,
        backBufferLength:            0,                // discard played segments — prevents loop
        lowLatencyMode:              false,
        startFragPrefetch:           true,
        enableWorker:                true,
        abrEwmaFastLive:             3.0,
        abrEwmaSlowLive:             9.0,
        manifestLoadingTimeOut:      60000,
        manifestLoadingMaxRetry:     8,
        manifestLoadingRetryDelay:   3000,
        levelLoadingTimeOut:         Math.max(30000, bufMs),
        levelLoadingMaxRetry:        6,
        fragLoadingTimeOut:          Math.max(30000, bufMs),
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
    let activeReader: ReadableStreamDefaultReader<Uint8Array> | null = null

    async function connect() {
      try {
        const res = await fetch(url, {
          headers: { Authorization: `Bearer ${token}` },
          signal: ctrl.signal,
        })
        if (!res.body) return
        const reader = res.body.getReader()
        activeReader = reader
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
    return () => { closed = true; ctrl.abort(); activeReader?.cancel() }
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
  const [tab, setTab]         = useState<'source'|'video'|'audio'|'hls'>('source')
  const [form, setForm]       = useState<any>(stream ? { ...BLANK, ...stream } : { ...BLANK })
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [categories, setCategories] = useState<string[]>([])

  useEffect(() => {
    const ctrl = new AbortController()
    api.get('/api/categories', { signal: ctrl.signal })
      .then((r: any) => setCategories((r.data as any[]).map((c: any) => c.name)))
      .catch(() => {})
    return () => ctrl.abort()
  }, [])

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
      // Trim URL and name to strip accidental newlines/spaces from copy-paste
      if (payload.url)  payload.url  = payload.url.trim()
      if (payload.name) payload.name = payload.name.trim()
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
            <div style={{ display:'flex', gap:12 }}>
              <div style={{ width:110, flexShrink:0 }}>
                <Row label="Nº Canal" hint="Número do canal — gerado automaticamente, editável">
                  <input
                    type="number" min={1} max={99999}
                    value={form.channel_num ?? ''}
                    onChange={e => set('channel_num', e.target.value === '' ? null : parseInt(e.target.value))}
                    placeholder="Auto"
                  />
                </Row>
              </div>
              <div style={{ flex:1 }}>
                <Row label="ID do Stream" hint="Apenas letras, números, _ e - (identificador interno único)">
                  <input value={form.id} onChange={e => set('id', e.target.value)}
                         disabled={!isNew} placeholder="globo_hd" />
                </Row>
              </div>
            </div>
            <Row label="Nome"><input value={form.name} onChange={e => set('name', e.target.value)} placeholder="Globo HD" /></Row>
            <Row label="Categoria" hint="Selecione a categoria do stream">
              <select value={form.category ?? ''} onChange={e => set('category', e.target.value)}>
                <option value="">— Sem categoria —</option>
                {categories.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </Row>
            <Row label="URL" hint="HLS (.m3u8), MPEG-TS, YouTube, CENC/CMAF">
              <textarea
                value={form.url}
                onChange={e => {
                  let v = e.target.value.replace(/[\n\r]/g, '')
                  // Auto-extract real URL if pasted from a browser extension player
                  // e.g. chrome-extension://xxx/player.html#https://real-url.m3u8
                  const hashIdx = v.indexOf('#http')
                  if (hashIdx !== -1) v = v.slice(hashIdx + 1)
                  set('url', v)
                }}
                onKeyDown={e => e.key === 'Enter' && e.preventDefault()}
                rows={3}
                placeholder="https://..."
              />
            </Row>
            <Row label="Tipo de stream">
              <Sel form={form} set={set} k="stream_type" opts={[['live','Ao vivo'],['vod','VOD / Arquivo']]} />
            </Row>
            <Row label="DRM">
              <Sel form={form} set={set} k="drm_type" opts={[['none','Sem DRM'],['cenc_ctr','CENC-CTR (Disney+, etc.)']]} />
            </Row>
            {form.drm_type === 'cenc_ctr' && <>
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

// ─── Record dialog ────────────────────────────────────────────────────────────

function RecordDialog({ streamName, onConfirm, onCancel }: {
  streamName: string
  onConfirm: (durationS: number | null, label: string) => void
  onCancel: () => void
}) {
  const [mode, setMode]     = useState<'indefinite' | 'timed'>('indefinite')
  const [minutes, setMinutes] = useState('60')
  const [label, setLabel]   = useState('')

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onCancel() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onCancel])

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onCancel()}>
      <div className="modal" style={{ maxWidth: 380 }}>
        <div className="modal-header">
          <h2 style={{ fontSize: 15, fontWeight: 600 }}>Iniciar Gravação</h2>
          <button className="btn btn-ghost btn-sm" onClick={onCancel}><FiX /></button>
        </div>
        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ fontSize: 13, color: 'var(--text2)' }}>{streamName}</div>
          <div>
            <label style={{ fontSize: 12, color: 'var(--text3)', display: 'block', marginBottom: 6 }}>Duração</label>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={mode === 'indefinite'} onChange={() => setMode('indefinite')} />
                Indefinida (parar manualmente)
              </label>
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                <input type="radio" checked={mode === 'timed'} onChange={() => setMode('timed')} />
                Tempo determinado:
              </label>
              {mode === 'timed' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 22 }}>
                  <input
                    className="input"
                    type="number"
                    value={minutes}
                    onChange={e => setMinutes(e.target.value)}
                    min="1" max="1440"
                    style={{ width: 70 }}
                  />
                  <span style={{ fontSize: 12, color: 'var(--text3)' }}>minutos</span>
                </div>
              )}
            </div>
          </div>
          <div>
            <label className="label" style={{ display: 'block', marginBottom: 4 }}>Etiqueta (opcional)</label>
            <input
              className="input"
              placeholder="ex: futebol, noticia…"
              value={label}
              onChange={e => setLabel(e.target.value)}
              maxLength={40}
            />
          </div>
        </div>
        <div className="modal-footer" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn btn-ghost" onClick={onCancel}>Cancelar</button>
          <button
            className="btn btn-primary"
            onClick={() => onConfirm(mode === 'timed' ? (parseInt(minutes) || 60) * 60 : null, label.trim())}
          >
            <FiCircle size={12} style={{ fill: 'currentColor' }} /> Gravar
          </button>
        </div>
      </div>
    </div>
  )
}


// ─── Recordings modal ─────────────────────────────────────────────────────────

function RecordingsModal({ onClose }: { onClose: () => void }) {
  const [tab, setTab]           = useState<'files' | 'schedules'>('files')
  const [recs, setRecs]         = useState<any[]>([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')
  const [downloading, setDl]    = useState<string | null>(null)
  const [deleting, setDeleting] = useState<string | null>(null)

  // Schedules tab state
  const [schedules, setSchedules]       = useState<any[]>([])
  const [schedsLoading, setSchedsLoad]  = useState(false)
  const [allStreams, setAllStreams]      = useState<{ id: string; name: string }[]>([])
  const [streamsLoading, setStreamsLoad] = useState(false)
  const [newSched, setNewSched]          = useState({
    stream_id: '', start_at: '', duration_min: '', label: '', repeat: 'none',
  })

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

    setStreamsLoad(true)
    api.get('/api/streams')
      .then(r => setAllStreams((r.data as any[]).map((s: any) => ({ id: s.id, name: s.name }))))
      .catch(() => {})
      .finally(() => setStreamsLoad(false))
  }, [])

  function loadSchedules() {
    setSchedsLoad(true)
    api.get('/api/recordings/schedules')
      .then(r => setSchedules(r.data))
      .catch(() => {})
      .finally(() => setSchedsLoad(false))
  }

  useEffect(() => { if (tab === 'schedules') loadSchedules() }, [tab])

  async function deleteSchedule(id: string) {
    await api.delete(`/api/recordings/schedules/${id}`)
    setSchedules(prev => prev.filter(s => s.id !== id))
  }

  async function addSchedule() {
    if (!newSched.stream_id || !newSched.start_at) return
    const start_at = new Date(newSched.start_at).getTime() / 1000
    const duration_s = newSched.duration_min ? parseInt(newSched.duration_min) * 60 : null
    await api.post('/api/recordings/schedules', {
      stream_id: newSched.stream_id,
      start_at,
      duration_s,
      label: newSched.label || null,
      repeat: newSched.repeat,
    })
    setNewSched({ stream_id: '', start_at: '', duration_min: '', label: '', repeat: 'none' })
    loadSchedules()
  }

  function fmt(bytes: number) {
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
  }

  function fmtTs(unix: number) {
    return new Date(unix * 1000).toLocaleString('pt-BR')
  }

  function repeatLabel(r: string) {
    return r === 'daily' ? 'Diário' : r === 'weekly' ? 'Semanal' : 'Uma vez'
  }

  async function deleteRecording(filename: string) {
    if (!confirm(`Excluir "${filename}"?`)) return
    setDeleting(filename)
    try {
      await api.delete(`/api/recordings/${filename}`)
      setRecs(prev => prev.filter(r => r.filename !== filename))
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Erro ao excluir gravação')
    } finally { setDeleting(null) }
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
      <div className="modal" style={{ maxWidth: 720 }}>
        <div className="modal-header">
          <h2 style={{ fontSize: 15, fontWeight: 600 }}>Gravações</h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /></button>
        </div>

        {/* Tab bar */}
        <div style={{ display: 'flex', borderBottom: '1px solid var(--border)', padding: '0 16px' }}>
          {(['files', 'schedules'] as const).map(t => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: 'none', border: 'none', padding: '10px 16px', cursor: 'pointer',
                fontSize: 13, color: tab === t ? 'var(--primary)' : 'var(--text3)',
                borderBottom: tab === t ? '2px solid var(--primary)' : '2px solid transparent',
                marginBottom: -1,
              }}
            >
              {t === 'files' ? 'Arquivos' : 'Agendamentos'}
            </button>
          ))}
        </div>

        <div className="modal-body" style={{ minHeight: 220 }}>
          {/* ── Files tab ── */}
          {tab === 'files' && (
            loading ? (
              <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 32 }}>Carregando…</div>
            ) : error ? (
              <div style={{ color: 'var(--danger)', textAlign: 'center', padding: 32, fontSize: 13 }}>{error}</div>
            ) : recs.length === 0 ? (
              <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 32 }}>
                <div style={{ fontSize: 28, marginBottom: 8 }}>📼</div>
                Nenhuma gravação encontrada.<br />
                <span style={{ fontSize: 12 }}>
                  Clique em <FiCircle size={11} style={{ verticalAlign: 'middle' }} /> em um stream ao vivo para gravar.
                </span>
              </div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)' }}>Arquivo</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text3)' }}>Tamanho</th>
                    <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text3)' }}>Data</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {recs.map(r => (
                    <tr key={r.filename} style={{ borderTop: '1px solid var(--border)' }}>
                      <td style={{ padding: '8px 8px', fontFamily: 'monospace', fontSize: 11, color: 'var(--text2)' }}>{r.filename}</td>
                      <td style={{ padding: '8px 8px', textAlign: 'right', color: 'var(--text3)' }}>{fmt(r.size_bytes)}</td>
                      <td style={{ padding: '8px 8px', textAlign: 'right', color: 'var(--text3)', fontSize: 11 }}>
                        {new Date(r.created_at).toLocaleString('pt-BR')}
                      </td>
                      <td style={{ padding: '8px 8px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <button
                          className="btn btn-ghost btn-sm"
                          title="Baixar"
                          disabled={downloading === r.filename}
                          onClick={() => download(r.filename)}
                        >
                          {downloading === r.filename ? '…' : <FiDownload size={12} />}
                        </button>
                        <button
                          className="btn btn-ghost btn-sm"
                          title="Excluir"
                          disabled={deleting === r.filename}
                          onClick={() => deleteRecording(r.filename)}
                          style={{ color: 'var(--danger)', marginLeft: 4 }}
                        >
                          {deleting === r.filename ? '…' : <FiTrash2 size={12} />}
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )
          )}

          {/* ── Schedules tab ── */}
          {tab === 'schedules' && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
              {/* New schedule form */}
              <div style={{ background: 'var(--bg2)', borderRadius: 6, padding: 14 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text3)', marginBottom: 10 }}>
                  Novo agendamento
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                  <div>
                    <label className="label">Stream</label>
                    <select
                      className="input"
                      value={newSched.stream_id}
                      onChange={e => setNewSched(p => ({ ...p, stream_id: e.target.value }))}
                    >
                      <option value="">
                        {streamsLoading ? 'Carregando streams…' : allStreams.length === 0 ? 'Nenhum stream cadastrado' : 'Selecionar…'}
                      </option>
                      {allStreams.map(s => <option key={s.id} value={s.id}>{s.name} ({s.id})</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="label">Data e hora</label>
                    <input
                      className="input"
                      type="datetime-local"
                      value={newSched.start_at}
                      onChange={e => setNewSched(p => ({ ...p, start_at: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className="label">Duração (min, vazio = indefinida)</label>
                    <input
                      className="input"
                      type="number"
                      placeholder="ex: 60"
                      value={newSched.duration_min}
                      onChange={e => setNewSched(p => ({ ...p, duration_min: e.target.value }))}
                      min="1" max="1440"
                    />
                  </div>
                  <div>
                    <label className="label">Repetição</label>
                    <select
                      className="input"
                      value={newSched.repeat}
                      onChange={e => setNewSched(p => ({ ...p, repeat: e.target.value }))}
                    >
                      <option value="none">Uma vez</option>
                      <option value="daily">Diário</option>
                      <option value="weekly">Semanal</option>
                    </select>
                  </div>
                  <div style={{ gridColumn: '1 / -1' }}>
                    <label className="label">Etiqueta (opcional)</label>
                    <input
                      className="input"
                      placeholder="ex: jornal, esportes…"
                      value={newSched.label}
                      onChange={e => setNewSched(p => ({ ...p, label: e.target.value }))}
                      maxLength={40}
                    />
                  </div>
                </div>
                <div style={{ marginTop: 10, textAlign: 'right' }}>
                  <button
                    className="btn btn-primary btn-sm"
                    disabled={!newSched.stream_id || !newSched.start_at}
                    onClick={addSchedule}
                  >
                    Agendar
                  </button>
                </div>
              </div>

              {/* Schedules list */}
              {schedsLoading ? (
                <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 16 }}>Carregando…</div>
              ) : schedules.length === 0 ? (
                <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 16, fontSize: 13 }}>
                  Nenhum agendamento.
                </div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                  <thead>
                    <tr>
                      <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)' }}>Stream</th>
                      <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)' }}>Data/Hora</th>
                      <th style={{ textAlign: 'right', padding: '6px 8px', color: 'var(--text3)' }}>Duração</th>
                      <th style={{ textAlign: 'left', padding: '6px 8px', color: 'var(--text3)' }}>Repetição</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {schedules.map(s => (
                      <tr key={s.id} style={{ borderTop: '1px solid var(--border)' }}>
                        <td style={{ padding: '8px 8px', color: 'var(--text2)' }}>
                          {allStreams.find(x => x.id === s.stream_id)?.name || s.stream_id}
                          {s.label && <span style={{ color: 'var(--text3)', marginLeft: 6, fontSize: 11 }}>({s.label})</span>}
                        </td>
                        <td style={{ padding: '8px 8px', color: 'var(--text3)', fontSize: 11 }}>{fmtTs(s.start_at)}</td>
                        <td style={{ padding: '8px 8px', textAlign: 'right', color: 'var(--text3)' }}>
                          {s.duration_s ? `${Math.round(s.duration_s / 60)} min` : '∞'}
                        </td>
                        <td style={{ padding: '8px 8px', color: 'var(--text3)' }}>{repeatLabel(s.repeat)}</td>
                        <td style={{ padding: '8px 8px', textAlign: 'right' }}>
                          <button
                            className="btn btn-ghost btn-sm"
                            title="Remover"
                            onClick={() => deleteSchedule(s.id)}
                          >
                            <FiTrash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
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
  const [showRecs, setShowRecs]         = useState(false)
  const [recording, setRecording]       = useState<Record<string, boolean>>({})
  const [stats, setStats]             = useState<Record<string, StreamStats>>({})
  const [thumbnails, setThumbnails]   = useState<Record<string, string>>({})
  const thumbnailsRef                 = useRef<Record<string, string>>({})
  const [searchParams, setSearchParams]   = useSearchParams()
  const [search, setSearch]               = useState('')
  const [m3uError, setM3uError]           = useState('')

  const activeCategory = searchParams.get('cat')

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

  // Keep ref in sync with state so unmount cleanup can revoke all blob URLs
  useEffect(() => { thumbnailsRef.current = thumbnails }, [thumbnails])

  // Revoke all blob URLs on unmount to prevent memory leak
  useEffect(() => {
    return () => { Object.values(thumbnailsRef.current).forEach(u => URL.revokeObjectURL(u)) }
  }, [])

  // When streams list changes, load thumbnails + recording status for running streams immediately
  useEffect(() => {
    if (streams.length === 0) return
    const token = localStorage.getItem('token') ?? ''
    const ctrl  = new AbortController()

    // Load thumbnails immediately for running streams (not already cached)
    const running = streams.filter(s => s.status === 'running')
    for (const s of running) {
      if (thumbnails[s.id]) continue   // already cached
      fetch(`/api/streams/${s.id}/thumbnail?t=${Date.now()}`, {
        headers: { Authorization: `Bearer ${token}` },
        signal: ctrl.signal,
      }).then(async r => {
        if (r.ok && !ctrl.signal.aborted) {
          try {
            const blob = await r.blob()
            if (!ctrl.signal.aborted) {
              setThumbnails(prev => {
                if (prev[s.id]) URL.revokeObjectURL(prev[s.id])
                return { ...prev, [s.id]: URL.createObjectURL(blob) }
              })
            }
          } catch { /* blob read failed — keep existing thumbnail */ }
        }
      }).catch(() => {})
    }

    // Restore recording status
    for (const s of running) {
      api.get(`/api/streams/${s.id}/record/status`, { signal: ctrl.signal }).then(r => {
        if (r.data?.recording) setRecording(prev => ({ ...prev, [s.id]: true }))
      }).catch(() => {})
    }

    return () => ctrl.abort()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [streams])

  // Poll stats for running streams every 5s (also fires immediately on first run)
  useEffect(() => {
    async function fetchStats() {
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
    }
    fetchStats()
    const t = setInterval(fetchStats, 5000)
    return () => clearInterval(t)
  }, [streams])

  // Refresh thumbnails for running streams every 15s
  useEffect(() => {
    let activeCtrl: AbortController | null = null
    const t = setInterval(async () => {
      // Abort previous batch and get a local reference for this tick
      activeCtrl?.abort()
      const ctrl = new AbortController()
      activeCtrl = ctrl
      const token   = localStorage.getItem('token') ?? ''
      const running = streams.filter(s => s.status === 'running')
      for (const s of running) {
        if (ctrl.signal.aborted) break
        try {
          const r = await fetch(`/api/streams/${s.id}/thumbnail?t=${Date.now()}`, {
            headers: { Authorization: `Bearer ${token}` },
            signal: ctrl.signal,
          })
          if (r.ok && !ctrl.signal.aborted) {
            const blob = await r.blob()
            if (!ctrl.signal.aborted) {
              setThumbnails(prev => {
                if (prev[s.id]) URL.revokeObjectURL(prev[s.id])
                return { ...prev, [s.id]: URL.createObjectURL(blob) }
              })
            }
          }
        } catch { /* ignore AbortError and network errors */ }
      }
    }, 15000)
    return () => { clearInterval(t); activeCtrl?.abort() }
  }, [streams])

  async function toggleAutoplay(s: Stream) {
    try {
      if (s.enabled) {
        await api.post(`/api/streams/${s.id}/stop`)
      } else {
        await api.post(`/api/streams/${s.id}/start`)
      }
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Erro ao alterar estado do stream')
    }
    load()
  }

  async function deleteStream(id: string) {
    if (!window.confirm(`Deletar stream "${id}"?`)) return
    await api.delete(`/api/streams/${id}`)
    load()
  }

  async function stopRecord(id: string) {
    try {
      await api.delete(`/api/streams/${id}/record`)
      setRecording(prev => ({ ...prev, [id]: false }))
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Erro ao parar gravação')
    }
  }

  async function startRecord(id: string) {
    try {
      await api.post(`/api/streams/${id}/record`)
      setRecording(prev => ({ ...prev, [id]: true }))
    } catch (e: any) {
      alert(e?.response?.data?.detail || 'Erro ao iniciar gravação')
    }
  }

  function toggleRecord(id: string) {
    if (recording[id]) {
      stopRecord(id)
    } else {
      startRecord(id)
    }
  }

  async function clearBan(id: string) {
    try {
      await api.post(`/api/streams/${id}/ban/clear`)
      load()
    } catch { /* ignore */ }
  }

  // Derived: filtered streams
  const filteredStreams = streams.filter(s => {
    const matchSearch   = !search || s.name.toLowerCase().includes(search.toLowerCase()) || s.id.toLowerCase().includes(search.toLowerCase())
    const matchCategory = !activeCategory || (s.category || '') === activeCategory
    return matchSearch && matchCategory
  })

  function StatusBadge({ status }: { status: string }) {
    const cls   = status === 'running' ? 'badge-running' : status === 'error' ? 'badge-error' : 'badge-stopped'
    const dot   = status === 'running' ? '●' : status === 'error' ? '●' : '○'
    const label = status === 'running' ? 'rodando' : status === 'error' ? 'erro' : 'parado'
    return <span className={`badge ${cls}`}>{dot} {label}</span>
  }

  function fmtUptime(sec: number) {
    if (sec < 60)   return `${sec}s`
    if (sec < 3600) return `${Math.floor(sec/60)}m ${sec%60}s`
    const h = Math.floor(sec/3600)
    const m = Math.floor((sec%3600)/60)
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }

  function StatsLine({ id, streamRunning }: { id: string; streamRunning: boolean }) {
    const s = stats[id]
    // Show only when stream is running and we have at least one meaningful value
    if (!streamRunning || !s) return null
    const kbps      = s.bitrate_kbps
    const mbps      = kbps > 0 ? (kbps > 1000 ? `${(kbps/1000).toFixed(1)} Mbps` : `${kbps} kbps`) : null
    const fps       = s.fps && s.fps !== '0' && s.fps !== '0.00' ? `${parseFloat(s.fps).toFixed(0)} fps` : null
    const uptime    = s.uptime_s > 0 ? `⏱ ${fmtUptime(s.uptime_s)}` : null
    const speed     = s.speed && s.speed !== '' && s.speed !== '0x' ? s.speed : null
    const totalSize = s.total_size_mb > 0
      ? (s.total_size_mb >= 1024 ? `${(s.total_size_mb/1024).toFixed(1)} GB` : `${s.total_size_mb} MB`)
      : null
    const hasDrops  = s.drop_frames > 0

    const parts = [uptime, mbps ? `⚡ ${mbps}` : null, fps, speed, totalSize].filter(Boolean)
    if (parts.length === 0 && !hasDrops) return null

    return (
      <div style={{ marginTop:2, display:'flex', flexDirection:'column', gap:1 }}>
        {parts.length > 0 && (
          <div style={{ fontSize:10, color:'var(--success)' }}>
            {parts.join(' · ')}
          </div>
        )}
        {hasDrops && (
          <div style={{ fontSize:10, color:'var(--warning)' }}>
            ⚠️ {s.drop_frames} frames descartados
          </div>
        )}
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

      {/* Search */}
      <div style={{ marginBottom:12 }}>
        <input
          type="search"
          placeholder="Buscar stream por nome ou ID…"
          value={search}
          onChange={e => setSearch(e.target.value)}
          style={{ maxWidth:380 }}
        />
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
                  <th style={{ width:44, textAlign:'center' }}>Nº</th>
                  <th style={{ width:44 }}></th>
                  <th>Nome</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {filteredStreams.length === 0 ? (
                  <tr><td colSpan={6} style={{ textAlign:'center', padding:32, color:'var(--text3)' }}>
                    Nenhum stream encontrado
                  </td></tr>
                ) : filteredStreams.map(s => (
                  <tr key={s.id}>
                    {/* Channel number */}
                    <td style={{ textAlign:'center', padding:'4px 6px' }}>
                      <span style={{ fontSize:13, fontWeight:600, color:'var(--text2)', fontVariantNumeric:'tabular-nums' }}>
                        {s.channel_num ?? '—'}
                      </span>
                    </td>
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
                      {/* Video / audio info — always visible */}
                      <div style={{ fontSize:10, color:'var(--text3)', marginTop:2, display:'flex', gap:6, flexWrap:'wrap', alignItems:'center' }}>
                        <span>🎬 {s.video_codec === 'copy' ? 'copy' : `${s.video_codec}`}</span>
                        {s.video_resolution && s.video_resolution !== 'original' && (
                          <span>· {s.video_resolution}</span>
                        )}
                        <span>· 🔊 {s.audio_codec}{s.audio_codec !== 'copy' ? ` ${s.audio_bitrate}` : ''}</span>
                        {s.buffer_seconds && <span>· ⏳ buf {s.buffer_seconds}s</span>}
                        {s.drm_type === 'cenc_ctr' && (
                          <span style={{ color:'#818cf8' }}>· 🔐 DRM</span>
                        )}
                      </div>
                      <StatsLine id={s.id} streamRunning={s.status === 'running'} />
                      {stats[s.id]?.ban_detected && (
                        <div style={{ marginTop:3, fontSize:10, color:'var(--danger)', display:'flex', alignItems:'center', gap:4 }}>
                          <FiSlash size={10} />
                          <span>
                            IP/conta banida pelo provedor
                            {(stats[s.id]?.ban_http_code ?? 0) > 0 && ` (HTTP ${stats[s.id]?.ban_http_code})`}
                            {(stats[s.id]?.ban_count ?? 0) > 1 && ` · ${stats[s.id]?.ban_count}×`}
                          </span>
                        </div>
                      )}
                    </td>
                    <td><StatusBadge status={s.status} /></td>
                    <td>
                      <div style={{ display:'flex', gap:5, flexWrap:'wrap' }}>
                        {canEdit && (
                          <Tip text={s.enabled ? 'Stream ativo — clique para desligar (para o processamento e autoplay)' : 'Stream inativo — clique para ligar (inicia e mantém rodando automaticamente)'}>
                            <button
                              onClick={() => toggleAutoplay(s)}
                              style={{
                                width: 38, height: 22, borderRadius: 11, border: 'none', cursor: 'pointer',
                                background: s.enabled ? 'var(--success)' : 'var(--bg3)',
                                position: 'relative', transition: 'background .2s', flexShrink: 0,
                                padding: 0,
                              }}
                              aria-label={s.enabled ? 'Desligar stream' : 'Ligar stream'}
                            >
                              <span style={{
                                position: 'absolute', top: 3,
                                left: s.enabled ? 19 : 3,
                                width: 16, height: 16, borderRadius: '50%',
                                background: '#fff', transition: 'left .2s',
                                display: 'block',
                              }} />
                            </button>
                          </Tip>
                        )}
                        {s.status === 'running' && (
                          <Tip text="Assistir o stream no player integrado">
                            <button className="btn btn-ghost btn-sm" onClick={() => setPlaying(s)}>
                              <FiPlay size={12} />
                            </button>
                          </Tip>
                        )}
                        {stats[s.id]?.ban_detected && canEdit && (
                          <Tip text="Limpar aviso de ban e reiniciar o stream">
                            <button className="btn btn-danger btn-sm" onClick={() => clearBan(s.id)}
                              style={{ fontSize:10, padding:'2px 7px' }}>
                              <FiSlash size={11} /> Limpar ban
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
          hlsTime={playing.hls_time ?? 15}
          hlsListSize={playing.hls_list_size ?? 15}
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
