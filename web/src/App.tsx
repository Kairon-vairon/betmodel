import { getOverview } from './api'
import { AuthProvider, useAuth } from './auth'
import { Shell } from './components/Shell'
import { ComingSoonPage } from './pages/ComingSoonPage'
import { DashboardPage } from './pages/DashboardPage'
import { SettingsPage } from './pages/SettingsPage'
import { SignInPage } from './pages/SignInPage'
import { usePath } from './router'
import { useApi } from './useApi'

function SignedInApp() {
  const path = usePath()
  const { data: overview, error } = useApi(getOverview, 60_000)
  let page
  if (path === '/') page = <DashboardPage overview={overview} error={error} />
  else if (path === '/settings') page = <SettingsPage />
  else page = <ComingSoonPage path={path} />
  return <Shell overview={overview}>{page}</Shell>
}

function Gate() {
  const { state } = useAuth()
  if (state.status === 'loading') {
    return (
      <div className="signin" aria-busy="true">
        <span className="dim">Loading…</span>
      </div>
    )
  }
  if (state.status === 'signed-out') return <SignInPage expired={state.expired} />
  return <SignedInApp />
}

export function App() {
  return (
    <AuthProvider>
      <Gate />
    </AuthProvider>
  )
}
