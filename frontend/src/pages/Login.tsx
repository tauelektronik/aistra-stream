import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { FiRadio, FiUser, FiLock } from 'react-icons/fi'
import api from '../api'

export default function Login() {
  const nav = useNavigate()
  const [form, setForm]   = useState({ username: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const r = await api.post('/auth/login', form)
      localStorage.setItem('token', r.data.access_token)
      // fetch user info
      const me = await api.get('/auth/me')
      localStorage.setItem('user', JSON.stringify(me.data))
      nav('/')
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Erro ao fazer login')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div style={{
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      height: '100vh',
      background: 'radial-gradient(ellipse at 50% 0%, rgba(59,130,246,.12) 0%, var(--bg) 70%)',
    }}>
      <div style={{ maxWidth: 380, width: '100%', display: 'flex', flexDirection: 'column', gap: 28, padding: '0 16px' }}>
        {/* Logo area */}
        <div style={{ textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 64,
            height: 64,
            borderRadius: 16,
            background: 'var(--accent-glow)',
            border: '1px solid var(--border2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
          }}>
            <FiRadio size={28} color="var(--accent)" />
          </div>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.5px' }}>Aistra Stream</h1>
            <p style={{ color: 'var(--text3)', fontSize: 13, marginTop: 4 }}>Painel de gerenciamento IPTV</p>
          </div>
        </div>

        {/* Card */}
        <div className="card" style={{ padding: 28, boxShadow: 'var(--shadow)', border: '1px solid var(--border2)' }}>
          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <div className="form-group">
              <label>Usuário</label>
              <div style={{ position: 'relative' }}>
                <FiUser
                  size={14}
                  color="var(--text3)"
                  style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
                />
                <input
                  value={form.username}
                  onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
                  placeholder="admin"
                  autoFocus
                  required
                  style={{ paddingLeft: 36 }}
                />
              </div>
            </div>

            <div className="form-group">
              <label>Senha</label>
              <div style={{ position: 'relative' }}>
                <FiLock
                  size={14}
                  color="var(--text3)"
                  style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}
                />
                <input
                  type="password"
                  value={form.password}
                  onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                  placeholder="••••••••"
                  required
                  style={{ paddingLeft: 36 }}
                />
              </div>
            </div>

            {error && (
              <div style={{
                color: 'var(--danger)',
                fontSize: 13,
                background: 'rgba(239,68,68,.08)',
                border: '1px solid rgba(239,68,68,.2)',
                borderRadius: 'var(--radius)',
                padding: '8px 12px',
              }}>
                {error}
              </div>
            )}

            <button
              className="btn btn-primary"
              style={{ width: '100%', justifyContent: 'center', padding: '10px', marginTop: 4 }}
              disabled={loading}
            >
              {loading ? 'Entrando…' : 'Entrar'}
            </button>
          </form>
        </div>

        <p style={{ textAlign: 'center', fontSize: 12, color: 'var(--text3)' }}>
          Aistra Stream — IPTV Headend
        </p>
      </div>
    </div>
  )
}
