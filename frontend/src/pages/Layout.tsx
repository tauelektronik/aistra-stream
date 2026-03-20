import { useState, useEffect } from 'react'
import { Outlet, NavLink, useNavigate, useLocation } from 'react-router-dom'
import { FiGrid, FiVideo, FiUsers, FiLogOut, FiRadio, FiSettings, FiChevronRight, FiTag, FiSun, FiMoon, FiActivity } from 'react-icons/fi'

interface Category { id: number; name: string; logo_path: string | null }

export default function Layout() {
  const nav      = useNavigate()
  const location = useLocation()
  const user     = JSON.parse(localStorage.getItem('user') || '{}')
  const [open, setOpen]               = useState(false)
  const [theme, setTheme]             = useState<'dark'|'light'>(
    () => (localStorage.getItem('theme') as 'dark'|'light') || 'dark'
  )
  const [configOpen, setConfigOpen]   = useState(
    () => ['/settings', '/users', '/categories', '/connection-logs'].some(p => location.pathname.startsWith(p))
  )
  const [streamsOpen, setStreamsOpen] = useState(
    () => location.pathname.startsWith('/streams')
  )
  const [cats, setCats] = useState<Category[]>([])
  const [logoSize, setLogoSize] = useState<number>(
    () => Number(localStorage.getItem('sidebar_logo_size') || 22)
  )

  // Listen for logo size changes from Settings page
  useEffect(() => {
    const handler = () => setLogoSize(Number(localStorage.getItem('sidebar_logo_size') || 22))
    window.addEventListener('sidebar_logo_size', handler)
    return () => window.removeEventListener('sidebar_logo_size', handler)
  }, [])

  // Apply/persist theme
  useEffect(() => {
    document.documentElement.classList.toggle('light', theme === 'light')
    localStorage.setItem('theme', theme)
  }, [theme])

  function toggleTheme() { setTheme(t => t === 'dark' ? 'light' : 'dark') }

  // Fetch categories for sidebar sub-menu (re-fetch on route change)
  useEffect(() => {
    const token = localStorage.getItem('token')
    if (!token) return
    fetch('/api/categories', { headers: { Authorization: `Bearer ${token}` } })
      .then(r => r.ok ? r.json() : [])
      .then(setCats)
      .catch(() => {})
  }, [location.pathname])

  // Close sidebar on navigation (mobile)
  useEffect(() => { setOpen(false) }, [location.pathname])

  // Auto-expand sub-menus when navigating to child routes
  useEffect(() => {
    if (['/settings', '/users', '/categories', '/connection-logs'].some(p => location.pathname.startsWith(p))) {
      setConfigOpen(true)
    }
    if (location.pathname.startsWith('/streams')) {
      setStreamsOpen(true)
    }
  }, [location.pathname])

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

  // Helpers for active state with search params
  const searchParams = new URLSearchParams(location.search)
  const activeCat    = searchParams.get('cat')

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

          {/* Streams — collapsible with category sub-items */}
          <div>
            <div
              className={`nav-group-header${streamsOpen ? ' open' : ''}`}
              onClick={() => setStreamsOpen(o => !o)}
            >
              <span className="nav-group-header-left">
                <FiVideo size={16} /> Streams
              </span>
              <FiChevronRight size={12} className={`nav-group-chevron${streamsOpen ? ' open' : ''}`} />
            </div>
            <div className={`nav-sub${streamsOpen ? ' open' : ''}`}>
              {/* "All streams" — active only when on /streams without ?cat= */}
              <div
                className={`nav-item${location.pathname === '/streams' && !activeCat ? ' active' : ''}`}
                onClick={() => nav('/streams')}
                style={{ cursor: 'pointer' }}
              >
                Todos os Streams
              </div>
              {cats.map(cat => (
                <div
                  key={cat.id}
                  className={`nav-item${activeCat === cat.name ? ' active' : ''}`}
                  onClick={() => nav(`/streams?cat=${encodeURIComponent(cat.name)}`)}
                  style={{ cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
                >
                  {cat.logo_path ? (
                    <img
                      src={`/api/categories/${cat.id}/logo?t=${cat.logo_path}`}
                      alt=""
                      style={{ width: logoSize, height: logoSize, objectFit: 'contain', borderRadius: 3, flexShrink: 0 }}
                    />
                  ) : (
                    <FiTag size={Math.max(12, logoSize - 4)} style={{ flexShrink: 0, color: 'var(--text3)' }} />
                  )}
                  {cat.name}
                </div>
              ))}
            </div>
          </div>

          {user.role === 'admin' && (
            <div>
              <div
                className={`nav-group-header${configOpen ? ' open' : ''}`}
                onClick={() => setConfigOpen(o => !o)}
              >
                <span className="nav-group-header-left">
                  <FiSettings size={16} /> Configurações
                </span>
                <FiChevronRight size={12} className={`nav-group-chevron${configOpen ? ' open' : ''}`} />
              </div>
              <div className={`nav-sub${configOpen ? ' open' : ''}`}>
                <NavLink to="/settings" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <FiSettings size={13} /> Geral
                </NavLink>
                <NavLink to="/categories" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <FiTag size={13} /> Categorias
                </NavLink>
                <NavLink to="/users" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <FiUsers size={13} /> Usuários
                </NavLink>
                <NavLink to="/connection-logs" className={({ isActive }) => `nav-item${isActive ? ' active' : ''}`}>
                  <FiActivity size={13} /> Conexões
                </NavLink>
              </div>
            </div>
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
          <div style={{ display: 'flex', gap: 6 }}>
            <button
              className="theme-toggle"
              onClick={toggleTheme}
              title={theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
            >
              {theme === 'dark' ? <FiSun size={14} /> : <FiMoon size={14} />}
            </button>
            <button className="btn btn-ghost btn-sm" style={{ flex: 1, justifyContent: 'center' }} onClick={logout}>
              <FiLogOut size={13} /> Sair
            </button>
          </div>
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
