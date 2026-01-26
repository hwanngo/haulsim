import { Box, Button, Flex, Heading, SimpleGrid, Spinner, Text } from '@chakra-ui/react'
import type { ReactElement, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import type {
  ExportConfig,
  ExportEvent,
  ExportFiles,
  ExportFileType,
  LoadZoneSummary,
  Material,
  Site,
} from '../types'
import {
  exportConfigSchema,
  exportEventSchema,
  materialsResponseSchema,
  sitesResponseSchema,
} from '../types'
import { ExportToggle } from './ExportToggle'

// ---------------------------------------------------------------------------
// Icon helpers (reuse the same svg/icon pattern from ImportButton)
// ---------------------------------------------------------------------------

type IconProps = { size?: number }
type IconFn = (p?: IconProps) => ReactElement

const svg =
  (paths: ReactNode): IconFn =>
  (p) => (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      width={p?.size ?? 18}
      height={p?.size ?? 18}
    >
      {paths}
    </svg>
  )

const Icon: Record<string, IconFn> = {
  file: svg(
    <>
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M12 18v-6" />
      <path d="M9 15h6" />
    </>,
  ),
  chart: svg(
    <>
      <path d="M3 3v18h18" />
      <path d="M18 17V9" />
      <path d="M13 17V5" />
      <path d="M8 17v-3" />
    </>,
  ),
  table: svg(
    <>
      <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z" />
      <polyline points="14 2 14 8 20 8" />
      <path d="M8 13h2" />
      <path d="M8 17h2" />
      <path d="M14 13h2" />
      <path d="M14 17h2" />
    </>,
  ),
  download: svg(
    <>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="7 10 12 15 17 10" />
      <line x1="12" y1="15" x2="12" y2="3" />
    </>,
  ),
  clock: svg(
    <>
      <circle cx="12" cy="12" r="10" />
      <polyline points="12 6 12 12 16 14" />
    </>,
  ),
  check: svg(
    <>
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" />
      <polyline points="22 4 12 14.01 9 11.01" />
    </>,
  ),
  alert: svg(
    <>
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </>,
  ),
  database: svg(
    <>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </>,
  ),
  chevron: svg(
    <>
      <polyline points="6 9 12 15 18 9" />
    </>,
  ),
  chevronUp: svg(
    <>
      <polyline points="18 15 12 9 6 15" />
    </>,
  ),
}

// ---------------------------------------------------------------------------
// Secondary button style (CAT: white, black border, inverts on hover)
// ---------------------------------------------------------------------------

const secondaryBtn = {
  bg: 'white',
  color: 'ink',
  borderWidth: '1px',
  borderColor: 'ink',
  borderRadius: 'sm',
  fontWeight: '600',
  _hover: { bg: 'ink', color: 'white' },
  _focusVisible: { outline: '2px solid', outlineColor: 'link', outlineOffset: '1px' },
}

// ---------------------------------------------------------------------------
// Default config values (matching DEFAULT_CONFIG / backend reality)
// ---------------------------------------------------------------------------

const DEFAULT_CONFIG: ExportConfig = {
  limit: 100000,
  sample_interval: 5,
  simplify_epsilon: 5.0,
  max_node_distance: 500.0,
  merge_tolerance: 15.0,
  zone_grid_size: 10.0,
  zone_min_stops: 20,
  sim_time: 480,
}

const DEFAULT_MATERIAL = 'copper_ore'

// ---------------------------------------------------------------------------
// ExportPanel
// ---------------------------------------------------------------------------

type SiteLoadState = 'loading' | 'error' | 'empty' | 'ready'
type MatLoadState = 'loading' | 'error' | 'ready'
type RunState = 'idle' | 'submitting' | 'running' | 'completed' | 'error'

export default function ExportPanel() {
  // Site picker state
  const [siteLoadState, setSiteLoadState] = useState<SiteLoadState>('loading')
  const [sites, setSites] = useState<Site[]>([])
  const [selectedSite, setSelectedSite] = useState<string>('')
  const [siteError, setSiteError] = useState<string>('')

  // Material selector state
  const [matLoadState, setMatLoadState] = useState<MatLoadState>('loading')
  const [materials, setMaterials] = useState<Material[]>([])
  const [selectedMaterial, setSelectedMaterial] = useState<string>(DEFAULT_MATERIAL)
  const [matError, setMatError] = useState<string>('')

  // Advanced settings (collapsed by default)
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [config, setConfig] = useState<ExportConfig>({ ...DEFAULT_CONFIG })
  // Raw text being typed into a numeric field. While a key is present here the
  // field shows the in-progress string (so it can be empty / partial like "3.");
  // a valid number is committed to `config` live, and on blur an empty/invalid
  // field resets to its DEFAULT_CONFIG value. Absent key → show committed config.
  const [configDraft, setConfigDraft] = useState<Partial<Record<keyof ExportConfig, string>>>({})

  // Export-type toggles
  const [exportModel, setExportModel] = useState(true)
  const [exportSimulation, setExportSimulation] = useState(true)
  const [exportRoutesExcel, setExportRoutesExcel] = useState(false)

  // Run state
  const [runState, setRunState] = useState<RunState>('idle')
  const [runMessage, setRunMessage] = useState('')
  const [runProgress, setRunProgress] = useState(0)
  const [runError, setRunError] = useState<string | null>(null)
  const [exportFiles, setExportFiles] = useState<ExportFiles | null>(null)

  // Per-zone material assignment (surfaced after a completed export).
  const [lastZones, setLastZones] = useState<LoadZoneSummary[]>([])
  const [zoneMaterials, setZoneMaterials] = useState<Record<number, string>>({})
  const [zoneMaterialsOpen, setZoneMaterialsOpen] = useState(false)

  // SSE ref
  const eventSourceRef = useRef<EventSource | null>(null)

  // ---------------------------------------------------------------------------
  // Fetch sites on mount
  // ---------------------------------------------------------------------------

  const fetchSites = () => {
    setSiteLoadState('loading')
    setSiteError('')
    fetch('/api/sites')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((raw: unknown) => {
        const parsed = sitesResponseSchema.safeParse(raw)
        if (!parsed.success) throw new Error('Unexpected /api/sites response shape')
        const list = parsed.data.sites
        if (list.length === 0) {
          setSiteLoadState('empty')
        } else {
          setSites(list)
          setSelectedSite(list[0].site_name)
          setSiteLoadState('ready')
        }
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        setSiteError(msg)
        setSiteLoadState('error')
      })
  }

  useEffect(() => {
    fetchSites()
  }, [])

  // ---------------------------------------------------------------------------
  // Fetch materials on mount
  // ---------------------------------------------------------------------------

  const fetchMaterials = () => {
    setMatLoadState('loading')
    setMatError('')
    fetch('/api/materials')
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((raw: unknown) => {
        const parsed = materialsResponseSchema.safeParse(raw)
        if (!parsed.success) throw new Error('Unexpected /api/materials response shape')
        const list = parsed.data.materials
        setMaterials(list)
        // Default to copper_ore if present, else first material
        const preferred = list.find((m) => m.name === DEFAULT_MATERIAL)
        setSelectedMaterial(preferred ? preferred.name : (list[0]?.name ?? DEFAULT_MATERIAL))
        setMatLoadState('ready')
      })
      .catch((err: unknown) => {
        const msg = err instanceof Error ? err.message : String(err)
        setMatError(msg)
        setMatLoadState('error')
      })
  }

  useEffect(() => {
    fetchMaterials()
  }, [])

  // ---------------------------------------------------------------------------
  // SSE cleanup on unmount
  // ---------------------------------------------------------------------------

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [])

  // ---------------------------------------------------------------------------
  // SSE startup
  // ---------------------------------------------------------------------------

  const startSSE = (siteName: string) => {
    // Close any existing connection before opening a new one
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }

    const es = new EventSource(`/api/exports/${encodeURIComponent(siteName)}/events`)
    eventSourceRef.current = es

    es.onmessage = (event: MessageEvent) => {
      let raw: unknown
      try {
        raw = JSON.parse(event.data as string)
      } catch {
        console.error('[ExportPanel] Failed to parse SSE JSON')
        return
      }

      const parsed = exportEventSchema.safeParse(raw)
      if (!parsed.success) {
        console.error('[ExportPanel] Invalid SSE payload:', parsed.error)
        return
      }

      const data: ExportEvent = parsed.data
      setRunMessage(data.message)
      setRunProgress(data.progress)

      if (data.status === 'completed') {
        setRunState('completed')
        setExportFiles(data.files)
        const zones = data.load_zones ?? []
        setLastZones(zones)
        // Surface the freshly detected zones expanded so they're discoverable.
        if (zones.length > 0) setZoneMaterialsOpen(true)
        es.close()
        eventSourceRef.current = null
      } else if (data.status === 'error') {
        setRunState('error')
        setRunError(data.message || 'Export failed')
        es.close()
        eventSourceRef.current = null
      }
    }

    es.onerror = () => {
      es.close()
      eventSourceRef.current = null
      setRunState((prev) => (prev === 'completed' ? prev : 'error'))
      setRunError((prev) => prev ?? 'Lost connection to export stream')
    }
  }

  // ---------------------------------------------------------------------------
  // Start export
  // ---------------------------------------------------------------------------

  const handleStartExport = async () => {
    if (
      !selectedSite ||
      !anyToggleSelected ||
      matLoadState === 'error' ||
      runState === 'submitting' ||
      runState === 'running'
    )
      return

    setRunState('submitting')
    setRunError(null)
    setRunMessage('')
    setRunProgress(0)
    setExportFiles(null)

    // Validate config before posting
    const configResult = exportConfigSchema.safeParse({ ...config, material: selectedMaterial })
    if (!configResult.success) {
      setRunState('error')
      setRunError('Invalid export configuration')
      return
    }

    // Build the per-zone override map, omitting any zone left at the site
    // default. An all-default selection sends no map at all, preserving the
    // byte-identical no-map backend path.
    const outboundConfig: ExportConfig = { ...configResult.data }
    const zm: Record<string, string> = {}
    for (const z of lastZones) {
      const m = zoneMaterials[z.id]
      if (m && m !== selectedMaterial) zm[String(z.id)] = m
    }
    if (Object.keys(zm).length > 0) outboundConfig.zone_materials = zm

    try {
      const resp = await fetch('/api/exports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          site_name: selectedSite,
          config: outboundConfig,
          export_model: exportModel,
          export_simulation: exportSimulation,
          export_routes_excel: exportRoutesExcel,
        }),
      })

      if (resp.status === 202) {
        setRunState('running')
        startSSE(selectedSite)
      } else if (resp.status === 400 || resp.status === 409) {
        let msg = `Server error: ${resp.status}`
        try {
          const body = (await resp.json()) as { error?: string }
          if (body.error) msg = body.error
        } catch {
          /* keep default */
        }
        setRunState('error')
        setRunError(msg)
      } else {
        setRunState('error')
        setRunError(`Unexpected server response: ${resp.status}`)
      }
    } catch (err) {
      setRunState('error')
      setRunError(err instanceof Error ? err.message : 'Network error')
    }
  }

  // ---------------------------------------------------------------------------
  // Download handler (mirrors ImportButton exactly)
  // ---------------------------------------------------------------------------

  const fallbackExt: Record<ExportFileType, string> = {
    model: 'json',
    des_inputs: 'json',
    ledger: 'json',
    routes_excel: 'xlsx',
  }

  const handleDownload = async (fileType: ExportFileType, filename?: string) => {
    try {
      const resp = await fetch(`/api/exports/${encodeURIComponent(selectedSite)}/files/${fileType}`)
      if (!resp.ok) throw new Error(`Download failed: ${resp.status}`)
      const blob = await resp.blob()
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename || `${fileType}.${fallbackExt[fileType]}`
      document.body.appendChild(a)
      a.click()
      window.URL.revokeObjectURL(url)
      document.body.removeChild(a)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      alert(`Failed to download ${fileType}: ${msg}`)
    }
  }

  // ---------------------------------------------------------------------------
  // Derived state
  // ---------------------------------------------------------------------------

  const anyToggleSelected = exportModel || exportSimulation || exportRoutesExcel

  const onlyOne = (self: boolean, a: boolean, b: boolean) => self && !a && !b

  const startDisabled =
    !selectedSite ||
    !anyToggleSelected ||
    matLoadState === 'error' ||
    runState === 'submitting' ||
    runState === 'running' ||
    siteLoadState !== 'ready'

  const disabledToggles = runState === 'submitting' || runState === 'running'

  // Show the per-zone material section only once an export has surfaced zones
  // for this site and the material list is ready to populate the dropdowns.
  const showZoneMaterials = lastZones.length > 0 && matLoadState === 'ready'

  // Short, muted location hint from a zone centroid, e.g. "(10, 20)".
  const zoneHintLabel = (hint: LoadZoneSummary['hint']): string | null =>
    hint ? `(${Math.round(hint.x)}, ${Math.round(hint.y)})` : null

  // Downloads to show: only the types that were actually generated
  const downloads = (
    [
      ['model', 'Model', exportFiles?.model],
      ['des_inputs', 'DES Inputs', exportFiles?.des_inputs],
      ['ledger', 'Ledger', exportFiles?.ledger],
      ['routes_excel', 'Routes Excel', exportFiles?.routes_excel],
    ] as Array<[ExportFileType, string, string | undefined]>
  ).filter(([, , f]) => Boolean(f))

  // ---------------------------------------------------------------------------
  // Config field helper
  // ---------------------------------------------------------------------------

  const configField = (key: keyof ExportConfig, label: string, helper: string, isInt = false) => (
    <Box key={key}>
      <label
        htmlFor={`cfg-${key}`}
        style={{
          fontSize: '14px',
          fontWeight: 600,
          color: '#000000',
          display: 'block',
          marginBottom: '4px',
        }}
      >
        {label}
      </label>
      <input
        id={`cfg-${key}`}
        type="number"
        value={configDraft[key] ?? String(config[key])}
        onChange={(e) => {
          const text = e.target.value
          // Keep the raw text so the field can be empty / partial while editing.
          setConfigDraft((prev) => ({ ...prev, [key]: text }))
          // Commit a valid number live so a submit without blur isn't stale.
          if (text.trim() !== '') {
            const val = isInt ? parseInt(text, 10) : parseFloat(text)
            if (!isNaN(val)) setConfig((prev) => ({ ...prev, [key]: val }))
          }
        }}
        style={{
          width: '100%',
          border: '1px solid #E5E7EB',
          borderRadius: '2px',
          padding: '6px 8px',
          fontSize: '14px',
          color: '#000000',
          background: 'white',
          outline: 'none',
        }}
        onFocus={(e) => (e.target.style.borderColor = '#0067B8')}
        onBlur={(e) => {
          e.target.style.borderColor = '#E5E7EB'
          const text = e.target.value
          const val = isInt ? parseInt(text, 10) : parseFloat(text)
          // Empty or unparseable on blur → fall back to the default (no stale value).
          if (text.trim() === '' || isNaN(val)) {
            setConfig((prev) => ({ ...prev, [key]: DEFAULT_CONFIG[key] }))
          }
          // Drop the draft so the field reflects the committed config again.
          setConfigDraft((prev) => {
            const next = { ...prev }
            delete next[key]
            return next
          })
        }}
      />
      <Text fontSize="xs" color="muted" mt="0.5">
        {helper}
      </Text>
    </Box>
  )

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <Box
      as="section"
      borderRadius="lg"
      borderWidth="1px"
      borderColor="line"
      bg="white"
      boxShadow="sm"
      overflow="hidden"
    >
      {/* Card header */}
      <Flex
        as="header"
        align="center"
        gap="2"
        bg="ink"
        px="4"
        py="3"
        borderBottomWidth="2px"
        borderColor="cat.yellow"
      >
        <Box color="cat.yellow">{Icon.database({ size: 18 })}</Box>
        <Heading
          as="h2"
          fontFamily="heading"
          fontWeight="700"
          fontSize="lg"
          lineHeight="1"
          color="white"
        >
          Export from Database
        </Heading>
      </Flex>

      <Box p="4">
        <Flex direction="column" gap="5">
          {/* ----------------------------------------------------------------
              Run status / SSE progress
          ---------------------------------------------------------------- */}
          {(runState === 'running' || runState === 'submitting') && (
            <Box
              borderRadius="md"
              borderWidth="1px"
              borderColor="line"
              bg="#fafafa"
              p="3"
              role="status"
              aria-live="polite"
            >
              <Flex align="center" gap="2" mb="2">
                <Box color="link">{Icon.clock({ size: 16 })}</Box>
                <Text fontSize="sm" fontWeight="600" color="muted">
                  Status:
                </Text>
                <Flex
                  align="center"
                  borderRadius="sm"
                  borderWidth="1px"
                  borderColor="link"
                  color="link"
                  px="2"
                  py="0.5"
                  fontSize="xs"
                  fontWeight="700"
                  textTransform="uppercase"
                >
                  {runState === 'submitting' ? 'Submitting' : 'Processing'}
                </Flex>
              </Flex>
              {runMessage && (
                <Text fontSize="sm" color="muted" mb="2">
                  {runMessage}
                </Text>
              )}
              {runState === 'running' && (
                <Box>
                  <Box h="2" borderRadius="full" bg="line" overflow="hidden">
                    <Box
                      h="full"
                      borderRadius="full"
                      bg="cat.yellow"
                      style={{ width: `${runProgress}%`, transition: 'width 0.3s ease' }}
                    />
                  </Box>
                  <Text fontSize="xs" color="muted" mt="1">
                    {runProgress}%
                  </Text>
                </Box>
              )}
            </Box>
          )}

          {/* Run error */}
          {runState === 'error' && runError && (
            <Flex
              align="flex-start"
              gap="2"
              borderRadius="md"
              borderWidth="1px"
              borderColor="red.600"
              bg="red.50"
              p="3"
              color="red.600"
              role="alert"
            >
              <Box mt="0.5" flexShrink="0">
                {Icon.alert({ size: 16 })}
              </Box>
              <Text fontSize="sm">
                <b>Error:</b> {runError}
              </Text>
            </Flex>
          )}

          {/* ----------------------------------------------------------------
              Completed: progress summary + downloads
          ---------------------------------------------------------------- */}
          {runState === 'completed' && (
            <Box borderRadius="md" borderWidth="1px" borderColor="green.200" bg="green.50" p="3">
              <Flex align="center" gap="2" mb="2" color="green.700">
                {Icon.check({ size: 16 })}
                <Text fontSize="sm" fontWeight="700">
                  Export Completed
                </Text>
              </Flex>
              {downloads.length > 0 ? (
                <Flex wrap="wrap" gap="2">
                  {downloads.map(([type, label, filename]) => (
                    <Button
                      key={type}
                      size="sm"
                      {...secondaryBtn}
                      onClick={() => handleDownload(type, filename)}
                    >
                      <Box as="span" mr="1.5">
                        {Icon.download({ size: 14 })}
                      </Box>
                      {label}
                    </Button>
                  ))}
                </Flex>
              ) : (
                <Text fontSize="sm" color="muted">
                  No files were generated for the selected export types.
                </Text>
              )}
            </Box>
          )}

          {/* ----------------------------------------------------------------
              Site picker
          ---------------------------------------------------------------- */}
          <Box>
            <Flex align="center" gap="2" mb="2" color="ink">
              {Icon.database({ size: 16 })}
              <Heading
                as="h3"
                fontFamily="heading"
                fontWeight="700"
                fontSize="md"
                lineHeight="1"
                color="ink"
              >
                Site
              </Heading>
            </Flex>

            {siteLoadState === 'loading' && (
              <Flex
                align="center"
                gap="2"
                p="3"
                borderRadius="md"
                borderWidth="1px"
                borderColor="line"
                bg="#fafafa"
              >
                <Spinner size="sm" color="cat.yellowEdge" borderWidth="2px" />
                <Text fontSize="sm" color="muted">
                  Loading sites…
                </Text>
              </Flex>
            )}

            {siteLoadState === 'error' && (
              <Flex
                direction="column"
                gap="2"
                p="3"
                borderRadius="md"
                borderWidth="1px"
                borderColor="red.600"
                bg="red.50"
                color="red.600"
                role="alert"
              >
                <Flex align="center" gap="2">
                  {Icon.alert({ size: 16 })}
                  <Text fontSize="sm">
                    <b>Failed to load sites:</b> {siteError}
                  </Text>
                </Flex>
                <Button size="sm" {...secondaryBtn} onClick={fetchSites} alignSelf="flex-start">
                  Retry
                </Button>
              </Flex>
            )}

            {siteLoadState === 'empty' && (
              <Text
                fontSize="sm"
                color="muted"
                p="3"
                borderRadius="md"
                borderWidth="1px"
                borderColor="line"
              >
                No sites available.
              </Text>
            )}

            {siteLoadState === 'ready' && (
              <select
                value={selectedSite}
                onChange={(e) => setSelectedSite(e.target.value)}
                disabled={disabledToggles}
                style={{
                  width: '100%',
                  border: '1px solid #E5E7EB',
                  borderRadius: '2px',
                  padding: '8px 10px',
                  fontSize: '14px',
                  color: '#000000',
                  background: 'white',
                  cursor: disabledToggles ? 'not-allowed' : 'pointer',
                  opacity: disabledToggles ? 0.6 : 1,
                }}
                aria-label="Select site"
              >
                {sites.map((s) => (
                  <option key={s.site_name} value={s.site_name}>
                    {s.site_name}
                    {s.site_short ? ` (${s.site_short})` : ''}
                  </option>
                ))}
              </select>
            )}
          </Box>

          {/* ----------------------------------------------------------------
              Material selector
          ---------------------------------------------------------------- */}
          <Box>
            <Flex align="center" gap="2" mb="2" color="ink">
              {Icon.file({ size: 16 })}
              <Heading
                as="h3"
                fontFamily="heading"
                fontWeight="700"
                fontSize="md"
                lineHeight="1"
                color="ink"
              >
                Material
              </Heading>
            </Flex>

            {matLoadState === 'loading' && (
              <Flex
                align="center"
                gap="2"
                p="3"
                borderRadius="md"
                borderWidth="1px"
                borderColor="line"
                bg="#fafafa"
              >
                <Spinner size="sm" color="cat.yellowEdge" borderWidth="2px" />
                <Text fontSize="sm" color="muted">
                  Loading materials…
                </Text>
              </Flex>
            )}

            {matLoadState === 'error' && (
              <Flex
                direction="column"
                gap="2"
                p="3"
                borderRadius="md"
                borderWidth="1px"
                borderColor="red.600"
                bg="red.50"
                color="red.600"
                role="alert"
              >
                <Flex align="center" gap="2">
                  {Icon.alert({ size: 16 })}
                  <Text fontSize="sm">
                    <b>Failed to load materials:</b> {matError}
                  </Text>
                </Flex>
                <Button size="sm" {...secondaryBtn} onClick={fetchMaterials} alignSelf="flex-start">
                  Retry
                </Button>
                <Text fontSize="xs" color="muted">
                  Start Export is disabled until materials load successfully.
                </Text>
              </Flex>
            )}

            {matLoadState === 'ready' && (
              <>
                <select
                  value={selectedMaterial}
                  onChange={(e) => setSelectedMaterial(e.target.value)}
                  disabled={disabledToggles}
                  style={{
                    width: '100%',
                    border: '1px solid #E5E7EB',
                    borderRadius: '2px',
                    padding: '8px 10px',
                    fontSize: '14px',
                    color: '#000000',
                    background: 'white',
                    cursor: disabledToggles ? 'not-allowed' : 'pointer',
                    opacity: disabledToggles ? 0.6 : 1,
                  }}
                  aria-label="Select material"
                >
                  {materials.map((m) => (
                    <option key={m.name} value={m.name}>
                      {m.display_name}
                    </option>
                  ))}
                </select>
                <Text fontSize="xs" color="muted" mt="1">
                  Material used for density and payload calculations in the simulation output.
                </Text>
              </>
            )}
          </Box>

          {/* ----------------------------------------------------------------
              Per-zone materials (optional) — appears after a completed export
          ---------------------------------------------------------------- */}
          {showZoneMaterials && (
            <Box>
              <button
                type="button"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  width: '100%',
                  textAlign: 'left',
                  minHeight: '44px',
                  padding: '8px 0',
                  background: 'transparent',
                  border: 'none',
                  cursor: 'pointer',
                }}
                onClick={() => setZoneMaterialsOpen((o) => !o)}
                aria-expanded={zoneMaterialsOpen}
                aria-controls="zone-materials-panel"
              >
                <Box color={zoneMaterialsOpen ? 'cat.yellowEdge' : 'muted'}>
                  {zoneMaterialsOpen ? Icon.chevronUp({ size: 16 }) : Icon.chevron({ size: 16 })}
                </Box>
                <Text fontFamily="heading" fontWeight="700" fontSize="md" color="ink">
                  Per-zone materials
                </Text>
                <Text fontSize="xs" color="muted" ml="1">
                  (optional — {lastZones.length} {lastZones.length === 1 ? 'zone' : 'zones'}{' '}
                  detected)
                </Text>
              </button>

              {zoneMaterialsOpen && (
                <Box
                  id="zone-materials-panel"
                  mt="3"
                  p="3"
                  borderRadius="md"
                  borderWidth="1px"
                  borderColor="line"
                  bg="#fafafa"
                >
                  <Text fontSize="xs" color="muted" mb="3">
                    Per-zone assignments apply to the zones detected in the last export. Changing
                    detection settings can shift zone ids.
                  </Text>
                  <Flex direction="column" gap="3">
                    {lastZones.map((z) => {
                      const hint = zoneHintLabel(z.hint)
                      const selectId = `zone-mat-${z.id}`
                      return (
                        <Box key={z.id}>
                          <label
                            htmlFor={selectId}
                            style={{ display: 'block', marginBottom: '4px' }}
                          >
                            <Box as="span" fontSize="sm" fontWeight="600" color="ink">
                              {z.name}
                            </Box>
                            {hint && (
                              <Box as="span" fontSize="xs" color="muted" ml="1.5">
                                {hint}
                              </Box>
                            )}
                          </label>
                          <select
                            id={selectId}
                            value={zoneMaterials[z.id] ?? selectedMaterial}
                            onChange={(e) =>
                              setZoneMaterials((prev) => ({ ...prev, [z.id]: e.target.value }))
                            }
                            disabled={disabledToggles}
                            style={{
                              width: '100%',
                              minHeight: '44px',
                              border: '1px solid #E5E7EB',
                              borderRadius: '2px',
                              padding: '8px 10px',
                              fontSize: '14px',
                              color: '#000000',
                              background: 'white',
                              cursor: disabledToggles ? 'not-allowed' : 'pointer',
                              opacity: disabledToggles ? 0.6 : 1,
                            }}
                            aria-label={`Material for ${z.name}`}
                          >
                            {materials.map((m) => (
                              <option key={m.name} value={m.name}>
                                {m.display_name}
                              </option>
                            ))}
                          </select>
                        </Box>
                      )
                    })}
                  </Flex>
                </Box>
              )}
            </Box>
          )}

          {/* ----------------------------------------------------------------
              Export-type toggles
          ---------------------------------------------------------------- */}
          <Box>
            <Flex align="center" gap="2" mb="2" color="ink">
              {Icon.file({ size: 16 })}
              <Heading
                as="h3"
                fontFamily="heading"
                fontWeight="700"
                fontSize="md"
                lineHeight="1"
                color="ink"
              >
                Export Options
              </Heading>
            </Flex>
            <SimpleGrid columns={{ base: 1, sm: 2 }} gap="3">
              <ExportToggle
                icon={Icon.file}
                label="Model"
                desc="Site structure & config"
                checked={exportModel}
                disabled={disabledToggles}
                onToggle={() => {
                  if (!onlyOne(exportModel, exportSimulation, exportRoutesExcel))
                    setExportModel(!exportModel)
                }}
              />
              <ExportToggle
                icon={Icon.chart}
                label="Simulation"
                desc="DES inputs & events"
                checked={exportSimulation}
                disabled={disabledToggles}
                onToggle={() => {
                  if (!onlyOne(exportSimulation, exportModel, exportRoutesExcel))
                    setExportSimulation(!exportSimulation)
                }}
              />
              <ExportToggle
                icon={Icon.table}
                label="Routes Excel"
                desc="Route template format"
                checked={exportRoutesExcel}
                disabled={disabledToggles}
                onToggle={() => {
                  if (!onlyOne(exportRoutesExcel, exportModel, exportSimulation))
                    setExportRoutesExcel(!exportRoutesExcel)
                }}
              />
            </SimpleGrid>
          </Box>

          {/* ----------------------------------------------------------------
              Advanced settings (collapsible)
          ---------------------------------------------------------------- */}
          <Box>
            <button
              type="button"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                width: '100%',
                textAlign: 'left',
                padding: '8px 0',
                background: 'transparent',
                border: 'none',
                cursor: 'pointer',
              }}
              onClick={() => setAdvancedOpen((o) => !o)}
              aria-expanded={advancedOpen}
            >
              <Box color={advancedOpen ? 'cat.yellowEdge' : 'muted'}>
                {advancedOpen ? Icon.chevronUp({ size: 16 }) : Icon.chevron({ size: 16 })}
              </Box>
              <Text fontFamily="heading" fontWeight="700" fontSize="md" color="ink">
                Advanced Settings
              </Text>
              <Text fontSize="xs" color="muted" ml="1">
                (collapsed by default — adjust processing parameters)
              </Text>
            </button>

            {advancedOpen && (
              <Box mt="3" p="3" borderRadius="md" borderWidth="1px" borderColor="line" bg="#fafafa">
                <SimpleGrid columns={{ base: 1, sm: 2 }} gap="4">
                  {configField('limit', 'Limit', 'Max telemetry records to fetch from DB', true)}
                  {configField(
                    'sample_interval',
                    'Sample interval (s)',
                    'Downsample GPS to every N seconds',
                    true,
                  )}
                  {configField(
                    'simplify_epsilon',
                    'Simplify epsilon (m)',
                    'Road path simplification tolerance',
                  )}
                  {configField(
                    'max_node_distance',
                    'Max node distance (m)',
                    'Max gap between road network nodes',
                  )}
                  {configField(
                    'merge_tolerance',
                    'Merge tolerance (m)',
                    'Distance to merge nearby road nodes',
                  )}
                  {configField(
                    'zone_grid_size',
                    'Zone grid size (m)',
                    'DBSCAN grid cell size for zone detection',
                  )}
                  {configField(
                    'zone_min_stops',
                    'Zone min stops',
                    'Min stop count for a valid zone cluster',
                    true,
                  )}
                  {configField(
                    'sim_time',
                    'Sim time (min)',
                    'Simulation duration in minutes',
                    true,
                  )}
                </SimpleGrid>
              </Box>
            )}
          </Box>

          {/* ----------------------------------------------------------------
              Start Export CTA
          ---------------------------------------------------------------- */}
          <Button
            w="full"
            bg="cat.yellow"
            color="ink"
            fontFamily="heading"
            fontWeight="700"
            fontSize="md"
            borderRadius="sm"
            borderWidth="2px"
            borderColor="cat.yellowEdge"
            _hover={startDisabled ? {} : { bg: 'cat.yellowEdge', color: 'white' }}
            _focusVisible={{ outline: '2px solid', outlineColor: 'link', outlineOffset: '1px' }}
            disabled={startDisabled}
            opacity={startDisabled ? 0.5 : 1}
            cursor={startDisabled ? 'not-allowed' : 'pointer'}
            onClick={handleStartExport}
          >
            {runState === 'submitting' ? (
              <Flex align="center" gap="2">
                <Spinner size="sm" borderWidth="2px" />
                <span>Starting…</span>
              </Flex>
            ) : (
              'Start Export'
            )}
          </Button>

          {/* Reset after completion or error */}
          {(runState === 'completed' || runState === 'error') && (
            <Button
              w="full"
              {...secondaryBtn}
              onClick={() => {
                setRunState('idle')
                setRunMessage('')
                setRunProgress(0)
                setRunError(null)
                setExportFiles(null)
                if (eventSourceRef.current) {
                  eventSourceRef.current.close()
                  eventSourceRef.current = null
                }
              }}
            >
              Reset
            </Button>
          )}
        </Flex>
      </Box>
    </Box>
  )
}
