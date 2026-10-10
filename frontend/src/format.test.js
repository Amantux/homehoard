import { describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({ api: { get: vi.fn() } }))

const { shortDate, loadCurrency, currencySymbol } = await import('./format')
const { api } = await import('./api')

describe('shortDate', () => {
  it('formats a UTC-midnight timestamp as that calendar day, whatever the zone', () => {
    // Compare against a local-constructed date: the two must agree in every TZ.
    expect(shortDate('2026-07-10T00:00:00+00:00')).toBe(new Date(2026, 6, 10).toLocaleDateString())
  })
  it('formats a bare date the same way', () => {
    expect(shortDate('2026-07-10')).toBe(new Date(2026, 6, 10).toLocaleDateString())
  })
  it('returns a dash for empty values', () => {
    expect(shortDate(null)).toBe('—')
  })
})

describe('loadCurrency', () => {
  it('retries after a failed fetch instead of giving up for the session', async () => {
    api.get.mockReset()
    api.get.mockRejectedValueOnce(new Error('offline'))
    await loadCurrency()
    expect(currencySymbol.value).toBe('$')

    api.get.mockImplementation((path) =>
      Promise.resolve(path === '/groups' ? { currency: 'eur' } : [{ code: 'eur', symbol: '€' }])
    )
    await loadCurrency()
    expect(api.get).toHaveBeenCalledWith('/currency')
    expect(currencySymbol.value).toBe('€')
  })
  it('shares one in-flight fetch between concurrent callers', async () => {
    vi.resetModules()
    const fresh = await import('./format')
    const { api: freshApi } = await import('./api')
    freshApi.get.mockReset()
    freshApi.get.mockImplementation((path) =>
      Promise.resolve(path === '/groups' ? { currency: 'eur' } : [{ code: 'eur', symbol: '€' }])
    )
    await Promise.all([fresh.loadCurrency(), fresh.loadCurrency()])
    expect(freshApi.get).toHaveBeenCalledTimes(2) // one /groups + one /currency
    await fresh.loadCurrency()
    expect(freshApi.get).toHaveBeenCalledTimes(2) // loaded: no refetch
  })
})
