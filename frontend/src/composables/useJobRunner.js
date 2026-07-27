import { ref, computed } from 'vue'
import { api } from '../api'

// Enqueue a background job of `kind` and poll its progress. `onDone(job)` fires
// once the job reaches done/error (or polling gives up). Resumes an already-running
// job of this kind on mount via resume().
export function useJobRunner(kind, { onDone } = {}) {
  const job = ref(null)
  const starting = ref(false)
  let timer = null
  let fails = 0
  const active = computed(() =>
    job.value && ['pending', 'running'].includes(job.value.status))

  async function start(body = {}) {
    if (starting.value || active.value) return
    starting.value = true
    try {
      job.value = await api.post(`/jobs/${kind}`, body)
      poll()
    } finally {
      starting.value = false
    }
  }

  async function poll() {
    if (!job.value) return
    const id = job.value.id
    try {
      job.value = await api.get(`/jobs/${id}`)
      fails = 0
      if (['done', 'error'].includes(job.value.status)) { onDone?.(job.value); return }
    } catch (e) {
      if (++fails >= 5) { job.value = null; onDone?.({ status: 'error', error: 'Lost track of the job.' }); return }
    }
    timer = setTimeout(poll, 1500)
  }

  async function resume() {
    try {
      const r = await api.get(`/jobs?kind=${kind}`)
      const a = (r.items || []).find(j => ['pending', 'running'].includes(j.status))
      if (a) { job.value = a; poll() }
    } catch (e) { /* optional */ }
  }

  function stop() { clearTimeout(timer) }

  return { job, starting, active, start, resume, stop }
}
