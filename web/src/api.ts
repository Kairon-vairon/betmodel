/** Talking to the Edgewise API. Money and odds arrive as strings (exact decimals). */

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let onUnauthorized: (() => void) | null = null

/** Called when the server says the session has ended (expired or signed out elsewhere). */
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    credentials: 'same-origin',
    ...init,
    headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}), ...init.headers },
  })
  if (!response.ok) {
    let message = 'Something went wrong. Try again.'
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') message = body.detail
    } catch {
      // not JSON: keep the generic message
    }
    if (response.status === 401 && !path.startsWith('/api/auth/login')) onUnauthorized?.()
    throw new ApiError(response.status, message)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

export type Owner = { username: string }

export type FeedState = 'not_configured' | 'waiting' | 'ok' | 'paused'

export type Feed = {
  feed: string
  name: string
  state: FeedState
  last_success_at: string | null
  paused: boolean
  last_error: string | null
  details: Record<string, unknown>
}

export type Notice = { created_at: string; kind: string; title: string; body: string }

export type WorkerStatus = { worker: string; last_beat_at: string; healthy: boolean }

export type Overview = {
  stack: 'live' | 'lab'
  bankroll: string
  peak_bankroll: string
  exposure_today: string
  daily_exposure_limit: string
  max_stake: string
  alerts_paused: boolean
  pause_reasons: string[]
  awaiting_approval: number
  feeds: Feed[]
  notices: Notice[]
  workers: WorkerStatus[]
}

export type Limit = { name: string; value: string; default: string; changed: boolean }
export type Limits = { limits: Limit[]; valid: boolean }

export const signIn = (username: string, password: string, code: string) =>
  api<Owner>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password, code }),
  })

export const signOut = () => api<void>('/api/auth/logout', { method: 'POST' })
export const whoAmI = () => api<Owner>('/api/auth/me')
export const getOverview = () => api<Overview>('/api/overview')
export const getLimits = () => api<Limits>('/api/limits')
