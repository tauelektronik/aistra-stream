import { Outlet, NavLink, useNavigate } from 'react-router-dom'
import { FiVideo, FiUsers, FiLogOut } from 'react-icons/fi'

export default function Layout() {
  const nav  = useNavigate()
  const user = JSON.parse(localStorage.getItem('user') || '{}')

  function logout() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    nav('/login')
  }

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="sidebar-logo">📡 Aistra Stream</div>
        <nav className="sidebar-nav">
          <NavLink to="/streams" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <FiVideo size={16} /> Streams
          </NavLink>
          {user.role === 'admin' && (
            <NavLink to="/users" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
              <FiUsers size={16} /> Usuários
            </NavLink>
          )}
        </nav>
        <div className="sidebar-bottom">
          <div style={{ marginBottom: 8 }}>
            <span style={{ color:'var(--text2)', fontWeight:500 }}>{user.username}</span>
            <span style={{ marginLeft: 6, color:'var(--text3)' }}>{user.role}</span>
          </div>
          <button className="btn btn-ghost btn-sm" style={{ width:'100%', justifyContent:'center' }} onClick={logout}>
            <FiLogOut size={13} /> Sair
          </button>
        </div>
      </aside>
      <main className="main-content">
        <Outlet />
      </main>
    </div>
  )
}
