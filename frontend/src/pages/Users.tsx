import { useEffect, useState, useCallback } from 'react'
import { FiPlus, FiEdit2, FiTrash2, FiX } from 'react-icons/fi'
import api from '../api'

interface User { id: number; username: string; email?: string; role: string; active: boolean }

// Defined outside to keep stable identity (no remount on parent re-render)
function RoleBadge({ role }: { role: string }) {
  const colors: Record<string, string> = { admin:'#7c3aed', operator:'#0ea5e9', viewer:'#64748b' }
  return <span className="badge" style={{ background:`${colors[role]}22`, color: colors[role] || '#fff' }}>{role}</span>
}

export default function Users() {
  const [users, setUsers]     = useState<User[]>([])
  const [editing, setEditing] = useState<User | null | 'new'>(null)
  const [form, setForm]       = useState({ username:'', password:'', email:'', role:'viewer', active:true })
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')

  const load = useCallback(async () => {
    const r = await api.get('/api/users')
    setUsers(r.data)
  }, [])

  useEffect(() => { load() }, [load])

  function openNew() {
    setForm({ username:'', password:'', email:'', role:'viewer', active:true })
    setEditing('new'); setError('')
  }
  function openEdit(u: User) {
    setForm({ username:u.username, password:'', email:u.email||'', role:u.role, active:u.active })
    setEditing(u); setError('')
  }

  async function save() {
    setSaving(true); setError('')
    try {
      const isNew = editing === 'new'
      const payload: any = { ...form }
      if (!isNew && !payload.password) delete payload.password
      if (isNew) await api.post('/api/users', payload)
      else       await api.put(`/api/users/${(editing as User).id}`, payload)
      setEditing(null); load()
    } catch(e: any) {
      const detail = e.response?.data?.detail
      if (Array.isArray(detail)) {
        setError(detail.map((d: any) => `${d.loc?.slice(-1)[0]}: ${d.msg}`).join(' | '))
      } else {
        setError(detail || 'Erro ao salvar')
      }
    } finally { setSaving(false) }
  }

  async function del(id: number, name: string) {
    if (!window.confirm(`Deletar usuário "${name}"?`)) return
    await api.delete(`/api/users/${id}`)
    load()
  }

  return (
    <div className="page">
      <div className="page-header">
        <h1>Usuários</h1>
        <div className="page-header-actions">
          <button className="btn btn-primary btn-sm" onClick={openNew}><FiPlus size={13} /> Novo Usuário</button>
        </div>
      </div>

      <div className="page-content">
        <div className="card" style={{ padding:0, overflow:'hidden' }}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Usuário</th>
                  <th className="col-hide-xs">Email</th>
                  <th>Papel</th>
                  <th className="col-hide-xs">Status</th>
                  <th>Ações</th>
                </tr>
              </thead>
              <tbody>
                {users.map(u => (
                  <tr key={u.id}>
                    <td>
                      <strong>{u.username}</strong>
                      {/* Show status inline on xs when columns are hidden */}
                      <span className="col-hide-xs" style={{ display:'none' }} />
                    </td>
                    <td className="col-hide-xs" style={{ color:'var(--text3)' }}>{u.email || '—'}</td>
                    <td><RoleBadge role={u.role} /></td>
                    <td className="col-hide-xs">
                      {u.active
                        ? <span className="badge badge-running">ativo</span>
                        : <span className="badge badge-stopped">inativo</span>
                      }
                    </td>
                    <td>
                      <div style={{ display:'flex', gap:6 }}>
                        <button className="btn btn-ghost btn-sm" onClick={() => openEdit(u)} title="Editar"><FiEdit2 size={12} /></button>
                        <button className="btn btn-danger btn-sm" onClick={() => del(u.id, u.username)} title="Deletar"><FiTrash2 size={12} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
                {users.length === 0 && (
                  <tr><td colSpan={5} style={{ textAlign:'center', padding:'32px 0', color:'var(--text3)' }}>Nenhum usuário cadastrado</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {editing && (
        <div className="modal-overlay" onClick={e => e.target === e.currentTarget && setEditing(null)}>
          <div className="modal" style={{ maxWidth:420 }}>
            <div className="modal-header">
              <h2 style={{ fontSize:16, fontWeight:600 }}>
                {editing === 'new' ? 'Novo Usuário' : `Editar: ${(editing as User).username}`}
              </h2>
              <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}><FiX /></button>
            </div>
            <div className="modal-body">
              <div className="form-group">
                <label>Usuário</label>
                <input value={form.username} disabled={editing !== 'new'}
                       onChange={e => setForm(f => ({ ...f, username: e.target.value }))} />
              </div>
              <div className="form-group">
                <label>{editing === 'new' ? 'Senha' : 'Nova senha (vazio = não alterar)'}</label>
                <input type="password" value={form.password}
                       onChange={e => setForm(f => ({ ...f, password: e.target.value }))}
                       placeholder={editing === 'new' ? 'Mínimo 8 caracteres' : ''} />
                {editing === 'new' && form.password.length > 0 && form.password.length < 8 && (
                  <span className="form-hint" style={{ color:'var(--warning)' }}>
                    Senha deve ter ao menos 8 caracteres ({form.password.length}/8)
                  </span>
                )}
              </div>
              <div className="form-group">
                <label>Email</label>
                <input value={form.email} onChange={e => setForm(f => ({ ...f, email: e.target.value }))} />
              </div>
              <div className="form-group">
                <label>Papel</label>
                <select value={form.role} onChange={e => setForm(f => ({ ...f, role: e.target.value }))}>
                  <option value="admin">admin — acesso total</option>
                  <option value="operator">operator — gerencia streams</option>
                  <option value="viewer">viewer — só visualiza</option>
                </select>
              </div>
              <div style={{ display:'flex', alignItems:'center', gap:10 }}>
                <input type="checkbox" id="u_active" checked={form.active}
                       onChange={e => setForm(f => ({ ...f, active: e.target.checked }))} style={{ width:'auto' }} />
                <label htmlFor="u_active" style={{ fontSize:13, color:'var(--text2)', cursor:'pointer' }}>Usuário ativo</label>
              </div>
              {error && <div style={{ color:'var(--danger)', fontSize:13 }}>{error}</div>}
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setEditing(null)}>Cancelar</button>
              <button className="btn btn-primary" onClick={save} disabled={saving}>{saving ? 'Salvando…' : 'Salvar'}</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
