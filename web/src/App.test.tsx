import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { App } from './App'

type Handler = (init?: RequestInit) => { status: number; body?: unknown }

const overview = {
  stack: 'live',
  bankroll: '2186.90',
  peak_bankroll: '2233.40',
  exposure_today: '33.00',
  daily_exposure_limit: '174.95',
  max_stake: '43',
  alerts_paused: false,
  pause_reasons: [],
  awaiting_approval: 1,
  feeds: [
    { feed: 'fixtures', name: 'Fixtures and results (API-Football)', state: 'ok', last_success_at: '2026-11-07T08:58:00Z', paused: false, last_error: null, details: {} },
    { feed: 'odds_feed', name: 'Bookmaker odds (The Odds API)', state: 'not_configured', last_success_at: null, paused: false, last_error: null, details: {} },
    { feed: 'betfair', name: 'Betfair Exchange prices', state: 'paused', last_success_at: null, paused: true, last_error: 'Betfair refused the login', details: {} },
  ],
  notices: [] as { created_at: string; kind: string; title: string; body: string }[],
  workers: [{ worker: 'worker', last_beat_at: '2026-11-07T09:00:00Z', healthy: true }],
}

const limits = {
  valid: true,
  limits: [
    { name: 'max_stake_fraction', value: '0.020000', default: '0.02', changed: false },
    { name: 'min_edge', value: '0.035000', default: '0.03', changed: true },
  ],
}

function mockApi(routes: Record<string, Handler>) {
  const calls: { path: string; init?: RequestInit }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = typeof input === 'string' ? input : input.toString()
      calls.push({ path, init })
      const handler = routes[path]
      const { status, body } = handler ? handler(init) : { status: 404, body: { detail: 'Not found' } }
      return new Response(status === 204 ? null : JSON.stringify(body ?? {}), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  return calls
}

beforeEach(() => {
  vi.unstubAllGlobals()
})

describe('signing in', () => {
  it('shows the sign-in form when there is no session', async () => {
    mockApi({ '/api/auth/me': () => ({ status: 401, body: { detail: 'Please sign in.' } }) })
    render(<App />)
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByText('Nothing is ever placed without your approval.')).toBeInTheDocument()
  })

  it('sends email, password and code, then opens the dashboard', async () => {
    let signedIn = false
    const calls = mockApi({
      '/api/auth/me': () => (signedIn ? { status: 200, body: { username: 'owner@example.com' } } : { status: 401 }),
      '/api/auth/login': () => {
        signedIn = true
        return { status: 200, body: { username: 'owner@example.com' } }
      },
      '/api/overview': () => ({ status: 200, body: overview }),
    })
    render(<App />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Password'), 'a long enough password')
    await user.type(screen.getByLabelText('6-digit code from your authenticator app'), '123456')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    expect(await screen.findByRole('heading', { name: 'Dashboard' })).toBeInTheDocument()
    const login = calls.find((c) => c.path === '/api/auth/login')
    expect(JSON.parse(String(login?.init?.body))).toEqual({
      username: 'owner@example.com',
      password: 'a long enough password',
      code: '123456',
    })
    const bankroll = await screen.findByRole('region', { name: 'Bankroll' })
    expect(within(bankroll).getByText('$2,186.90')).toBeInTheDocument()
    expect(screen.getByText('1 bets')).toBeInTheDocument()
  })

  it('shows the server message when sign-in fails and clears the code', async () => {
    mockApi({
      '/api/auth/me': () => ({ status: 401 }),
      '/api/auth/login': () => ({ status: 401, body: { detail: "That email, password or code isn't right." } }),
    })
    render(<App />)
    const user = userEvent.setup()
    await user.type(await screen.findByLabelText('Email'), 'owner@example.com')
    await user.type(screen.getByLabelText('Password'), 'wrong password')
    const code = screen.getByLabelText('6-digit code from your authenticator app')
    await user.type(code, '000000')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))
    expect(await screen.findByRole('alert')).toHaveTextContent("That email, password or code isn't right.")
    expect(code).toHaveValue('')
  })
})

describe('signed in', () => {
  function signedIn(extra: Record<string, Handler> = {}) {
    return mockApi({
      '/api/auth/me': () => ({ status: 200, body: { username: 'owner@example.com' } }),
      '/api/overview': () => ({ status: 200, body: overview }),
      '/api/limits': () => ({ status: 200, body: limits }),
      '/api/auth/logout': () => ({ status: 204 }),
      ...extra,
    })
  }

  it('navigates to settings and shows limits in plain words', async () => {
    signedIn()
    render(<App />)
    const user = userEvent.setup()
    const nav = await screen.findByRole('navigation', { name: 'Main' })
    await user.click(within(nav).getByRole('link', { name: 'Settings & limits' }))
    expect(await screen.findByRole('heading', { name: 'Settings & limits' })).toBeInTheDocument()
    expect(await screen.findByText('2% of bankroll')).toBeInTheDocument()
    expect(screen.getByText('3.5% after margin')).toBeInTheDocument()
    expect(screen.getByText('changed')).toBeInTheDocument()
    expect(window.location.pathname).toBe('/settings')
    expect(within(nav).getByRole('link', { name: 'Settings & limits' })).toHaveAttribute('aria-current', 'page')
  })

  it('signs out', async () => {
    const calls = signedIn()
    window.history.replaceState(null, '', '/settings')
    render(<App />)
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Sign out' }))
    expect(await screen.findByRole('button', { name: 'Sign in' })).toBeInTheDocument()
    expect(calls.some((c) => c.path === '/api/auth/logout' && c.init?.method === 'POST')).toBe(true)
  })

  it('returns to sign-in when the session expires', async () => {
    let expired = false
    signedIn({
      '/api/overview': () => (expired ? { status: 401 } : { status: 200, body: overview }),
      '/api/limits': () => (expired ? { status: 401 } : { status: 200, body: limits }),
    })
    render(<App />)
    await screen.findByRole('heading', { name: 'Dashboard' })
    expired = true
    const user = userEvent.setup()
    await user.click(within(screen.getByRole('navigation', { name: 'Main' })).getByRole('link', { name: 'Settings & limits' }))
    expect(await screen.findByText('You were signed out. Sign in again to continue.')).toBeInTheDocument()
  })

  it('shows an honest placeholder for pages not built yet', async () => {
    signedIn()
    window.history.replaceState(null, '', '/bet-log')
    render(<App />)
    expect(await screen.findByRole('heading', { name: 'Bet log' })).toBeInTheDocument()
    expect(screen.getByText('Coming soon')).toBeInTheDocument()
  })

  it('shows each data feed and recent notices', async () => {
    signedIn({
      '/api/overview': () => ({
        status: 200,
        body: {
          ...overview,
          notices: [{ created_at: '2026-11-07T08:59:00Z', kind: 'feed_paused', title: 'Betfair Exchange prices has stopped', body: 'Value bets that need it are paused.' }],
        },
      }),
    })
    render(<App />)
    const sidebar = await screen.findByLabelText('Data feeds')
    expect(await within(sidebar).findByText(/Bookmaker odds · not connected/)).toBeInTheDocument()
    expect(within(sidebar).getByText(/Betfair prices · paused/)).toBeInTheDocument()
    const system = screen.getByRole('region', { name: 'System' })
    expect(within(system).getByText('No key yet')).toBeInTheDocument()
    expect(within(system).getByText('Paused')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Recent notices' })).toBeInTheDocument()
    expect(screen.getByText('Betfair Exchange prices has stopped')).toBeInTheDocument()
    expect(screen.getByText('Connect the data feeds to start')).toBeInTheDocument()
  })

  it('warns when alerts are paused', async () => {
    signedIn({
      '/api/overview': () => ({
        status: 200,
        body: { ...overview, alerts_paused: true, pause_reasons: ['drawdown_stop'] },
      }),
    })
    render(<App />)
    expect(await screen.findByRole('status')).toHaveTextContent(
      'Alerts are paused because the bankroll fell 15% from its peak (drawdown stop).',
    )
  })
})
