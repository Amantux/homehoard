import { describe, it, expect } from 'vitest'
import { hideMarker, finalizeReply } from './bugMarker'

describe('bugMarker', () => {
  it('finalizeReply strips a complete marker and returns the clean summary', () => {
    const r = finalizeReply('Fix the widget\n[[REPORT_BUG]]')
    expect(r.content).toBe('Fix the widget')
    expect(r.summary).toBe('Fix the widget')
  })
  it('finalizeReply leaves a normal reply unchanged with no summary', () => {
    const r = finalizeReply('normal reply')
    expect(r.content).toBe('normal reply')
    expect(r.summary).toBeNull()
  })
  it('hideMarker hides a mid-stream partial marker', () => {
    expect(hideMarker('x [[REPO')).toBe('x')
  })
  it('hideMarker hides a complete marker', () => {
    expect(hideMarker('done [[REPORT_BUG]]')).toBe('done')
  })
  it('hideMarker leaves ordinary text untouched', () => {
    expect(hideMarker('where is my drill')).toBe('where is my drill')
  })
})
