import { useState, useEffect } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { FiGrid, FiVideo, FiUsers, FiLogOut, FiRadio } from 'react-icons/fi'

export default function Layout() {
  const nav      = useNavigate()
  const location = useLocation()
  const user     = JSON.parse(localStorage.getItem('user') || '{}')
  const [open, setOpen] = useState(false)

  // Close sidebar on navigation (mobile)
  useEffect(() => { setOpen(false) }, [location.pathname])

  // Prevent body scroll when sidebar open on mobile
  useEffect(() => {
    document.body.style.overflow = open ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [open])

  function logout() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    nav('/login')
  }

  const initials = (user.username || 'U').charAt(0).toUpperCase()

  return (
    <div className="layout">
      {/* Backdrop overlay — closes sidebar on mobile */}
      <div className={`sidebar-overlay${open ? ' open' : ''}`} onClick={() => setOpen(false)} />

      <aside className={`sidebar${open ? ' open' : ''}`}>
        <div className="sidebar-logo">
          <FiRadio size={18} color="var(--accent)" />
          Aistra Stream
        </div>
        <nav className="sidebar-nav">
          <NavLink to="/dashboard" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
            <FiGrid size={16} /> Dashboard
          </NavLink>
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
          <div className="sidebar-user">
            <div className="avatar">{initials}</div>
            <div className="sidebar-user-info">
              <span className="sidebar-username">{user.username}</span>
              {user.role && <span className="sidebar-role">{user.role}</span>}
            </div>
          </div>
          <button className="btn btn-ghost btn-sm" style={{ width: '100%', justifyContent: 'center' }} onClick={logout}>
            <FiLogOut size={13} /> Sair
          </button>
        </div>
      </aside>

      <main className="main-content">
        {/* Mobile top bar with hamburger */}
        <div className="mobile-topbar">
          <button className="menu-btn" onClick={() => setOpen(o => !o)} aria-label="Abrir menu">
            <span /><span /><span />
          </button>
          <span className="topbar-title">
            <FiRadio size={15} style={{ marginRight: 6, verticalAlign: 'middle' }} />
            Aistra Stream
          </span>
        </div>
        <Outlet />
      </main>
    </div>
  )
}
