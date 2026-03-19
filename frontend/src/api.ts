import axios from 'axios'

const api = axios.create({ baseURL: '/', timeout: 30000 })

// Attach JWT to every request
api.interceptors.request.use(cfg => {
  const token = localStorage.getItem('token')
  if (token) cfg.headers.Authorization = `Bearer ${token}`
  return cfg
})

// Redirect to login on 401
api.interceptors.response.use(
  r => r,
  err => {
    if (err.response?.status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export default api

export function getHlsUrl(streamId: string) {
  return `/stream/${streamId}/hls/stream.m3u8`
}
