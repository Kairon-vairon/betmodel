/** Numbers for people: money in AUD, signed percentages with a real minus sign. */

export const MINUS = '−'

const dollars = new Intl.NumberFormat('en-AU', {
  style: 'currency',
  currency: 'AUD',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

const wholeDollars = new Intl.NumberFormat('en-AU', {
  style: 'currency',
  currency: 'AUD',
  currencyDisplay: 'narrowSymbol',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
})

export function money(value: string | number, options: { sign?: boolean; whole?: boolean } = {}): string {
  const n = Number(value)
  const text = (options.whole ? wholeDollars : dollars).format(Math.abs(n))
  if (n < 0) return `${MINUS}${text}`
  if (options.sign && n > 0) return `+${text}`
  return text
}

export function percent(fraction: string | number, options: { sign?: boolean; digits?: number } = {}): string {
  const n = Number(fraction) * 100
  const digits = options.digits ?? 1
  const text = `${Math.abs(n).toFixed(digits)}%`
  if (n < 0 && Math.abs(n) >= 0.5 * 10 ** -digits) return `${MINUS}${text}`
  if (options.sign && n > 0) return `+${text}`
  return text
}

/** Drop trailing zeros: "0.020000" -> "2" percent, "1.50" -> "1.50" for odds. */
function trimPercent(fraction: string): string {
  return String(Number((Number(fraction) * 100).toFixed(2)))
}

const LIMIT_TEXT: Record<string, { label: string; show: (v: string) => string }> = {
  max_stake_fraction: { label: 'Max stake per bet', show: (v) => `${trimPercent(v)}% of bankroll` },
  max_daily_exposure_fraction: {
    label: 'Max daily exposure',
    show: (v) => `${trimPercent(v)}% of bankroll (placed + waiting)`,
  },
  drawdown_stop_fraction: {
    label: 'Drawdown stop',
    show: (v) => `${MINUS}${trimPercent(v)}% from peak pauses alerts`,
  },
  min_edge: { label: 'Minimum edge', show: (v) => `${trimPercent(v)}% after margin` },
  min_odds_edge: { label: "Don't take below", show: (v) => `the price where edge falls to ${trimPercent(v)}%` },
  min_odds: { label: 'Lowest odds', show: (v) => Number(v).toFixed(2) },
  max_odds: { label: 'Highest odds', show: (v) => Number(v).toFixed(2) },
  kelly_multiplier: {
    label: 'Stake size',
    show: (v) => (Number(v) === 0.25 ? '¼ Kelly' : `${Number(v)} × Kelly`),
  },
  min_stake: { label: 'Smallest stake', show: (v) => money(v, { whole: true }) },
  approval_window_minutes: { label: 'Approval window', show: (v) => `${Number(v)} min` },
  max_bets_per_match: {
    label: 'Bets per match',
    show: (v) => `${Number(v)} unless you allow more`,
  },
}

export function limitLabel(name: string): string {
  return LIMIT_TEXT[name]?.label ?? name
}

export function limitValue(name: string, value: string): string {
  return LIMIT_TEXT[name]?.show(value) ?? value
}

export function sydneyDate(at: Date): string {
  return new Intl.DateTimeFormat('en-AU', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    timeZone: 'Australia/Sydney',
  }).format(at)
}

export function sydneyTime(at: string | Date): string {
  return new Intl.DateTimeFormat('en-AU', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZone: 'Australia/Sydney',
  }).format(typeof at === 'string' ? new Date(at) : at)
}
