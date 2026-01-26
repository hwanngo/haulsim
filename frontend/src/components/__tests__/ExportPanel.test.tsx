import { ChakraProvider, defaultSystem } from '@chakra-ui/react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ExportPanel from '../ExportPanel'
import { ExportToggle } from '../ExportToggle'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function renderWithChakra(ui: ReactElement) {
  return render(<ChakraProvider value={defaultSystem}>{ui}</ChakraProvider>)
}

// A minimal EventSource stub that never fires events on its own (prevents real
// SSE). Tests can grab the last-constructed instance via `lastEventSource` and
// drive a `message` event through `onmessage` to simulate server progress.
let lastEventSource: MockEventSource | null = null

class MockEventSource {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 2
  readyState = MockEventSource.CONNECTING
  onmessage: ((e: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  constructor() {
    lastEventSource = this
  }
  close() {
    this.readyState = MockEventSource.CLOSED
  }
  // Test helper: dispatch a server SSE payload to the component's handler.
  emit(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) } as MessageEvent)
  }
}

// ---------------------------------------------------------------------------
// Setup: reset fetch + EventSource mocks before each test
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.restoreAllMocks()
  lastEventSource = null
  // Prevent any real SSE connection.
  vi.stubGlobal('EventSource', MockEventSource)
})

// ---------------------------------------------------------------------------
// ExportToggle tests
// ---------------------------------------------------------------------------

describe('ExportToggle', () => {
  it('calls onToggle when clicked and not disabled', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const icon = () => <svg />
    renderWithChakra(
      <ExportToggle
        icon={icon}
        label="Model"
        desc="desc"
        checked={false}
        disabled={false}
        onToggle={onToggle}
      />,
    )
    await user.click(screen.getByRole('switch', { name: /Model/i }))
    expect(onToggle).toHaveBeenCalledOnce()
  })

  it('does not call onToggle when disabled', async () => {
    const user = userEvent.setup()
    const onToggle = vi.fn()
    const icon = () => <svg />
    renderWithChakra(
      <ExportToggle
        icon={icon}
        label="Model"
        desc="desc"
        checked={false}
        disabled={true}
        onToggle={onToggle}
      />,
    )
    await user.click(screen.getByRole('switch', { name: /Model/i }))
    expect(onToggle).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// ExportPanel tests
// ---------------------------------------------------------------------------

describe('ExportPanel', () => {
  it('shows site dropdown populated from /api/sites', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sites: [
                { site_name: 'TestSite', site_short: 'TS', site_id: 1 },
                { site_name: 'OtherSite', site_short: 'OS', site_id: 2 },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              materials: [{ name: 'copper_ore', display_name: 'Copper Ore' }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    renderWithChakra(<ExportPanel />)

    // Sites dropdown should appear after fetch resolves
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /select site/i })).toBeInTheDocument()
    })
    expect(screen.getByText('TestSite (TS)')).toBeInTheDocument()
    expect(screen.getByText('OtherSite (OS)')).toBeInTheDocument()
  })

  it('shows material dropdown populated from /api/materials', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sites: [{ site_name: 'S1', site_short: 'S', site_id: 1 }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              materials: [
                { name: 'copper_ore', display_name: 'Copper Ore' },
                { name: 'iron_ore', display_name: 'Iron Ore' },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    renderWithChakra(<ExportPanel />)

    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /select material/i })).toBeInTheDocument()
    })
    expect(screen.getByText('Copper Ore')).toBeInTheDocument()
    expect(screen.getByText('Iron Ore')).toBeInTheDocument()
  })

  it('disables Start Export when materials fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sites: [{ site_name: 'S1', site_short: 'S', site_id: 1 }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(new Response('{}', { status: 500 }))
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    renderWithChakra(<ExportPanel />)

    await waitFor(() => {
      // Materials error state renders the retry button
      expect(screen.getByText(/Failed to load materials/i)).toBeInTheDocument()
    })

    const startBtn = screen.getByRole('button', { name: /Start Export/i })
    expect(startBtn).toBeDisabled()
  })

  it('renders error state when sites fetch fails', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(new Response('{}', { status: 503 }))
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              materials: [{ name: 'copper_ore', display_name: 'Copper Ore' }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    renderWithChakra(<ExportPanel />)

    await waitFor(() => {
      expect(screen.getByText(/Failed to load sites/i)).toBeInTheDocument()
    })
    // Retry button present
    expect(screen.getByRole('button', { name: /Retry/i })).toBeInTheDocument()
  })

  it('advanced numeric field can be cleared and retyped, and resets to default on empty blur', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sites: [{ site_name: 'S1', site_short: 'S', site_id: 1 }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              materials: [{ name: 'copper_ore', display_name: 'Copper Ore' }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    const user = userEvent.setup()
    renderWithChakra(<ExportPanel />)

    // Open the collapsed Advanced Settings panel.
    await user.click(screen.getByRole('button', { name: /Advanced Settings/i }))

    const limit = await screen.findByLabelText('Limit')
    // Default seeds the field (DEFAULT_CONFIG.limit = 100000).
    expect(limit).toHaveValue(100000)

    // Clearing must leave the field EMPTY (the regression: it used to snap back
    // to the default the instant it was cleared, making retyping impossible).
    await user.clear(limit)
    expect(limit).toHaveValue(null) // empty number input

    // And a fresh value can be typed in.
    await user.type(limit, '250')
    expect(limit).toHaveValue(250)

    // Clearing then blurring resets to the default (no stale value).
    await user.clear(limit)
    await user.tab()
    expect(limit).toHaveValue(100000)
  })

  it('shows per-zone material selects after a completed export', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation((input: RequestInfo | URL) => {
      const u = String(input)
      if (u.includes('/api/sites')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              sites: [{ site_name: 'S1', site_short: 'S', site_id: 1 }],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/materials')) {
        return Promise.resolve(
          new Response(
            JSON.stringify({
              materials: [
                { name: 'copper_ore', display_name: 'Copper Ore' },
                { name: 'iron_ore', display_name: 'Iron Ore' },
              ],
            }),
            { status: 200, headers: { 'Content-Type': 'application/json' } },
          ),
        )
      }
      if (u.includes('/api/exports')) {
        // POST /api/exports → 202 Accepted; the panel then opens an EventSource.
        return Promise.resolve(new Response('{}', { status: 202 }))
      }
      return Promise.reject(new Error(`Unexpected fetch: ${u}`))
    })

    const user = userEvent.setup()
    renderWithChakra(<ExportPanel />)

    // Wait for both dropdowns to load, then start the export.
    await waitFor(() => {
      expect(screen.getByRole('combobox', { name: /select material/i })).toBeInTheDocument()
    })
    await user.click(screen.getByRole('button', { name: /Start Export/i }))

    // The POST opens the (mock) EventSource; drive a completed event with zones.
    await waitFor(() => expect(lastEventSource).not.toBeNull())
    lastEventSource!.emit({
      status: 'completed',
      progress: 100,
      message: 'done',
      files: {},
      load_zones: [
        { id: 1, name: 'Load zone 1', hint: { x: 10, y: 20, z: 0 } },
        { id: 2, name: 'Load zone 2', hint: null },
      ],
    })

    // (a) The per-zone section appears showing both zone labels.
    await waitFor(() => {
      expect(screen.getByText('Load zone 1')).toBeInTheDocument()
    })
    expect(screen.getByText('Load zone 2')).toBeInTheDocument()
    // The hint for the first zone renders a short coordinate label.
    expect(screen.getByText('(10, 20)')).toBeInTheDocument()

    // (b) Each per-zone select defaults to the site-wide material (copper_ore).
    const zone1 = screen.getByRole('combobox', {
      name: /Material for Load zone 1/i,
    }) as HTMLSelectElement
    const zone2 = screen.getByRole('combobox', {
      name: /Material for Load zone 2/i,
    }) as HTMLSelectElement
    expect(zone1.value).toBe('copper_ore')
    expect(zone2.value).toBe('copper_ore')
  })
})
