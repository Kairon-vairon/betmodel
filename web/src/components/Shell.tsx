import type { ReactNode } from 'react'

import type { Feed, Overview } from '../api'
import { sydneyTime } from '../format'
import { Link } from '../router'
import {
  ChartIcon,
  DashboardIcon,
  FlaskIcon,
  ListIcon,
  LogoMark,
  SlidersIcon,
  SparkleIcon,
  TargetIcon,
} from './icons'

export const NAV = [
  { to: '/', label: 'Dashboard', icon: DashboardIcon },
  { to: '/value-bets', label: 'Value bets', icon: TargetIcon },
  { to: '/bet-log', label: 'Bet log', icon: ListIcon },
  { to: '/performance', label: 'Model & performance', icon: ChartIcon },
  { to: '/settings', label: 'Settings & limits', icon: SlidersIcon },
] as const

export const CLAUDE_NAV = [
  { to: '/analyst', label: 'Claude analyst', icon: SparkleIcon },
  { to: '/lab', label: 'Lab & releases', icon: FlaskIcon },
] as const

const TABS = [
  { to: '/', label: 'Today', icon: TargetIcon },
  { to: '/bet-log', label: 'Bet log', icon: ListIcon },
  { to: '/performance', label: 'Stats', icon: ChartIcon },
  { to: '/settings', label: 'Limits', icon: SlidersIcon },
] as const

export const FEED_NAMES: Record<string, string> = {
  fixtures: 'Fixtures & results',
  odds_feed: 'Bookmaker odds',
  betfair: 'Betfair prices',
}

export function feedStateText(feed: Feed): string {
  if (feed.state === 'not_configured') return 'not connected'
  if (feed.state === 'waiting') return 'starting'
  if (feed.state === 'paused') return 'paused'
  return feed.last_success_at ? sydneyTime(feed.last_success_at) : 'running'
}

export function feedDot(feed: Feed): string {
  return feed.state === 'ok' ? 'ok' : feed.state === 'paused' ? 'warn' : ''
}

function Brand() {
  return (
    <div className="brand">
      <div className="brand-mark">
        <LogoMark />
      </div>
      <div>
        <div className="brand-name">Edgewise</div>
        <div className="brand-sub">Value finder · Phase 1</div>
      </div>
    </div>
  )
}

function FeedsBox({ overview }: { overview: Overview | null }) {
  const feeds = overview?.feeds ?? []
  return (
    <div className="feeds-box" aria-label="Data feeds">
      <span className="label">Data feeds</span>
      {feeds.length === 0 ? (
        <div className="feed-row">
          <span className="dot" />
          Not connected yet
        </div>
      ) : (
        feeds.map((feed) => (
          <div className="feed-row" key={feed.feed}>
            <span className={`dot ${feedDot(feed)}`} />
            {FEED_NAMES[feed.feed] ?? feed.name} · {feedStateText(feed)}
          </div>
        ))
      )}
      <div className="dim" style={{ borderTop: '1px solid var(--divider)', paddingTop: 10 }}>
        Placement: <span style={{ color: 'var(--text-2)' }}>manual at bookmaker</span>
      </div>
    </div>
  )
}

export function Shell({ overview, children }: { overview: Overview | null; children: ReactNode }) {
  return (
    <div className="shell">
      <nav className="sidebar" aria-label="Main">
        <Brand />
        <div className="nav-list">
          {NAV.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className="nav-link">
              <Icon />
              {label}
            </Link>
          ))}
          <span className="nav-heading">Claude</span>
          {CLAUDE_NAV.map(({ to, label, icon: Icon }) => (
            <Link key={to} to={to} className="nav-link">
              <Icon />
              {label}
            </Link>
          ))}
        </div>
        <FeedsBox overview={overview} />
      </nav>

      <header className="phone-header">
        <Brand />
      </header>

      <main className="main">{children}</main>

      <nav className="tabbar" aria-label="Tabs">
        {TABS.map(({ to, label, icon: Icon }) => (
          <Link key={to} to={to} className="tab">
            <Icon size={20} />
            {label}
          </Link>
        ))}
      </nav>
    </div>
  )
}
