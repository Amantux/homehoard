import { describe, it, expect } from 'vitest'
import { escapeHtml, buildPrintHtml } from './html'

const PAYLOAD = '<img src=x onerror=alert(1)>'

describe('escapeHtml', () => {
  it('neutralises markup', () => {
    const out = escapeHtml(PAYLOAD)
    expect(out).not.toContain('<')
    expect(out).toBe('&lt;img src=x onerror=alert(1)&gt;')
  })

  it('escapes quotes and ampersands', () => {
    expect(escapeHtml(`a&b "c" 'd'`)).toBe('a&amp;b &quot;c&quot; &#39;d&#39;')
  })

  it('treats null/undefined as empty', () => {
    expect(escapeHtml(undefined)).toBe('')
    expect(escapeHtml(null)).toBe('')
  })
})

describe('buildPrintHtml', () => {
  const base = { title: 'QR abc', imgSrc: 'blob:http://x/1', heading: 'Drill', caption: 'abc' }

  it('escapes a hostile heading', () => {
    const out = buildPrintHtml({ ...base, heading: PAYLOAD })
    expect(out).not.toContain('<img src=x')
    expect(out).toContain('&lt;img')
  })

  it('escapes a hostile caption and title', () => {
    const out = buildPrintHtml({ ...base, title: '</title><script>x()</script>', caption: PAYLOAD })
    expect(out).not.toContain('<img src=x')
    expect(out).not.toContain('<script>x()')
  })

  it('cannot break out of the img src attribute', () => {
    const out = buildPrintHtml({ ...base, imgSrc: '" onerror="alert(1)' })
    expect(out).not.toContain('" onerror="')
  })

  it('keeps the auto-print script', () => {
    expect(buildPrintHtml(base)).toContain('<script>window.onload=()=>window.print()</script>')
  })
})
