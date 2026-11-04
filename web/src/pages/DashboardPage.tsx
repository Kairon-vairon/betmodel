import type { Overview } from '../api'
import { WarningIcon } from '../components/icons'
import { FEED_NAMES } from '../components/Shell'
import { money, percent, sydneyDate, sydneyTime } from '../format'
import { Link } from '../router'

const MILESTONES = [
  { name: 'Foundations', detail: 'Server, database, sign-in with 2FA, this app', state: 'Built' },
  { name: 'Data ingestion', detail: 'Fixtures, odds, Betfair prices, results: needs your keys', state: 'Built' },
  { name: 'Value finder', detail: 'Fair prices, edge, ¼ Kelly stake, every safety limit', state: 'Built' },
  { name: 'Alerts and approval', detail: 'Push and Telegram, Placed / Skip in seconds', state: 'Next' },
  { name: 'Bet log and settlement', detail: 'Auto-grading, CLV, bankroll ledger', state: 'Core built' },
  { name: 'Web app screens', detail: 'Value bets, bet log, settings from the design', state: 'Started' },
] as const

const PAUSE_TEXT: Record<string, string> = {
  drawdown_stop: 'the bankroll fell 15% from its peak (drawdown stop)',
  owner: 'you paused them',
}

function ratio(part: string, whole: string): number {
  const w = Number(whole)
  return w > 0 ? Math.min(1, Math.max(0, Number(part) / w)) : 0
}

function SafetyRails({ overview }: { overview: Overview }) {
  const drawdown = Number(overview.peak_bankroll) > 0 ? 1 - Number(overview.bankroll) / Number(overview.peak_bankroll) : 0
  return (
    <section className="card" aria-labelledby="rails-title">
      <div className="card-head">
        <h2 id="rails-title">Safety rails</h2>
        <Link to="/settings">Limits</Link>
      </div>
      <div className="rail">
        <div className="rail-row">
          <span>Daily exposure</span>
          <span className="mono">
            {money(overview.exposure_today, { whole: true })} / {money(overview.daily_exposure_limit, { whole: true })}
          </span>
        </div>
        <div className="bar" role="meter" aria-label="Daily exposure used" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(ratio(overview.exposure_today, overview.daily_exposure_limit) * 100)}>
          <span style={{ width: `${ratio(overview.exposure_today, overview.daily_exposure_limit) * 100}%` }} />
        </div>
      </div>
      <div className="rail-row">
        <span>Max stake per bet</span>
        <span className="mono">{money(overview.max_stake, { whole: true })}</span>
      </div>
      <div className="rail">
        <div className="rail-row">
          <span>Drawdown from peak</span>
          <span className="mono">
            {percent(-drawdown)} / {percent(-0.15, { digits: 0 })}
          </span>
        </div>
        <div className="bar drawdown" role="meter" aria-label="Drawdown towards the stop" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round((drawdown / 0.15) * 100)}>
          <span style={{ width: `${Math.min(1, drawdown / 0.15) * 100}%` }} />
        </div>
      </div>
    </section>
  )
}

export function DashboardPage({ overview, error }: { overview: Overview | null; error: string | null }) {
  const worker = overview?.workers[0]
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">{sydneyDate(new Date())} · Top 5 European leagues</div>
          <h1>Dashboard</h1>
        </div>
      </div>

      {error && !overview && (
        <p className="notice" role="alert">
          <WarningIcon /> Couldn't load the latest figures: {error}
        </p>
      )}

      {overview?.stack === 'lab' && (
        <p className="notice lab">
          This is the lab version. It works on a read-only copy of your data and can't send alerts or place bets.
        </p>
      )}

      {overview?.alerts_paused && (
        <p className="notice" role="status">
          <WarningIcon /> Alerts are paused because{' '}
          {overview.pause_reasons.map((r) => PAUSE_TEXT[r] ?? r).join(' and ')}. No bets will be suggested until you
          resume them.
        </p>
      )}

      <div className="grid stats">
        <section className="card" aria-label="Bankroll">
          <span className="label">Bankroll</span>
          <span className="stat-value">{overview ? money(overview.bankroll) : '—'}</span>
          <span className="stat-note">
            {overview && Number(overview.bankroll) === 0 ? 'Record your starting bankroll on the server' : 'Settled balance'}
          </span>
        </section>
        <section className="card" aria-label="Return on investment">
          <span className="label">ROI</span>
          <span className="stat-value dim">—</span>
          <span className="stat-note">No settled bets yet</span>
        </section>
        <section className="card" aria-label="Closing line value">
          <span className="label">Closing line value</span>
          <span className="stat-value dim">—</span>
          <span className="stat-note">Measured once bets settle</span>
        </section>
        <section className="card" aria-label="Awaiting approval">
          <span className="label">Awaiting approval</span>
          <span className="stat-value">{overview ? `${overview.awaiting_approval} bets` : '—'}</span>
          <span className="stat-note">
            {overview?.feeds.some((f) => f.state === 'not_configured')
              ? 'Connect the data feeds to start'
              : 'Checked every minute'}
          </span>
        </section>
      </div>

      <div className="grid two">
        <section className="card" aria-labelledby="progress-title">
          <div>
            <h2 id="progress-title">Phase 1 progress</h2>
            <div className="card-sub">Bookmaker value finder, manual placement</div>
          </div>
          <div className="list">
            {MILESTONES.map((m, i) => (
              <div className="list-row" key={m.name}>
                <div>
                  <div>
                    M{i + 1} · {m.name}
                  </div>
                  <div className="dim" style={{ fontSize: 13 }}>
                    {m.detail}
                  </div>
                </div>
                <span className={`badge ${m.state === 'Built' ? 'done' : ''}`}>{m.state}</span>
              </div>
            ))}
          </div>
        </section>

        <div className="grid" style={{ alignContent: 'start' }}>
          {overview && <SafetyRails overview={overview} />}
          {overview && overview.notices.length > 0 && (
            <section className="card" aria-labelledby="notices-title">
              <h2 id="notices-title">Recent notices</h2>
              <div className="list">
                {overview.notices.map((notice) => (
                  <div className="list-row" key={`${notice.created_at}-${notice.title}`} style={{ alignItems: 'flex-start' }}>
                    <div>
                      <div>{notice.title}</div>
                      <div className="dim" style={{ fontSize: 13 }}>
                        {notice.body}
                      </div>
                    </div>
                    <span className="value dim mono" style={{ fontSize: 12 }}>
                      {sydneyTime(notice.created_at)}
                    </span>
                  </div>
                ))}
              </div>
            </section>
          )}
          <section className="card" aria-labelledby="system-title">
            <h2 id="system-title">System</h2>
            <div className="list">
              <div className="list-row">
                <span>Background worker</span>
                <span className="value">
                  {worker ? (
                    <span className={worker.healthy ? 'accent' : 'negative'}>
                      {worker.healthy ? 'Running' : 'Not responding'} · {sydneyTime(worker.last_beat_at)}
                    </span>
                  ) : (
                    <span className="dim">Not started</span>
                  )}
                </span>
              </div>
              {(overview?.feeds ?? []).map((feed) => (
                <div className="list-row" key={feed.feed}>
                  <span>{FEED_NAMES[feed.feed] ?? feed.name}</span>
                  <span className={`value ${feed.state === 'ok' ? 'accent' : feed.state === 'paused' ? 'negative' : 'dim'}`}>
                    {feed.state === 'ok' && feed.last_success_at ? `Updated ${sydneyTime(feed.last_success_at)}` : null}
                    {feed.state === 'paused' ? 'Paused' : null}
                    {feed.state === 'waiting' ? 'Starting' : null}
                    {feed.state === 'not_configured' ? 'No key yet' : null}
                  </span>
                </div>
              ))}
              <div className="list-row">
                <span>Bet placement</span>
                <span className="value dim">Manual, by you, at the bookmaker</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </>
  )
}
