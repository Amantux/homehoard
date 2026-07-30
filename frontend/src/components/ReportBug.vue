<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api } from '../api'
import { recentErrors } from '../utils/errorLog'
import { buildDiagnostics, issueUrl, searchUrl, MAX_BODY, truncate } from '../utils/bugReport'

const REPO = 'Amantux/homehoard'
const APP = 'HomeHoard'
const VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : 'unknown'
// Encoding roughly doubles the byte length; keep the raw URL comfortably under
// the ~8 KB browser/GitHub ceiling before falling back to the clipboard.
const MAX_URL = 6800

const props = defineProps({
  // Optional prefill from the chat bug-report walkthrough: { description?, type? }.
  initial: { type: Object, default: null },
})
const emit = defineEmits(['close'])
const route = useRoute()

const type = ref(props.initial?.type || 'bug') // 'bug' | 'feature'
const title = ref('')
const description = ref(props.initial?.description || '')
const includeDiag = ref(true)
const diagText = ref('')
const loading = ref(true)
const copied = ref(false)
const fallbackUrl = ref('')

const TYPES = [
  { id: 'bug', label: 'Bug' },
  { id: 'feature', label: 'Feature request' },
]

onMounted(async () => {
  let diagnostics = {}
  try {
    diagnostics = await api.get('/diagnostics')
  } catch (e) {
    // Diagnostics are best-effort — the report still works without them.
  }
  diagText.value = buildDiagnostics({
    app: APP,
    version: VERSION,
    diagnostics,
    errors: recentErrors(),
    route: route.fullPath,
  })
  loading.value = false
})

const body = computed(() => {
  const parts = [description.value.trim()]
  if (includeDiag.value && diagText.value.trim()) {
    parts.push('', '---', '<details><summary>Diagnostics</summary>', '',
      truncate(diagText.value.trim(), MAX_BODY), '</details>')
  }
  return parts.join('\n')
})

const url = computed(() => issueUrl({ repo: REPO, type: type.value, title: title.value, body: body.value }))
const canSubmit = computed(() => title.value.trim() && description.value.trim() && !loading.value)

function searchExisting() {
  const q = title.value.trim() || (recentErrors()[0] && recentErrors()[0].message) || ''
  window.open(searchUrl({ repo: REPO, query: q }), '_blank', 'noopener')
}

async function copyReport() {
  // Guard for non-HTTPS Home Assistant ingress, where navigator.clipboard is
  // undefined — the textarea in the fallback card still holds the text either way.
  try {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(body.value)
      copied.value = true
      return
    }
  } catch (e) { /* fall through to the visible textarea */ }
  copied.value = false
}

async function submit() {
  if (!canSubmit.value) return
  copied.value = false
  fallbackUrl.value = ''
  const link = url.value
  if (link.length <= MAX_URL) {
    // Fits: open the prefilled issue and close. window.open() with 'noopener'
    // returns null even on success, so we can't read its return to detect a
    // blocked popup — the browser surfaces its own blocked-popup UI, and a block
    // on a direct user gesture is rare.
    window.open(link, '_blank', 'noopener')
    emit('close')
    return
  }
  // Too long to prefill in a URL: open a blank issue and give the user their report
  // to paste (kept in a textarea below so it's never lost, clipboard or not).
  fallbackUrl.value = issueUrl({ repo: REPO, type: type.value, title: title.value, body: '' })
  await copyReport()
}
</script>

<template>
  <div class="modal-backdrop" @click.self="emit('close')">
    <div class="card modal" style="width:540px;max-width:96vw">
      <div class="modal-head">
        <h2 style="flex:1">🐞 Report a bug</h2>
        <button class="ghost icon-btn" aria-label="Close" @click="emit('close')">✕</button>
      </div>

      <div class="row wrap" role="group" aria-label="Report type" style="gap:6px;margin-bottom:12px">
        <button v-for="t in TYPES" :key="t.id" class="sm" :class="type === t.id ? '' : 'ghost'"
                :aria-pressed="type === t.id" @click="type = t.id">{{ t.label }}</button>
      </div>

      <label class="field">
        <span>Title</span>
        <input v-model="title" maxlength="140"
               :placeholder="type === 'feature' ? 'Short summary of the idea' : 'Short summary of the problem'" />
      </label>

      <label class="field">
        <span>{{ type === 'feature' ? 'What would you like, and why?' : 'What happened? What did you expect?' }}</span>
        <textarea v-model="description" rows="5"
                  placeholder="Steps to reproduce, what you saw, what you expected…"></textarea>
      </label>

      <div class="card" style="padding:10px;background:var(--surface-2)">
        <label class="row" style="gap:8px;align-items:center;cursor:pointer;margin:0">
          <input type="checkbox" v-model="includeDiag" style="width:auto" />
          <span>Include diagnostics</span>
        </label>
        <p class="muted" style="font-size:0.8rem;margin:8px 0 6px">
          This opens a <strong>public</strong> GitHub issue — review and edit the details below;
          remove anything you don't want shared. No API keys, addresses, or your inventory are included.
        </p>
        <textarea v-if="includeDiag" v-model="diagText" rows="7" spellcheck="false"
                  aria-label="Diagnostics to include"
                  style="font-family:var(--mono,monospace);font-size:0.8rem"
                  :disabled="loading"></textarea>
        <p v-if="loading" class="muted" style="font-size:0.8rem;margin:6px 0 0">Gathering diagnostics…</p>
      </div>

      <div v-if="fallbackUrl" class="card" style="padding:10px;margin-top:10px;background:var(--surface-2)">
        <p style="margin:0 0 6px">
          Your report is too long to prefill automatically.
          {{ copied ? "It's on your clipboard — " : 'Copy the text below, then ' }}open a
          new issue and paste it in:
        </p>
        <textarea readonly :value="body" rows="4" @focus="$event.target.select()"
                  style="font-family:var(--mono,monospace);font-size:0.8rem"></textarea>
        <div class="row" style="gap:8px;margin-top:6px;align-items:center">
          <button class="secondary sm" @click="copyReport">{{ copied ? 'Copied ✓' : 'Copy report' }}</button>
          <a :href="fallbackUrl" target="_blank" rel="noopener">Open a new GitHub issue ↗</a>
        </div>
      </div>

      <div class="divider"></div>
      <div class="row" style="gap:8px;align-items:center">
        <button class="ghost sm" @click="searchExisting">🔍 Search existing issues</button>
        <div class="grow"></div>
        <button class="secondary" @click="emit('close')">Cancel</button>
        <button :disabled="!canSubmit" @click="submit">Open GitHub issue ↗</button>
      </div>
    </div>
  </div>
</template>
