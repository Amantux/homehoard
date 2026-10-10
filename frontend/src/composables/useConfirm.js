// In-app replacement for window.confirm(): `await confirm({...})` -> boolean.
// Cancel, Esc and backdrop click all resolve false. Rendered by the single
// <ConfirmDialog> mounted in App.vue.
import { useUI } from '../stores/ui'

export function useConfirm() {
  const ui = useUI()
  return ({ title, body, confirmLabel = 'Confirm', cancelLabel = 'Cancel', danger = false } = {}) =>
    ui.requestConfirm({ title, body, confirmLabel, cancelLabel, danger })
}
