// @vitest-environment happy-dom
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { mount, flushPromises } from '@vue/test-utils'
import { parse } from 'vue/compiler-sfc'
import { setActivePinia, createPinia } from 'pinia'
import { LABEL_LAYOUT } from '../storageKeys'
import { useUI } from '../stores/ui'

// Shapes follow GET /qr-tags: `target` is the tagged thing's summary, and only
// an item's summary carries `assetId` ("000-000" when it has none).
const TAGS = [
  { id: 't-drill', kind: 'item', source: 'generated', token: 'tok-drill', description: '',
    target: { id: 'i1', name: 'Cordless drill', assetId: '000-007' } },
  { id: 't-screws', kind: 'item', source: 'generated', token: 'tok-screws', description: '',
    target: { id: 'i2', name: 'Loose screws', assetId: '000-000' } },
  { id: 't-bin', kind: 'bin', source: 'generated', token: 'tok-bin', description: '',
    target: { id: 'b1', name: 'Garage bin' } },
  { id: 't-shed', kind: 'location', source: 'generated', token: 'tok-shed', description: '',
    target: { id: 'l1', name: 'Shed' } },
  // The user's own pre-printed code: nothing to print, so it is never offered.
  { id: 't-own', kind: 'item', source: 'external', token: 'tok-own', description: '',
    target: { id: 'i3', name: 'Own label', assetId: '000-009' } },
]

vi.mock('../api', () => ({
  api: { get: vi.fn(async () => TAGS.map((t) => ({ ...t }))) },
  apiUrl: (path) => `/api/v1${path}`,
  getToken: () => null,
}))

const { api } = await import('../api')
const LabelSheet = (await import('./LabelSheet.vue')).default

// happy-dom swaps in its own URL class, which node:fs rejects; go through a path.
const SRC = join(dirname(fileURLToPath(import.meta.url)), '..')
const readSrc = (file) => readFileSync(join(SRC, file), 'utf8')

// The variables the stylesheet reads. Setting them is the component's job; the
// contract tests below check the stylesheet actually consumes them.
const SHEET_VARS = ['--print-cols', '--cell-w', '--cell-h', '--qr-size', '--gutter']

const LAYOUT_VARS = {
  'address-3up': { '--print-cols': '3', '--cell-w': '63.5mm', '--cell-h': '38.1mm', '--qr-size': '30mm', '--gutter': '2.5mm' },
  'small-4up': { '--print-cols': '4', '--cell-w': '50.8mm', '--cell-h': '25.4mm', '--qr-size': '20mm', '--gutter': '2mm' },
  'large-2up': { '--print-cols': '2', '--cell-w': '101.6mm', '--cell-h': '50.8mm', '--qr-size': '40mm', '--gutter': '2.5mm' },
}

let wrapper

async function mountSheet() {
  const pinia = createPinia()
  setActivePinia(pinia)
  wrapper = mount(LabelSheet, { global: { plugins: [pinia] }, attachTo: document.body })
  await flushPromises()
  return wrapper
}

const radio = (id) => wrapper.find(`input[type="radio"][value="${id}"]`)
const tagRow = (name) => wrapper.findAll('label').find((l) => l.text().includes(name))
const sheet = () => wrapper.find('.label-sheet')
const cell = (name) => wrapper.findAll('.label-cell').find((c) => c.find('.label-name').text().includes(name))
const printButton = () => wrapper.findAll('button').find((b) => /Print sheet|Preparing/.test(b.text()))
const sheetVars = () =>
  Object.fromEntries(SHEET_VARS.map((v) => [v, sheet().element.style.getPropertyValue(v)]))

// The contract tests read stylesheets as written. happy-dom's own parser rewrites
// shorthands (`padding: 0` becomes four longhands) and drops at-rules it does not
// know (@page), so this is a small reader instead: comments stripped, nested
// at-rules flattened, each rule tagged with the media text it sits under
// (null at top level). Tests that assert something is ABSENT must also assert
// the surrounding rule was found, or a parse that finds nothing passes them all.
function splitDeclarations(body) {
  const parts = []
  let depth = 0
  let start = 0
  for (let k = 0; k < body.length; k++) {
    if (body[k] === '(') depth++
    else if (body[k] === ')') depth--
    else if (body[k] === ';' && depth === 0) {
      parts.push(body.slice(start, k))
      start = k + 1
    }
  }
  parts.push(body.slice(start))
  const out = {}
  for (const part of parts) {
    const colon = part.indexOf(':')
    if (colon > 0) out[part.slice(0, colon).trim()] = part.slice(colon + 1).trim()
  }
  return out
}
function parseCss(source) {
  const text = source.replace(/\/\*[\s\S]*?\*\//g, '')
  let i = 0
  const readBlock = (media) => {
    const rules = []
    while (i < text.length) {
      const open = text.indexOf('{', i)
      const close = text.indexOf('}', i)
      if (close !== -1 && (open === -1 || close < open)) {
        i = close + 1
        return rules
      }
      if (open === -1) break
      const prelude = text.slice(i, open).trim()
      i = open + 1
      if (prelude.startsWith('@') && !/^@(page|font-face)\b/.test(prelude)) {
        // @media / @supports / @keyframes: a block of rules
        rules.push(...readBlock(prelude.replace(/^@media\s*/, '')))
      } else {
        const end = text.indexOf('}', i)
        rules.push({
          media,
          selectors: prelude.split(',').map((x) => x.trim()),
          decls: splitDeclarations(text.slice(i, end)),
        })
        i = end + 1
      }
    }
    return rules
  }
  return readBlock(null)
}
const inMedia = (rules, media) => rules.filter((r) => r.media === media)
// Every declaration of every rule whose selector list names `selector`, merged.
const declsOf = (rules, selector) =>
  Object.assign({}, ...rules.filter((r) => r.selectors.includes(selector)).map((r) => r.decls))

// Image requests: success, an HTTP error, a dropped connection.
const pngOk = () => ({ ok: true, blob: async () => new Blob(['png']) })
const http500 = () => ({ ok: false, status: 500, blob: async () => new Blob([]) })
const stubFetch = (handler) => vi.stubGlobal('fetch', vi.fn(async (url) => handler(String(url))))
const fetchedImages = (id) => fetch.mock.calls.filter(([url]) => String(url).includes(`/qr-tags/${id}/image`)).length

// The "Select all" / "Deselect all" button of a group, found by the group's heading.
const groupButton = (heading) =>
  wrapper.findAll('h2').find((h) => h.text().startsWith(heading)).element.parentElement.querySelector('button')
const button = (label) => wrapper.findAll('button').find((b) => b.text() === label)
// Every top-level node the view renders: what a printer would be handed. (The view
// has several roots, so VTU's wrapper.element is the mount container itself.)
const roots = () => [...document.body.querySelector('[data-v-app]').children]

async function pick(...names) {
  for (const n of names) await tagRow(n).find('input').setValue(true)
  await flushPromises()
}
async function useLayout(id) {
  await radio(id).setValue(true)
}

beforeEach(() => {
  localStorage.clear()
  api.get.mockClear()
  // Selecting a tag fetches its QR image; hand back a tiny blob for each.
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, blob: async () => new Blob(['png']) })))
  URL.createObjectURL = vi.fn((_blob) => 'blob:test-qr')
  window.print = vi.fn()
})
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
})

describe('LabelSheet layout', () => {
  it('starts on the 3-up address layout and lists only printable codes', async () => {
    await mountSheet()

    expect(api.get).toHaveBeenCalledWith('/qr-tags')
    expect(radio('address-3up').element.checked).toBe(true)
    expect(radio('small-4up').element.checked).toBe(false)
    expect(radio('large-2up').element.checked).toBe(false)
    expect(wrapper.find('.layout-summary').text()).toMatch(/63\.5×38\.1\s*mm per label,\s*3 across/)

    // Generated codes only: the user's own external label has nothing to print.
    expect(tagRow('Cordless drill')).toBeTruthy()
    expect(tagRow('Garage bin')).toBeTruthy()
    expect(tagRow('Own label')).toBeUndefined()

    await pick('Cordless drill')
    expect(sheetVars()).toEqual(LAYOUT_VARS['address-3up'])
  })

  it('switching layout rewrites the sheet CSS variables and the summary', async () => {
    await mountSheet()
    await pick('Cordless drill')

    await useLayout('small-4up')
    expect(sheetVars()).toEqual(LAYOUT_VARS['small-4up'])
    expect(wrapper.find('.layout-summary').text()).toMatch(/50\.8×25\.4\s*mm per label,\s*4 across/)

    await useLayout('large-2up')
    expect(sheetVars()).toEqual(LAYOUT_VARS['large-2up'])
    expect(wrapper.find('.layout-summary').text()).toMatch(/101\.6×50\.8\s*mm per label,\s*2 across/)

    await useLayout('address-3up')
    expect(sheetVars()).toEqual(LAYOUT_VARS['address-3up'])
  })

  it('offers the layouts as one named radio group', async () => {
    await mountSheet()

    expect(wrapper.find('fieldset legend').text()).toBe('Label sheet layout')
    expect(wrapper.findAll('fieldset input[type="radio"]')).toHaveLength(3)
  })

  it('has no inline sizes on the cells: the stylesheet is the only source', async () => {
    await mountSheet()
    await pick('Cordless drill')

    const c = cell('Cordless drill')
    expect(c.attributes('style') ?? '').toBe('')
    expect(c.find('.label-qr').attributes('style') ?? '').toBe('')
  })
})

describe('LabelSheet stylesheet contract', () => {
  // happy-dom does not apply component CSS, so the unit tests above can only see
  // the variables being SET. What broke on main was the READ side: the <style>
  // block read names nothing ever set (v-bind() of a name that is not a script
  // binding compiles to NaN and "undefinedmm"), the grid declaration was dropped,
  // and every layout printed as a single column. Pin that side too.
  const { descriptor } = parse(readSrc('views/LabelSheet.vue'))
  const css = descriptor.styles.map((s) => s.content).join('\n')
  const rules = parseCss(css)
  const screen = inMedia(rules, null)
  const print = inMedia(rules, 'print')

  it('reads the stylesheet it is about to judge', () => {
    // The absence tests below pass on an empty parse; this is what stops that.
    const sample = parseCss(`
      /* braces in a comment must not open a rule: .x { display: none } */
      @page { margin: 0; }
      @keyframes spin { to { opacity: 0; } }
      .a, .b { display: grid; gap: calc(1mm + 2px); }
      @media print { .a { color: #000; } }
    `)
    expect(declsOf(sample, '.x')).toEqual({})
    expect(declsOf(sample, '@page')).toEqual({ margin: '0' })
    expect(declsOf(inMedia(sample, null), '.b')).toEqual({ display: 'grid', gap: 'calc(1mm + 2px)' })
    expect(declsOf(inMedia(sample, 'print'), '.a')).toEqual({ color: '#000' })

    expect(screen.length).toBeGreaterThan(8)
    expect(print.length).toBeGreaterThan(1)
    expect(inMedia(parseCss(readSrc('style.css')), 'print').length).toBeGreaterThan(2)
  })

  it('uses no v-bind() in the stylesheet', () => {
    // descriptor.cssVars is the compiler's own list of v-bind() expressions.
    expect(descriptor.cssVars).toEqual([])
  })

  it('reads every variable the component sets, in the declarations that size the sheet', () => {
    const sheetRule = declsOf(screen, '.label-sheet')
    // `grid-template-columns` alone is not a grid: without `display: grid` it is
    // ignored and every layout prints as one column, which is the bug that shipped.
    expect(sheetRule.display).toBe('grid')
    expect(sheetRule['grid-template-columns']).toMatch(
      /^repeat\(\s*var\(--print-cols\)\s*,\s*var\(--cell-w\)\s*\)$/,
    )
    expect(sheetRule['column-gap']).toBe('var(--gutter)')
    expect(declsOf(screen, '.label-cell').width).toBe('var(--cell-w)')
    expect(declsOf(screen, '.label-cell').height).toBe('var(--cell-h)')
    expect(declsOf(screen, '.label-qr').width).toBe('var(--qr-size)')
    expect(declsOf(screen, '.label-qr').height).toBe('var(--qr-size)')
  })

  it('keeps every label its stated size and in one piece', () => {
    const cellRule = declsOf(screen, '.label-cell')
    expect(cellRule['box-sizing']).toBe('border-box')
    // A label split across two pages is two useless halves; the old spelling is
    // kept because older engines honour only that one.
    expect(cellRule['break-inside']).toBe('avoid')
    expect(cellRule['page-break-inside']).toBe('avoid')
    // Without this the QR shrinks to make room for a long name.
    expect(declsOf(screen, '.label-qr').flex).toBe('none')
  })

  it('changes only the look of the sheet in print, never its geometry', () => {
    const GEOMETRY = [
      'display', 'grid', 'grid-template', 'grid-template-columns', 'grid-template-rows',
      'grid-auto-flow', 'grid-auto-columns', 'grid-auto-rows', 'gap', 'column-gap',
      'width', 'min-width', 'max-width', 'height', 'min-height', 'max-height',
      'flex', 'flex-basis', 'flex-grow', 'flex-shrink', 'flex-direction', 'margin',
      'transform', 'zoom', 'scale', 'position', 'float', 'columns', 'column-count',
      'aspect-ratio', 'box-sizing',
    ]
    const sheetParts = ['.label-sheet', '.label-cell', '.label-qr', '.label-text']
    const touched = print.filter((r) => r.selectors.some((sel) => sheetParts.includes(sel)))

    expect(touched.length).toBeGreaterThan(0) // the print block was found
    for (const r of touched) {
      const overridden = Object.keys(r.decls).filter((prop) => GEOMETRY.includes(prop))
      expect(overridden, `${r.selectors.join(', ')} under @media print`).toEqual([])
    }
  })

  it('prints black on white whatever the app theme is', () => {
    // On a dark OS with the "auto" theme, --text and --muted are pale: Chromium
    // printed all the label text at about 2.9:1 on white.
    for (const sel of ['.label-name', '.label-asset', '.label-token']) {
      expect(declsOf(print, sel).color, sel).toBe('#000')
    }
    // ... and "background graphics" would otherwise put the dark page behind it.
    expect(declsOf(print, '.label-cell').background).toBe('#fff')
  })

  it('keeps the layout radios from inheriting the global full-width input rule', () => {
    // style.css gives every input width:100% and exempts only checkboxes; a stretched
    // radio pushed its label text to the far side of the card.
    expect(declsOf(screen, '.layout-option input').width).toBe('auto')
    expect(descriptor.template.content).toMatch(/class="row layout-option"/)
  })

  it('reads only variables the component sets or the app theme defines', async () => {
    await mountSheet()
    await pick('Cordless drill')
    const set = new Set(
      [...sheet().attributes('style').matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]),
    )
    expect([...set].sort()).toEqual([...SHEET_VARS].sort())

    const themeTokens = new Set(
      [...readSrc('style.css').matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]),
    )
    const read = [...css.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1])
    const unknown = read.filter((v) => !set.has(v) && !themeTokens.has(v))
    expect(unknown).toEqual([])
  })
})

describe('LabelSheet print page', () => {
  const printStyle = () => document.head.querySelector('style[data-label-print-page]')

  it('prints on a page with no margin, with the app padding off, only while the view is open', async () => {
    expect(printStyle()).toBeNull()
    await mountSheet()

    const rules = parseCss(printStyle().textContent)
    expect(declsOf(rules, '@page')).toEqual({ margin: '0' })
    expect(declsOf(inMedia(rules, 'print'), 'main.content').padding).toBe('0')

    // It must not outlive the view: an @page margin of 0 left behind would strip
    // the margins from every page printed later in the session (the inventory report).
    wrapper.unmount()
    wrapper = null
    expect(printStyle()).toBeNull()

    await mountSheet()
    expect(document.head.querySelectorAll('style[data-label-print-page]')).toHaveLength(1)
  })

  it('resets the padded column the app really renders', () => {
    expect(readSrc('App.vue')).toMatch(/<main class="content">/)
    expect(declsOf(inMedia(parseCss(readSrc('style.css')), null), '.content').padding).toBeTruthy()
  })

  it.each(Object.keys(LAYOUT_VARS))(
    'the %s grid is no wider than A4, the narrowest paper it is printed on',
    async (id) => {
      await mountSheet()
      await pick('Cordless drill')
      await useLayout(id)

      // Wider than the page and the browser shrinks the whole sheet to fit, so no
      // label comes out at the size it claims (4 x 50.8 + 3 x 2.5 is 210.7 mm).
      const v = sheetVars()
      const cols = Number(v['--print-cols'])
      const widthMm = cols * parseFloat(v['--cell-w']) + (cols - 1) * parseFloat(v['--gutter'])
      expect(widthMm).toBeLessThanOrEqual(210)
    },
  )

  it('hides the fixed chat button and the toasts, which would print over the labels', () => {
    const hidden = inMedia(parseCss(readSrc('style.css')), 'print')
      .filter((r) => r.decls.display === 'none !important')
      .flatMap((r) => r.selectors)

    expect(hidden).toEqual(expect.arrayContaining(['.sidebar', '.topbar', '.no-print', '.asst', '.toast-wrap']))
    // ... and those are the roots the two components really render.
    expect(readSrc('components/ChatAssistant.vue')).toMatch(/<template>\s*<div class="asst">/)
    expect(readSrc('components/Toasts.vue')).toMatch(/<template>\s*<div class="toast-wrap"/)
  })

  it('tells the user how to get the stated size', async () => {
    await mountSheet()

    expect(wrapper.find('.layout-summary').text()).toMatch(/100% scale/)
    expect(wrapper.find('.layout-summary').text()).toMatch(/top-left corner/)
  })
})

describe('LabelSheet layout persistence', () => {
  it('remembers the chosen layout and restores it when the page is opened again', async () => {
    await mountSheet()
    await useLayout('small-4up')
    expect(localStorage.getItem(LABEL_LAYOUT)).toBe('small-4up')

    wrapper.unmount()
    await mountSheet()

    expect(radio('small-4up').element.checked).toBe(true)
    expect(radio('address-3up').element.checked).toBe(false)
    await pick('Cordless drill')
    expect(sheetVars()).toEqual(LAYOUT_VARS['small-4up'])
  })

  it.each([
    ['an unknown id (a layout from another build)', 'a4-sheet-21up'],
    ['an empty string', ''],
    ['an inherited property name', 'constructor'],
    ['__proto__', '__proto__'],
    ['toString', 'toString'],
  ])('falls back to the default for a garbage saved value: %s', async (_label, saved) => {
    localStorage.setItem(LABEL_LAYOUT, saved)

    await mountSheet()

    expect(radio('address-3up').element.checked).toBe(true)
    await pick('Cordless drill')
    expect(sheetVars()).toEqual(LAYOUT_VARS['address-3up'])
  })

  it('still works, with the default layout, when storage throws', async () => {
    // Fail only this page's key: the theme store reads localStorage unguarded at
    // start-up, which is not what this test is about.
    const real = localStorage
    const boom = () => { throw new Error('SecurityError') }
    vi.stubGlobal('localStorage', {
      getItem: (k) => (k === LABEL_LAYOUT ? boom() : real.getItem(k)),
      setItem: (k, v) => (k === LABEL_LAYOUT ? boom() : real.setItem(k, v)),
    })

    await mountSheet()
    expect(radio('address-3up').element.checked).toBe(true)

    // Choosing still applies for this visit even though it cannot be saved.
    await pick('Cordless drill')
    await useLayout('large-2up')
    expect(radio('large-2up').element.checked).toBe(true)
    expect(sheetVars()).toEqual(LAYOUT_VARS['large-2up'])
  })
})

describe('LabelSheet extra line', () => {
  it('prints an item asset id only on the layout that shows extra text', async () => {
    await mountSheet()
    await pick('Cordless drill', 'Loose screws', 'Garage bin', 'Shed')

    // Default and small layouts: no extra line at all, even for an item with an id.
    expect(wrapper.findAll('.label-asset')).toHaveLength(0)
    await useLayout('small-4up')
    expect(wrapper.findAll('.label-asset')).toHaveLength(0)

    await useLayout('large-2up')
    expect(cell('Cordless drill').find('.label-asset').text()).toBe('000-007')
  })

  it('prints nothing extra for an item with no asset id, a bin, or a location', async () => {
    await mountSheet()
    await pick('Cordless drill', 'Loose screws', 'Garage bin', 'Shed')
    await useLayout('large-2up')

    // Exactly one label carries the extra line, and it is the item that has an id.
    expect(wrapper.findAll('.label-asset').map((e) => e.text())).toEqual(['000-007'])
    expect(cell('Loose screws').find('.label-asset').exists()).toBe(false)
    expect(cell('Loose screws').text()).not.toContain('000-000')
    expect(cell('Garage bin').find('.label-asset').exists()).toBe(false)
    expect(cell('Shed').find('.label-asset').exists()).toBe(false)
    // Every cell still shows its name and token.
    expect(cell('Garage bin').find('.label-token').text()).toBe('tok-bin')
  })

  it('has no extra-text checkbox: the line follows the layout, not a control', async () => {
    await mountSheet()
    await useLayout('large-2up')

    expect(wrapper.find('input[type="checkbox"][disabled]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('short code')
    expect(wrapper.find('.layout-summary').text()).toContain('asset id')
  })
})

describe('LabelSheet printing', () => {
  it('is disabled until something is selected, then prints once, and disables again when cleared', async () => {
    await mountSheet()
    expect(printButton().attributes('disabled')).toBeDefined()
    expect(sheet().exists()).toBe(false)

    await pick('Cordless drill')
    expect(printButton().attributes('disabled')).toBeUndefined()
    expect(wrapper.find('.badge').text()).toBe('1 selected')

    await printButton().trigger('click')
    expect(window.print).toHaveBeenCalledTimes(1)

    const clear = wrapper.findAll('button').find((b) => b.text() === 'Clear selection')
    await clear.trigger('click')
    expect(printButton().attributes('disabled')).toBeDefined()
    expect(sheet().exists()).toBe(false)
  })

  it('waits for the QR images before it will print', async () => {
    let release
    const gate = new Promise((resolve) => { release = resolve })
    vi.stubGlobal('fetch', vi.fn(async () => {
      await gate
      return { ok: true, blob: async () => new Blob(['png']) }
    }))
    await mountSheet()

    await pick('Cordless drill')
    expect(printButton().text()).toContain('Preparing images')
    expect(printButton().attributes('disabled')).toBeDefined()
    // A click on a disabled button never reaches the handler, so it cannot show
    // the guard inside printSheet works; call it directly (Enter on a stale
    // focused button, or any other route to it, would).
    wrapper.vm.printSheet()
    expect(window.print).not.toHaveBeenCalled()

    release()
    await flushPromises()
    expect(printButton().text()).toContain('Print sheet')
    expect(printButton().attributes('disabled')).toBeUndefined()
  })
})

describe('LabelSheet selection', () => {
  const picked = () => wrapper.find('.page-head .badge').text()

  it('Select all picks every code in its group and loads each one\'s QR image', async () => {
    await mountSheet()

    groupButton('Items').click()
    await flushPromises()

    expect(picked()).toBe('2 selected')
    expect(fetchedImages('t-drill')).toBe(1)
    expect(fetchedImages('t-screws')).toBe(1)
    expect(cell('Cordless drill').find('img.label-qr').exists()).toBe(true)
    expect(cell('Loose screws').find('img.label-qr').exists()).toBe(true)
    expect(cell('Garage bin')).toBeUndefined() // the other groups are untouched
    expect(groupButton('Items').textContent).toContain('Deselect all')
  })

  it('Deselect all clears that group and no other', async () => {
    await mountSheet()
    await pick('Garage bin')
    groupButton('Items').click()
    await flushPromises()
    expect(picked()).toBe('3 selected')

    groupButton('Items').click()
    await flushPromises()

    expect(picked()).toBe('1 selected')
    expect(cell('Garage bin')).toBeTruthy()
    expect(cell('Cordless drill')).toBeUndefined()
    expect(groupButton('Items').textContent).toContain('Select all')
  })

  it('asks for a code\'s QR image once, however often it is picked', async () => {
    await mountSheet()

    await pick('Cordless drill')
    await tagRow('Cordless drill').find('input').setValue(false)
    await pick('Cordless drill')

    expect(fetchedImages('t-drill')).toBe(1)
    expect(cell('Cordless drill').find('img.label-qr').exists()).toBe(true)
  })
})

describe('LabelSheet failed images', () => {
  const failDrill = (url) => (url.includes('t-drill') ? http500() : pngOk())

  it('holds printing, says how many, and marks the code in the preview', async () => {
    stubFetch(failDrill)
    await mountSheet()

    await pick('Cordless drill', 'Garage bin')

    // The requests are done, so this is not a stuck "Preparing images" state;
    // it is a finished request that failed.
    expect(printButton().text()).toContain('Print sheet')
    expect(printButton().attributes('disabled')).toBeDefined()
    const banner = wrapper.find('.load-failed')
    expect(banner.attributes('role')).toBe('alert')
    expect(banner.classes()).toContain('no-print')
    expect(banner.text()).toContain('1 QR image could not be loaded')
    expect(cell('Cordless drill').find('.label-qr-failed').exists()).toBe(true)
    expect(cell('Cordless drill').find('img').exists()).toBe(false)
    expect(cell('Garage bin').find('img.label-qr').exists()).toBe(true)
    // The toast reaches the user wherever they have scrolled to.
    expect(useUI().toasts.some((t) => t.type === 'error' && t.message.includes('Cordless drill'))).toBe(true)
    // The guard inside printSheet, not just the disabled attribute.
    wrapper.vm.printSheet()
    expect(window.print).not.toHaveBeenCalled()
  })

  it('counts every failure', async () => {
    stubFetch(() => http500())
    await mountSheet()

    await pick('Cordless drill', 'Garage bin')

    expect(wrapper.find('.load-failed').text()).toContain('2 QR images could not be loaded')
  })

  it.each([
    ['an HTTP error', () => http500()],
    ['a dropped connection', () => { throw new TypeError('Failed to fetch') }],
    ['a body that cannot be read', () => ({ ok: true, blob: async () => { throw new Error('truncated') } })],
  ])('treats %s as a failed image', async (_label, response) => {
    stubFetch(response)
    await mountSheet()

    await pick('Cordless drill')

    expect(wrapper.find('.load-failed').exists()).toBe(true)
    expect(cell('Cordless drill').find('img').exists()).toBe(false)
    expect(printButton().text()).toContain('Print sheet')
    expect(printButton().attributes('disabled')).toBeDefined()
  })

  it('Try again asks only for the failed codes, then printing can go ahead', async () => {
    let healthy = false
    let release
    const gate = new Promise((resolve) => { release = resolve })
    stubFetch(async (url) => {
      if (!healthy) return url.includes('t-drill') ? http500() : pngOk()
      await gate
      return pngOk()
    })
    await mountSheet()
    await pick('Cordless drill', 'Garage bin')
    expect(wrapper.find('.load-failed').exists()).toBe(true)

    healthy = true
    await button('Try again').trigger('click')

    // The attempt is under way: the failure is not showing, the cell is loading
    // again, and there is nothing to print or to click a second time.
    expect(wrapper.find('.load-failed').exists()).toBe(false)
    expect(cell('Cordless drill').find('.skeleton').exists()).toBe(true)
    expect(printButton().text()).toContain('Preparing images')
    expect(printButton().attributes('disabled')).toBeDefined()

    release()
    await flushPromises()

    expect(fetchedImages('t-drill')).toBe(2)
    expect(fetchedImages('t-bin')).toBe(1) // loaded once; not asked for again
    expect(wrapper.find('.load-failed').exists()).toBe(false)
    expect(cell('Cordless drill').find('img.label-qr').exists()).toBe(true)
    expect(printButton().attributes('disabled')).toBeUndefined()
    await printButton().trigger('click')
    expect(window.print).toHaveBeenCalledTimes(1)
  })

  it('lets printing resume when the failed code is deselected, and retries it when picked again', async () => {
    let healthy = false
    stubFetch((url) => (!healthy && url.includes('t-drill') ? http500() : pngOk()))
    await mountSheet()
    await pick('Cordless drill', 'Garage bin')
    expect(printButton().attributes('disabled')).toBeDefined()

    await tagRow('Cordless drill').find('input').setValue(false)

    expect(wrapper.find('.load-failed').exists()).toBe(false)
    expect(printButton().attributes('disabled')).toBeUndefined()
    expect(cell('Cordless drill')).toBeUndefined()

    healthy = true
    await pick('Cordless drill')

    expect(fetchedImages('t-drill')).toBe(2)
    expect(cell('Cordless drill').find('img.label-qr').exists()).toBe(true)
    expect(wrapper.find('.load-failed').exists()).toBe(false)
  })
})

describe('LabelSheet load states', () => {
  // What a printer would be handed: every top-level node not marked no-print.
  const printable = () => roots().filter((el) => !el.classList.contains('no-print'))

  it('shows a skeleton while the codes load, with nothing printable', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    wrapper = mount(LabelSheet, { global: { plugins: [pinia] }, attachTo: document.body })

    expect(wrapper.find('.skeleton').exists()).toBe(true)
    expect(printButton().attributes('disabled')).toBeDefined()
    expect(printable()).toEqual([])

    await flushPromises()
  })

  it('shows the error, with a way to try again, when the codes cannot be loaded', async () => {
    api.get.mockRejectedValueOnce(new Error('server said no'))
    await mountSheet()

    expect(wrapper.text()).toContain('server said no')
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(printButton().attributes('disabled')).toBeDefined()
    expect(printable()).toEqual([])

    await button('Try again').trigger('click')
    await flushPromises()

    expect(api.get).toHaveBeenCalledTimes(2)
    expect(tagRow('Cordless drill')).toBeTruthy()
  })

  it.each([
    ['no codes at all', []],
    ['only codes the user printed themselves', [TAGS[4]]],
  ])('shows the empty state, with nothing to pick, for %s', async (_label, listed) => {
    api.get.mockResolvedValueOnce(listed.map((t) => ({ ...t })))
    await mountSheet()

    expect(wrapper.text()).toContain('No printable QR codes')
    expect(wrapper.find('input[type="checkbox"]').exists()).toBe(false)
    expect(wrapper.find('input[type="radio"]').exists()).toBe(false)
    expect(printButton().attributes('disabled')).toBeDefined()
    expect(printable()).toEqual([])
  })

  it('hands the printer only the sheet: every control, heading and message is no-print', async () => {
    await mountSheet()
    expect(printable()).toEqual([]) // nothing picked, nothing to print

    await pick('Cordless drill', 'Garage bin')

    expect(printable()).toHaveLength(1)
    expect(printable()[0].classList.contains('label-sheet')).toBe(true)
    // the picker card, the headings and the page head are all present, and all hidden
    expect(roots().filter((el) => el.classList.contains('no-print')).length).toBeGreaterThanOrEqual(3)
  })
})
