import { useState } from 'react'

import { getLimits } from '../api'
import { useAuth } from '../auth'
import { limitLabel, limitValue } from '../format'
import { useApi } from '../useApi'

const ORDER = [
  'max_stake_fraction',
  'max_daily_exposure_fraction',
  'drawdown_stop_fraction',
  'min_edge',
  'min_odds_edge',
  'min_odds',
  'max_odds',
  'kelly_multiplier',
  'approval_window_minutes',
  'max_bets_per_match',
  'min_stake',
]

export function SettingsPage() {
  const { state, logout } = useAuth()
  const { data, error } = useApi(getLimits)
  const [signingOut, setSigningOut] = useState(false)
  const limits = data ? [...data.limits].sort((a, b) => ORDER.indexOf(a.name) - ORDER.indexOf(b.name)) : []

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Enforced on the server: a bet that breaks a limit is never suggested</div>
          <h1>Settings &amp; limits</h1>
        </div>
      </div>

      <div className="grid two">
        <section className="card" aria-labelledby="limits-title">
          <div>
            <h2 id="limits-title">Safety limits</h2>
            <div className="card-sub">Editing arrives with the full settings screen.</div>
          </div>
          {error && (
            <p className="error" role="alert">
              {error}
            </p>
          )}
          {data && !data.valid && (
            <p className="notice" role="alert">
              The stored limits don't form a valid set, so no bets will be suggested until they're fixed.
            </p>
          )}
          <div className="list">
            {limits.map((limit) => (
              <div className="list-row" key={limit.name}>
                <span>{limitLabel(limit.name)}</span>
                <span className="value" style={{ color: 'var(--text-2)', fontVariantNumeric: 'tabular-nums' }}>
                  {limitValue(limit.name, limit.value)}
                  {limit.changed && <span className="badge" style={{ marginLeft: 8 }}>changed</span>}
                </span>
              </div>
            ))}
          </div>
        </section>

        <div className="grid" style={{ alignContent: 'start' }}>
          <section className="card" aria-labelledby="control-title">
            <h2 id="control-title">Staying in control</h2>
            <p className="muted" style={{ margin: 0 }}>
              Set deposit limits inside each bookmaker account. If betting stops feeling like an experiment, BetStop,
              the national self-exclusion register, covers every licensed Australian bookmaker in one step.
            </p>
            <p style={{ margin: 0 }}>
              <a href="https://www.betstop.gov.au" target="_blank" rel="noreferrer">
                betstop.gov.au
              </a>
              {' · '}Gambling Help Online <a href="tel:1800858858" className="mono">1800 858 858</a>
            </p>
          </section>

          <section className="card" aria-labelledby="account-title">
            <h2 id="account-title">Account</h2>
            <div className="rail-row">
              <span>Signed in as</span>
              <span>{state.status === 'signed-in' ? state.username : ''}</span>
            </div>
            <button
              type="button"
              className="btn"
              disabled={signingOut}
              onClick={() => {
                setSigningOut(true)
                void logout()
              }}
            >
              Sign out
            </button>
          </section>
        </div>
      </div>
    </>
  )
}
