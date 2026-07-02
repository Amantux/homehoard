import { ref } from 'vue'
import { api } from './api'

export const currencySymbol = ref('$')

let loaded = false
export async function loadCurrency() {
  if (loaded) return
  loaded = true
  try {
    const group = await api.get('/groups')
    const currencies = await api.get('/currency')
    const c = currencies.find((x) => x.code === group.currency)
    if (c) currencySymbol.value = c.symbol
  } catch (e) {
    /* ignore */
  }
}

export function money(v) {
  return (
    currencySymbol.value +
    Number(v || 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  )
}

export function shortDate(v) {
  return v ? new Date(v).toLocaleDateString() : '—'
}
