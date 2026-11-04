import { describe, expect, it } from 'vitest'

import { limitLabel, limitValue, MINUS, money, percent } from './format'

describe('money', () => {
  it('formats Australian dollars', () => {
    expect(money('2186.90')).toBe('$2,186.90')
    expect(money(43, { whole: true })).toBe('$43')
  })

  it('always signs gains and losses', () => {
    expect(money('186.9', { sign: true })).toBe('+$186.90')
    expect(money('-12.30')).toBe(`${MINUS}$12.30`)
    expect(money(0, { sign: true })).toBe('$0.00')
  })
})

describe('percent', () => {
  it('uses a real minus sign and optional plus', () => {
    expect(percent(0.031, { sign: true })).toBe('+3.1%')
    expect(percent(-0.024)).toBe(`${MINUS}2.4%`)
    expect(percent(-0.15, { digits: 0 })).toBe(`${MINUS}15%`)
  })

  it('does not show minus zero', () => {
    expect(percent(-0.0001)).toBe('0.0%')
    expect(percent(-0)).toBe('0.0%')
  })
})

describe('limits', () => {
  it('describes each limit in plain words', () => {
    expect(limitLabel('max_stake_fraction')).toBe('Max stake per bet')
    expect(limitValue('max_stake_fraction', '0.020000')).toBe('2% of bankroll')
    expect(limitValue('drawdown_stop_fraction', '0.15')).toBe(`${MINUS}15% from peak pauses alerts`)
    expect(limitValue('kelly_multiplier', '0.25')).toBe('¼ Kelly')
    expect(limitValue('min_odds', '1.5')).toBe('1.50')
    expect(limitValue('approval_window_minutes', '60')).toBe('60 min')
    expect(limitValue('min_edge', '0.035')).toBe('3.5% after margin')
  })
})
