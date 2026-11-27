import { describe, it, expect } from 'vitest'
import { SEVERITY_LABELS, severityLabel } from './severityLabels'

const TOKENS = Object.keys(SEVERITY_LABELS)

describe('severityLabels', () => {
  it('maps every enumerated severity token to a non-empty plain-language label', () => {
    expect(TOKENS.length).toBeGreaterThan(0)
    for (const token of TOKENS) {
      const label = severityLabel(token)
      expect(typeof label).toBe('string')
      expect(label.trim().length).toBeGreaterThan(0)
    }
  })

  it('maps the core attention-digest / report tokens to their plain-language label', () => {
    expect(severityLabel('overdue')).toBe('Overdue')
    expect(severityLabel('low')).toBe('Low')
    expect(severityLabel('missing price')).toBe('Missing price')
    expect(severityLabel('needs attention')).toBe('Needs attention')
    expect(severityLabel('expiring soon')).toBe('Expiring soon')
    expect(severityLabel('missing fields')).toBe('Missing fields')
  })

  it('maps warranty status tokens', () => {
    expect(severityLabel('lifetime')).toBe('Lifetime')
    expect(severityLabel('active')).toBe('Active')
    expect(severityLabel('expiring')).toBe('Expiring soon')
    expect(severityLabel('expired')).toBe('Expired')
    expect(severityLabel('none')).toBe('None')
  })

  it('normalizes case, separators and camelCase when looking tokens up', () => {
    expect(severityLabel('OVERDUE')).toBe('Overdue')
    expect(severityLabel('Expiring_Soon')).toBe('Expiring soon')
    expect(severityLabel('needsAttention')).toBe('Needs attention')
    expect(severityLabel('Maintenance Overdue')).toBe('Overdue')
  })

  it('falls back to a capitalized form of unknown tokens', () => {
    expect(severityLabel('banana')).toBe('Banana')
    expect(severityLabel('totallyUnknown')).toBe('Totally Unknown')
  })

  it('returns an empty string for an empty token', () => {
    expect(severityLabel('')).toBe('')
    expect(severityLabel(null)).toBe('')
  })
})
