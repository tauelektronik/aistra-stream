import { Routes, Route, Navigate } from 'react-router-dom'
import Login   from './pages/Login'
import Layout  from './pages/Layout'
import Streams from './pages/Streams'
import Users   from './pages/Users'

function RequireAuth({ children }: { children: JSX.Element }) {
  return localStorage.getItem('token') ? children : <Navigate to="/login" replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<Navigate to="/streams" replace />} />
        <Route path="streams" element={<Streams />} />
        <Route path="users"   element={<Users />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
