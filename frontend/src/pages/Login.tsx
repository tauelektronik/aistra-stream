import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
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
    <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100vh', background:'var(--bg)' }}>
      <div className="card" style={{ width: 360, display:'flex', flexDirection:'column', gap: 24 }}>
        <div style={{ textAlign:'center' }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>📡</div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color:'var(--text)' }}>Aistra Stream</h1>
          <p style={{ color:'var(--text3)', fontSize: 13, marginTop: 4 }}>Painel de gerenciamento de streams</p>
        </div>

        <form onSubmit={submit} style={{ display:'flex', flexDirection:'column', gap: 14 }}>
          <div className="form-group">
            <label>Usuário</label>
            <input
              value={form.username}
              onChange={e => setForm(f => ({ ...f, username: e.target.value }))}
              placeholder="admin"
              autoFocus
              required
            />
          </div>
          <div className="form-group">
            <label>Senha</label>
            <input
              type="password"
              value={form.password}
              onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
              placeholder="••••••••"
              required
            />
          </div>
          {error && <div style={{ color:'var(--danger)', fontSize: 13 }}>{error}</div>}
          <button className="btn btn-primary" style={{ width:'100%', justifyContent:'center', padding:'10px' }} disabled={loading}>
            {loading ? 'Entrando…' : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  )
}
