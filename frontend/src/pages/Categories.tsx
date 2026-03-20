import { useEffect, useRef, useState } from 'react'
import {
  FiPlus, FiEdit2, FiTrash2, FiX, FiUpload, FiImage,
  FiCheckSquare, FiSquare, FiSave, FiLink,
} from 'react-icons/fi'
import api from '../api'

interface Category {
  id: number
  name: string
  logo_path: string | null
  created_at: string
}

interface Stream {
  id: string
  name: string
  category: string | null
  status: string
}

// ─── Category form modal ───────────────────────────────────────────────────────

function CategoryModal({
  cat, streams, onSave, onClose,
}: {
  cat: Category | null
  streams: Stream[]
  onSave: () => void
  onClose: () => void
}) {
  const isNew = !cat
  const [name, setName]           = useState(cat?.name ?? '')
  const [saving, setSaving]       = useState(false)
  const [error, setError]         = useState('')
  const [logoMode, setLogoMode]   = useState<'file'|'url'>('file')
  const [logoUrl, setLogoUrl]     = useState('')
  const [logoPreview, setPreview] = useState<string | null>(
    cat?.logo_path ? `/api/categories/${cat.id}/logo` : null
  )
  const [logoFile, setLogoFile]   = useState<File | null>(null)
  const [selected, setSelected]   = useState<Set<string>>(
    () => new Set(streams.filter(s => s.category === cat?.name).map(s => s.id))
  )
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', h)
    return () => document.removeEventListener('keydown', h)
  }, [onClose])

  function switchMode(m: 'file'|'url') {
    setLogoMode(m)
    setLogoFile(null)
    if (m === 'url') {
      setPreview(logoUrl || null)
    } else {
      setPreview(cat?.logo_path ? `/api/categories/${cat.id}/logo` : null)
    }
  }

  function pickLogo(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0]
    if (!f) return
    setLogoFile(f)
    setPreview(prev => {
      if (prev?.startsWith('blob:')) URL.revokeObjectURL(prev)
      return URL.createObjectURL(f)
    })
    e.target.value = ''
  }

  function onUrlChange(v: string) {
    // Auto-detect base64 data URI — convert to File and switch to upload mode
    if (v.startsWith('data:image')) {
      try {
        const [header, b64] = v.split(',')
        const mime = header.match(/data:(image\/[^;]+)/)?.[1] ?? 'image/jpeg'
        const ext  = mime.split('/')[1].replace('svg+xml', 'svg')
        const bin  = atob(b64)
        const arr  = new Uint8Array(bin.length)
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
        const file = new File([arr], `logo.${ext}`, { type: mime })
        setLogoMode('file')
        setLogoFile(file)
        setPreview(URL.createObjectURL(file))
        setLogoUrl('')
      } catch { /* ignore malformed base64 */ }
      return
    }
    setLogoUrl(v)
    setPreview(v.startsWith('http') ? v : null)
  }

  function toggleStream(id: string) {
    setSelected(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  async function save() {
    if (!name.trim()) { setError('Nome obrigatório'); return }
    setSaving(true); setError('')
    try {
      let catId = cat?.id
      if (isNew) {
        const r = await api.post('/api/categories', { name: name.trim() })
        catId = r.data.id
      } else {
        await api.put(`/api/categories/${catId}`, { name: name.trim() })
      }
      // Save logo — file upload or URL
      if (catId !== undefined) {
        if (logoMode === 'url' && logoUrl.trim()) {
          await api.put(`/api/categories/${catId}/logo-url`, { url: logoUrl.trim() })
        } else if (logoMode === 'file' && logoFile) {
          const fd = new FormData()
          fd.append('file', logoFile)
          const logoRes = await fetch(`/api/categories/${catId}/logo`, {
            method: 'POST',
            headers: { Authorization: `Bearer ${localStorage.getItem('token')}` },
            body: fd,
          })
          if (!logoRes.ok) {
            const msg = await logoRes.text().catch(() => '')
            throw new Error(`Erro ao enviar logo: ${logoRes.status}${msg ? ' — ' + msg : ''}`)
          }
        }
      }
      // Assign streams
      if (catId !== undefined) {
        await api.post(`/api/categories/${catId}/streams`, {
          stream_ids: Array.from(selected),
        })
      }
      onSave()
    } catch (e: any) {
      setError(e.response?.data?.detail || 'Erro ao salvar')
    } finally {
      setSaving(false)
    }
  }

  const runningCount  = streams.filter(s => selected.has(s.id) && s.status === 'running').length
  const selectedCount = selected.size

  return (
    <div className="modal-overlay" onClick={e => e.target === e.currentTarget && onClose()}>
      <div className="modal" style={{ maxWidth: 580 }}>
        <div className="modal-header">
          <h2 style={{ fontSize: 15, fontWeight: 600 }}>
            {isNew ? 'Nova Categoria' : `Editar: ${cat!.name}`}
          </h2>
          <button className="btn btn-ghost btn-sm" onClick={onClose}><FiX /></button>
        </div>

        <div className="modal-body">
          {/* Name + Logo */}
          <div style={{ display: 'flex', gap: 16, alignItems: 'flex-start', marginBottom: 20 }}>
            {/* Logo preview box */}
            <div style={{ flexShrink: 0 }}>
              <div
                onClick={() => logoMode === 'file' && fileRef.current?.click()}
                style={{
                  width: 72, height: 72, borderRadius: 10,
                  border: '2px dashed var(--border)',
                  cursor: logoMode === 'file' ? 'pointer' : 'default',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  background: 'var(--bg3)', overflow: 'hidden', position: 'relative',
                }}
                title={logoMode === 'file' ? 'Clique para enviar logo (PNG, JPG, SVG, WEBP — máx 2MB)' : ''}
              >
                {logoPreview
                  ? <img src={logoPreview} alt="logo"
                      style={{ width: '100%', height: '100%', objectFit: 'contain', padding: 4 }}
                      onError={() => setPreview(null)}
                    />
                  : <FiImage size={22} color="var(--text3)" />
                }
                {logoMode === 'file' && (
                  <div style={{
                    position: 'absolute', inset: 0, background: 'rgba(0,0,0,.45)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    opacity: 0, transition: '.15s',
                  }}
                    onMouseEnter={e => (e.currentTarget.style.opacity = '1')}
                    onMouseLeave={e => (e.currentTarget.style.opacity = '0')}
                  >
                    <FiUpload size={18} color="#fff" />
                  </div>
                )}
              </div>
              {/* Mode toggle */}
              <div style={{ display: 'flex', marginTop: 6, borderRadius: 6, overflow: 'hidden', border: '1px solid var(--border)' }}>
                <button
                  type="button"
                  onClick={() => switchMode('file')}
                  style={{
                    flex: 1, padding: '3px 0', fontSize: 11, border: 'none', cursor: 'pointer',
                    background: logoMode === 'file' ? 'var(--accent)' : 'var(--bg2)',
                    color: logoMode === 'file' ? '#fff' : 'var(--text3)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3,
                  }}
                  title="Upload de arquivo"
                ><FiUpload size={10} /> Arquivo</button>
                <button
                  type="button"
                  onClick={() => switchMode('url')}
                  style={{
                    flex: 1, padding: '3px 0', fontSize: 11, border: 'none', cursor: 'pointer',
                    background: logoMode === 'url' ? 'var(--accent)' : 'var(--bg2)',
                    color: logoMode === 'url' ? '#fff' : 'var(--text3)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 3,
                  }}
                  title="URL da imagem"
                ><FiLink size={10} /> URL</button>
              </div>
            </div>
            <input ref={fileRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={pickLogo} />

            {/* Name + URL input */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 10 }}>
              <div className="form-group" style={{ margin: 0 }}>
                <label style={{ fontWeight: 500 }}>Nome da Categoria</label>
                <input
                  value={name}
                  onChange={e => setName(e.target.value)}
                  placeholder="Ex: Esportes, Notícias, Filmes…"
                  autoFocus
                />
              </div>
              {logoMode === 'url' && (
                <div className="form-group" style={{ margin: 0 }}>
                  <label style={{ fontWeight: 500 }}>URL do Logo</label>
                  <input
                    value={logoUrl}
                    onChange={e => onUrlChange(e.target.value)}
                    placeholder="https://exemplo.com/logo.png"
                    type="url"
                  />
                </div>
              )}
            </div>
          </div>

          {/* Stream assignment */}
          <div>
            <div style={{ fontWeight: 500, fontSize: 13, marginBottom: 8, display: 'flex', justifyContent: 'space-between' }}>
              <span>Streams desta categoria</span>
              <span style={{ fontSize: 12, color: 'var(--text3)' }}>
                {selectedCount} selecionado{selectedCount !== 1 ? 's' : ''}
                {runningCount > 0 && <span style={{ color: 'var(--success)', marginLeft: 6 }}>● {runningCount} ao vivo</span>}
              </span>
            </div>

            {streams.length === 0 ? (
              <div style={{ color: 'var(--text3)', fontSize: 13, padding: '16px 0' }}>
                Nenhum stream cadastrado ainda.
              </div>
            ) : (
              <div style={{
                border: '1px solid var(--border)', borderRadius: 8,
                maxHeight: 260, overflowY: 'auto',
              }}>
                {streams.map((s, i) => (
                  <div
                    key={s.id}
                    onClick={() => toggleStream(s.id)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '9px 12px', cursor: 'pointer',
                      borderTop: i > 0 ? '1px solid var(--border)' : undefined,
                      background: selected.has(s.id) ? 'var(--accent-glow)' : undefined,
                      transition: 'background .1s',
                    }}
                  >
                    {selected.has(s.id)
                      ? <FiCheckSquare size={15} color="var(--accent)" />
                      : <FiSquare size={15} color="var(--text3)" />
                    }
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 500, fontSize: 13, color: 'var(--text)' }}>{s.name}</div>
                      <div style={{ fontSize: 11, color: 'var(--text3)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.id}
                        {s.category && s.category !== name && s.category !== cat?.name && (
                          <span style={{ marginLeft: 6, color: 'var(--warning, #f59e0b)' }}>
                            (em: {s.category})
                          </span>
                        )}
                      </div>
                    </div>
                    {s.status === 'running' && (
                      <span style={{ fontSize: 10, color: 'var(--success)' }}>● ao vivo</span>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>

          {error && (
            <div style={{ color: 'var(--danger)', fontSize: 13, marginTop: 12 }}>{error}</div>
          )}
        </div>

        <div className="modal-footer">
          <button className="btn btn-ghost" onClick={onClose}>Cancelar</button>
          <button className="btn btn-primary" onClick={save} disabled={saving}>
            <FiSave size={13} /> {saving ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function Categories() {
  const [cats, setCats]       = useState<Category[]>([])
  const [streams, setStreams] = useState<Stream[]>([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState<Category | null | 'new'>(null)

  const load = async () => {
    try {
      const [cr, sr] = await Promise.all([
        api.get('/api/categories'),
        api.get('/api/streams'),
      ])
      setCats(cr.data)
      setStreams(sr.data)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function del(cat: Category) {
    if (!window.confirm(`Deletar categoria "${cat.name}"?\nOs streams não serão deletados, apenas desvinculados.`)) return
    await api.delete(`/api/categories/${cat.id}`)
    load()
  }

  function streamCount(catName: string) {
    return streams.filter(s => s.category === catName).length
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Categorias</h1>
        <div className="page-header-actions">
          <button className="btn btn-primary btn-sm" onClick={() => setEditing('new')}>
            <FiPlus size={13} /> Nova Categoria
          </button>
        </div>
      </div>

      <div className="page-content">
        {loading ? (
          <div style={{ color: 'var(--text3)', textAlign: 'center', padding: 40 }}>Carregando…</div>
        ) : cats.length === 0 ? (
          <div className="card" style={{ textAlign: 'center', padding: 48, color: 'var(--text3)' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>🗂️</div>
            <p>Nenhuma categoria criada ainda.</p>
            <button className="btn btn-primary" style={{ marginTop: 16 }} onClick={() => setEditing('new')}>
              <FiPlus /> Criar primeira categoria
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
            {cats.map(cat => (
              <div key={cat.id} className="card" style={{ padding: 0, overflow: 'hidden' }}>
                {/* Logo banner */}
                <div style={{
                  height: 80, background: 'var(--bg3)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  position: 'relative', overflow: 'hidden',
                }}>
                  {cat.logo_path ? (
                    <img
                      src={`/api/categories/${cat.id}/logo?t=${cat.logo_path}`}
                      alt={cat.name}
                      style={{ maxHeight: '100%', maxWidth: '100%', objectFit: 'contain', padding: 8 }}
                    />
                  ) : (
                    <FiImage size={28} color="var(--text3)" />
                  )}
                </div>

                {/* Info */}
                <div style={{ padding: '12px 14px' }}>
                  <div style={{ fontWeight: 600, fontSize: 14, color: 'var(--text)', marginBottom: 4 }}>
                    {cat.name}
                  </div>
                  <div style={{ fontSize: 12, color: 'var(--text3)' }}>
                    {streamCount(cat.name)} stream{streamCount(cat.name) !== 1 ? 's' : ''}
                  </div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 10 }}>
                    <button
                      className="btn btn-ghost btn-sm"
                      style={{ flex: 1 }}
                      onClick={() => setEditing(cat)}
                    >
                      <FiEdit2 size={12} /> Editar
                    </button>
                    <button
                      className="btn btn-danger btn-sm"
                      onClick={() => del(cat)}
                    >
                      <FiTrash2 size={12} />
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {editing && (
        <CategoryModal
          cat={editing === 'new' ? null : editing}
          streams={streams}
          onSave={() => { setEditing(null); load() }}
          onClose={() => setEditing(null)}
        />
      )}
    </div>
  )
}
