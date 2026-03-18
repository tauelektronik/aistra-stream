import { useEffect, useRef, useState, useCallback } from 'react'
import Hls from 'hls.js'
import { FiPlay, FiSquare, FiEdit2, FiTrash2, FiPlus, FiX, FiRefreshCw, FiExternalLink, FiEye } from 'react-icons/fi'
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
  enabled: boolean; status: string
  created_at: string; updated_at: string
}

const BLANK: Omit<Stream, 'status'|'created_at'|'updated_at'> = {
  id:'', name:'', url:'', drm_type:'none', drm_keys:'', drm_kid:'', drm_key:'',
  stream_type:'live', video_codec:'libx264', video_preset:'ultrafast',
  video_crf:26, video_maxrate:'', video_resolution:'original',
  audio_codec:'aac', audio_bitrate:'128k',
  hls_time:4, hls_list_size:30, buffer_seconds:20,
  output_rtmp:'', output_udp:'', enabled:true,
}

// ─── Player component ─────────────────────────────────────────────────────────

function StreamPlayer({ streamId, bufferSeconds, onClose }: {
  streamId: string; bufferSeconds: number; onClose: () => void
}) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const hlsRef   = useRef<Hls | null>(null)
  const [status, setStatus] = useState('Conectando…')

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
      })
      hlsRef.current = hls
      hls.on(Hls.Events.MANIFEST_PARSED, () => { setStatus(''); video.play().catch(() => {}) })
      hls.on(Hls.Events.ERROR, (_e, d) => {
        if (d.fatal) setStatus(`Erro: ${d.details}`)
        else if (d.type !== Hls.ErrorTypes.MEDIA_ERROR) return  // suppress non-fatal media errors
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

// ─── Stream form modal ────────────────────────────────────────────────────────

function StreamModal({ stream, onSave, onClose }: {
  stream: Partial<Stream> | null; onSave: () => void; onClose: () => void
}) {
  const isNew = !stream?.id
  const [tab, setTab]     = useState<'source'|'video'|'audio'|'hls'>('source')
  const [form, setForm]   = useState<any>(stream ? { ...BLANK, ...stream } : { ...BLANK })
  const [saving, setSaving] = useState(false)
  const [error, setError]  = useState('')

  function set(k: string, v: any) { setForm((f: any) => ({ ...f, [k]: v })) }

  async function save() {
    setSaving(true); setError('')
    try {
      const payload = { ...form }
      // Auto-generate id from name if empty or too short
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

  const Row = ({ label, children, hint }: { label: string; children: React.ReactNode; hint?: string }) => (
    <div className="form-group">
      <label>{label}</label>
      {children}
      {hint && <span className="form-hint">{hint}</span>}
    </div>
  )
  const Sel = ({ k, opts }: { k: string; opts: [string, string][] }) => (
    <select value={form[k]} onChange={e => set(k, e.target.value)}>
      {opts.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
    </select>
  )
  const Num = ({ k, min, max, step=1 }: { k: string; min: number; max: number; step?: number }) => (
    <div style={{ display:'flex', gap:8, alignItems:'center' }}>
      <input type="range" min={min} max={max} step={step} value={form[k]}
             onChange={e => set(k, Number(e.target.value))}
             style={{ flex:1, padding:0, border:'none', background:'transparent', accentColor:'var(--accent)' }} />
      <span style={{ minWidth:36, color:'var(--text2)', fontSize:13 }}>{form[k]}</span>
    </div>
  )

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
            <Row label="URL" hint="HLS (.m3u8), MPEG-TS, ou CENC/CMAF">
              <textarea value={form.url} onChange={e => set('url', e.target.value)} rows={3} placeholder="https://..." />
            </Row>
            <Row label="Tipo de stream">
              <Sel k="stream_type" opts={[['live','Ao vivo'],['vod','VOD']]} />
            </Row>
            <Row label="DRM">
              <Sel k="drm_type" opts={[['none','Sem DRM'],['cenc-ctr','CENC-CTR (Disney+, etc.)']]} />
            </Row>
            {form.drm_type === 'cenc-ctr' && <>
              <Row label="Keys / CDM Script" hint="Um par KID:KEY por linha — formato de saída de CDM tools">
                <textarea
                  rows={5}
                  value={form.drm_keys||''}
                  onChange={e => set('drm_keys', e.target.value)}
                  placeholder={'c2e511d926db4f209e8cd856656e6bb1:4d67d0f698ad334072056dfbf61d4a99\n0101a79fc2c4cd3239893a14661661ac:dbbf91281e295228e8a49e273f77bd9d\n...'}
                  style={{ fontFamily:'monospace', fontSize:12, resize:'vertical' }}
                />
              </Row>
            </>}
            <div style={{ display:'flex', alignItems:'center', gap:10 }}>
              <input type="checkbox" id="enabled" checked={form.enabled} onChange={e => set('enabled', e.target.checked)} style={{ width:'auto' }} />
              <label htmlFor="enabled" style={{ fontSize:13, color:'var(--text2)', cursor:'pointer' }}>Stream ativo</label>
            </div>
          </>}

          {tab === 'video' && <>
            <Row label="Codec de vídeo">
              <Sel k="video_codec" opts={[
                ['copy','Copy (sem transcode — mais rápido)'],
                ['libx264','libx264 (CPU — qualidade alta)'],
                ['h264_nvenc','h264_nvenc (GPU NVIDIA)'],
              ]} />
            </Row>
            {form.video_codec !== 'copy' && <>
              <Row label="Preset (velocidade × qualidade)" hint="Mais rápido = menos CPU, menor qualidade">
                <Sel k="video_preset" opts={[
                  ['ultrafast','ultrafast'],['superfast','superfast'],['veryfast','veryfast'],
                  ['faster','faster'],['fast','fast'],['medium','medium'],
                ]} />
              </Row>
              <Row label={`CRF: ${form.video_crf} — qualidade (menor = melhor)`}>
                <Num k="video_crf" min={0} max={51} />
              </Row>
              <Row label="Resolução">
                <Sel k="video_resolution" opts={[
                  ['original','Original'],['1920x1080','1080p'],['1280x720','720p'],['854x480','480p'],
                ]} />
              </Row>
              <Row label="Bitrate máximo (opcional)" hint='Ex: "4000k" ou deixe vazio para sem limite'>
                <input value={form.video_maxrate||''} onChange={e => set('video_maxrate', e.target.value)} placeholder="4000k" />
              </Row>
            </>}
          </>}

          {tab === 'audio' && <>
            <Row label="Codec de áudio">
              <Sel k="audio_codec" opts={[['copy','Copy'],['aac','AAC (transcode)']]} />
            </Row>
            {form.audio_codec !== 'copy' && (
              <Row label="Bitrate de áudio">
                <Sel k="audio_bitrate" opts={[['96k','96k'],['128k','128k'],['192k','192k'],['256k','256k']]} />
              </Row>
            )}
          </>}

          {tab === 'hls' && <>
            <Row label={`Duração do segmento HLS: ${form.hls_time}s`} hint="Menor = menor latência, maior = mais estável">
              <Num k="hls_time" min={1} max={10} />
            </Row>
            <Row label={`Segmentos na playlist: ${form.hls_list_size}`} hint="Janela disponível para o player">
              <Num k="hls_list_size" min={5} max={120} />
            </Row>
            <Row label={`Buffer do player: ${form.buffer_seconds}s`} hint="Atraso em relação ao vivo — mais = mais suave">
              <Num k="buffer_seconds" min={5} max={120} step={5} />
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
                <input value={form.output_rtmp||''} onChange={e => set('output_rtmp', e.target.value)}
                       placeholder="rtmp://..." />
              </Row>
              <Row label="Saída UDP / Multicast" hint='Ex: udp://239.0.0.1:1234 ou udp://127.0.0.1:5000'>
                <input value={form.output_udp||''} onChange={e => set('output_udp', e.target.value)}
                       placeholder="udp://..." />
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

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Streams() {
  const [streams, setStreams]       = useState<Stream[]>([])
  const [loading, setLoading]       = useState(true)
  const [editing, setEditing]       = useState<Stream | null | 'new'>(null)
  const [playing, setPlaying]       = useState<Stream | null>(null)
  const [deleting, setDeleting]     = useState<string | null>(null)
  const user = JSON.parse(localStorage.getItem('user') || '{}')
  const canEdit = user.role === 'admin' || user.role === 'operator'

  const load = useCallback(async () => {
    try {
      const r = await api.get('/api/streams')
      setStreams(r.data)
    } finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])
  // Auto-refresh status every 10s
  useEffect(() => { const t = setInterval(load, 10000); return () => clearInterval(t) }, [load])

  async function stopStream(id: string) {
    await api.post(`/api/streams/${id}/stop`)
    load()
  }

  async function deleteStream(id: string) {
    if (!window.confirm(`Deletar stream "${id}"?`)) return
    await api.delete(`/api/streams/${id}`)
    load()
  }

  function StatusBadge({ status }: { status: string }) {
    const cls = status === 'running' ? 'badge-running' : status === 'error' ? 'badge-error' : 'badge-stopped'
    const dot = status === 'running' ? '●' : status === 'error' ? '●' : '○'
    return <span className={`badge ${cls}`}>{dot} {status}</span>
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Streams</h1>
        <div style={{ display:'flex', gap:8 }}>
          <button className="btn btn-ghost btn-sm" onClick={load}><FiRefreshCw size={13} /> Atualizar</button>
          {canEdit && (
            <button className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>
              <FiPlus size={13} /> Novo Stream
            </button>
          )}
        </div>
      </div>

      <div className="page-content">
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
            <table>
              <thead>
                <tr>
                  <th>Nome</th>
                  <th>ID</th>
                  <th>DRM</th>
                  <th>Codec</th>
                  <th>Buffer</th>
                  <th>Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {streams.map(s => (
                  <tr key={s.id}>
                    <td>
                      <div style={{ fontWeight:500, color:'var(--text)' }}>{s.name}</div>
                      <div style={{ fontSize:11, color:'var(--text3)', marginTop:2, maxWidth:280, overflow:'hidden', textOverflow:'ellipsis', whiteSpace:'nowrap' }}>
                        {s.url.length > 60 ? s.url.slice(0,60)+'…' : s.url}
                      </div>
                    </td>
                    <td><code style={{ fontSize:12, color:'var(--text2)' }}>{s.id}</code></td>
                    <td>
                      {s.drm_type === 'cenc-ctr'
                        ? <span className="badge" style={{ background:'#1e1b4b', color:'#818cf8' }}>CENC-CTR</span>
                        : <span style={{ color:'var(--text3)', fontSize:12 }}>—</span>
                      }
                    </td>
                    <td>
                      <span style={{ fontSize:12, color:'var(--text2)' }}>
                        {s.video_codec === 'copy' ? 'copy' : `${s.video_codec} ${s.video_preset}`}
                      </span>
                    </td>
                    <td><span style={{ fontSize:12, color:'var(--text2)' }}>{s.buffer_seconds}s</span></td>
                    <td><StatusBadge status={s.status} /></td>
                    <td>
                      <div style={{ display:'flex', gap:6 }}>
                        <button className="btn btn-success btn-sm" title="Assistir"
                                onClick={() => setPlaying(s)}>
                          <FiPlay size={12} />
                        </button>
                        {s.status === 'running' && (
                          <button className="btn btn-ghost btn-sm" title="Parar"
                                  onClick={() => stopStream(s.id)}>
                            <FiSquare size={12} />
                          </button>
                        )}
                        <a href={getHlsUrl(s.id)} target="_blank" rel="noreferrer"
                           className="btn btn-ghost btn-sm" title="Abrir URL">
                          <FiExternalLink size={12} />
                        </a>
                        {canEdit && <>
                          <button className="btn btn-ghost btn-sm" title="Editar"
                                  onClick={() => setEditing(s)}>
                            <FiEdit2 size={12} />
                          </button>
                          <button className="btn btn-danger btn-sm" title="Deletar"
                                  onClick={() => deleteStream(s.id)}>
                            <FiTrash2 size={12} />
                          </button>
                        </>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Player overlay */}
      {playing && (
        <StreamPlayer
          streamId={playing.id}
          bufferSeconds={playing.buffer_seconds}
          onClose={() => { setPlaying(null); load() }}
        />
      )}

      {/* Stream form modal */}
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
