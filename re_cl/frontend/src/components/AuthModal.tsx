import { useState } from 'react'
import { X } from 'lucide-react'
import { authLogin, authRegister, authMe } from '../api'
import { useAppStore } from '../store'

type Mode = 'login' | 'register'

export function AuthModal() {
  const { authModalOpen, setAuthModalOpen, setAuth } = useAppStore()
  const [mode, setMode] = useState<Mode>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  if (!authModalOpen) return null

  const reset = () => {
    setEmail('')
    setPassword('')
    setError(null)
    setLoading(false)
  }

  const close = () => {
    reset()
    setAuthModalOpen(false)
  }

  const switchMode = (m: Mode) => {
    setMode(m)
    setError(null)
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    setError(null)

    const result = mode === 'login'
      ? await authLogin(email, password)
      : await authRegister(email, password)

    if (!result.ok) {
      setError(result.error)
      setLoading(false)
      return
    }

    try {
      const user = await authMe(result.token.access_token)
      setAuth(result.token.access_token, user)
      reset()
    } catch {
      setError('No se pudo obtener el perfil de usuario')
      setLoading(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="bg-gray-900 border border-gray-700 rounded-xl shadow-2xl w-full max-w-sm mx-4">
        {/* Header */}
        <div className="flex items-center justify-between px-5 pt-5 pb-3 border-b border-gray-800">
          <div className="flex gap-3">
            <button
              onClick={() => switchMode('login')}
              className={`text-sm font-medium pb-1 border-b-2 transition-colors ${
                mode === 'login'
                  ? 'border-blue-500 text-white'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              Iniciar sesión
            </button>
            <button
              onClick={() => switchMode('register')}
              className={`text-sm font-medium pb-1 border-b-2 transition-colors ${
                mode === 'register'
                  ? 'border-blue-500 text-white'
                  : 'border-transparent text-gray-500 hover:text-gray-300'
              }`}
            >
              Registrarse
            </button>
          </div>
          <button onClick={close} className="text-gray-500 hover:text-white">
            <X size={18} />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex flex-col gap-4 px-5 py-5">
          <div>
            <label className="block text-xs text-gray-400 mb-1">Email</label>
            <input
              type="email"
              required
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="usuario@ejemplo.com"
              className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-600 text-gray-200 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-400 mb-1">
              Contraseña {mode === 'register' && <span className="text-gray-500">(mín. 8 caracteres)</span>}
            </label>
            <input
              type="password"
              required
              minLength={mode === 'register' ? 8 : 1}
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              className="w-full px-3 py-2 rounded bg-gray-800 border border-gray-600 text-gray-200 text-sm focus:border-blue-500 focus:outline-none"
            />
          </div>

          {error && (
            <p className="text-red-400 text-xs bg-red-900/20 border border-red-800 rounded px-3 py-2">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 rounded bg-blue-600 text-white text-sm font-medium hover:bg-blue-500 disabled:opacity-50 transition-colors"
          >
            {loading
              ? 'Procesando...'
              : mode === 'login' ? 'Entrar' : 'Crear cuenta'}
          </button>
        </form>
      </div>
    </div>
  )
}
