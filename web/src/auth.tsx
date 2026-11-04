import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

import { setUnauthorizedHandler, signIn, signOut, whoAmI } from './api'

type AuthState =
  | { status: 'loading' }
  | { status: 'signed-out'; expired?: boolean }
  | { status: 'signed-in'; username: string }

type AuthContextValue = {
  state: AuthState
  login: (username: string, password: string, code: string) => Promise<void>
  logout: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: 'loading' })

  useEffect(() => {
    let cancelled = false
    whoAmI()
      .then((owner) => !cancelled && setState({ status: 'signed-in', username: owner.username }))
      .catch(() => !cancelled && setState({ status: 'signed-out' }))
    setUnauthorizedHandler(() => setState({ status: 'signed-out', expired: true }))
    return () => {
      cancelled = true
      setUnauthorizedHandler(null)
    }
  }, [])

  const login = useCallback(async (username: string, password: string, code: string) => {
    const owner = await signIn(username, password, code)
    setState({ status: 'signed-in', username: owner.username })
  }, [])

  const logout = useCallback(async () => {
    try {
      await signOut()
    } finally {
      setState({ status: 'signed-out' })
    }
  }, [])

  const value = useMemo(() => ({ state, login, logout }), [state, login, logout])
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext)
  if (!value) throw new Error('useAuth must be used inside AuthProvider')
  return value
}
