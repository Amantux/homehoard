// @vitest-environment happy-dom
import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'

// Closing the scanner while the ZXing chunk is still loading must not leave the
// camera on: once the import resolves and the reader opens the stream, that
// stream has to be stopped because the modal is already gone (P49).

// The dynamic `import('@zxing/browser')` stays pending until the test opens
// this gate, so the modal can be unmounted mid-start.
const zx = vi.hoisted(() => {
  let open
  const gate = new Promise((r) => { open = r })
  return { gate, open, tracks: [], controls: [] }
})

vi.mock('@zxing/browser', async () => {
  await zx.gate
  return {
    BrowserMultiFormatReader: class {
      async decodeFromConstraints(constraints) {
        // What the real reader does: open the camera, hand back stop() controls.
        const stream = await navigator.mediaDevices.getUserMedia(constraints)
        const controls = { stop: vi.fn(() => stream.getTracks().forEach((t) => t.stop())) }
        zx.controls.push(controls)
        return controls
      }
    },
  }
})

vi.mock('../api', () => ({
  api: { get: vi.fn(async () => []), post: vi.fn(async () => ({})) },
}))

const ScannerModal = (await import('./ScannerModal.vue')).default

describe('ScannerModal camera lifecycle', () => {
  afterEach(() => { delete navigator.mediaDevices })

  it('stops the camera when closed before the ZXing import resolves', async () => {
    // happy-dom has no camera; force the ZXing path and fake getUserMedia.
    delete window.BarcodeDetector
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: vi.fn(async () => {
          const track = { stop: vi.fn(), kind: 'video' }
          zx.tracks.push(track)
          return { getTracks: () => [track] }
        }),
      },
    })

    const router = createRouter({
      history: createMemoryHistory(),
      routes: [{ path: '/:rest(.*)*', component: { render: () => null } }],
    })
    const wrapper = mount(ScannerModal, {
      global: { plugins: [createPinia(), router] },
      attachTo: document.body,
    })
    await flushPromises()
    expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled() // still loading ZXing

    wrapper.unmount()
    zx.open()
    await flushPromises()

    // Either the late start never reached the camera, or every track it opened
    // has been stopped. Both are a closed camera; a live track is the leak.
    for (const t of zx.tracks) expect(t.stop).toHaveBeenCalled()
  })
})
