import { useState, type FormEvent } from 'react'

import { ApiError } from '../api'
import { useAuth } from '../auth'
import { LogoMark } from '../components/icons'

export function SignInPage({ expired = false }: { expired?: boolean }) {
  const { login } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [code, setCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await login(username, password, code)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not reach Edgewise. Check your connection.')
      setCode('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="signin">
      <form className="card" onSubmit={submit} aria-labelledby="signin-title" style={{ gap: 18, padding: 28 }}>
        <div className="brand" style={{ padding: 0 }}>
          <div className="brand-mark">
            <LogoMark />
          </div>
          <div>
            <h1 id="signin-title" className="brand-name" style={{ margin: 0, fontSize: 20 }}>
              Edgewise
            </h1>
            <div className="brand-sub">Sign in to continue</div>
          </div>
        </div>

        {expired && <p className="notice">You were signed out. Sign in again to continue.</p>}

        <div className="field">
          <label htmlFor="username">Email</label>
          <input
            id="username"
            name="username"
            type="text"
            inputMode="email"
            autoCapitalize="none"
            spellCheck={false}
            autoComplete="username"
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="code">6-digit code from your authenticator app</label>
          <input
            id="code"
            name="code"
            className="code"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9 ]{6,7}"
            maxLength={7}
            required
            value={code}
            onChange={(e) => setCode(e.target.value)}
          />
        </div>

        {error && (
          <p className="error" role="alert">
            {error}
          </p>
        )}

        <button type="submit" className="btn primary" disabled={busy}>
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
        <p className="dim" style={{ margin: 0, fontSize: 13, textAlign: 'center' }}>
          Nothing is ever placed without your approval.
        </p>
      </form>
    </div>
  )
}
