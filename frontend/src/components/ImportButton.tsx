import { Box, Button, Flex, Heading, SimpleGrid, Spinner, Text } from '@chakra-ui/react'
import type { ChangeEvent, DragEvent, KeyboardEvent, ReactElement, ReactNode } from 'react'
import { useEffect, useRef, useState } from 'react'
import type { ExportFiles, ExportFileType, ImportResponse, ImportStatus } from '../types'
import { importEventSchema, importResponseSchema } from '../types'
import { ExportToggle } from './ExportToggle'

const DEFAULT_SITE_NAME = 'DefaultSite'

type IconProps = { size?: number }
type IconFn = (p?: IconProps) => ReactElement

// SVG icons (no emoji), single stroke family. Color comes from the parent's `color`.
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
  upload: svg(
    <>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <polyline points="17 8 12 3 7 8" />
      <line x1="12" y1="3" x2="12" y2="15" />
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
}

// Secondary (CAT) button style: white, black border, inverts on hover.
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

interface ImportButtonProps {
  onImportComplete?: (data: ImportResponse) => void
}

function ImportButton({ onImportComplete }: ImportButtonProps) {
  const [importing, setImporting] = useState(false)
  const [status, setStatus] = useState<ImportStatus>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [exportStatus, setExportStatus] = useState<string | null>(null)
  const [exportFiles, setExportFiles] = useState<ExportFiles | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const eventSourceRef = useRef<EventSource | null>(null)

  const [exportModel, setExportModel] = useState(true)
  const [exportSimulation, setExportSimulation] = useState(true)
  const [exportRoutesExcel, setExportRoutesExcel] = useState(false)

  const [importBaseName, setImportBaseName] = useState(DEFAULT_SITE_NAME)

  const extractBaseName = (filename?: string): string => {
    if (!filename) return DEFAULT_SITE_NAME
    const lastDot = filename.lastIndexOf('.')
    return lastDot > 0 ? filename.substring(0, lastDot) : filename
  }

  const handleFileSelect = (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files
    if (!files || files.length === 0) return
    handleImport(files)
  }

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
        eventSourceRef.current = null
      }
    }
  }, [])

  const startSSE = (baseName: string) => {
    if (eventSourceRef.current) eventSourceRef.current.close()

    const eventSource = new EventSource(`/api/imports/${encodeURIComponent(baseName)}/events`)
    eventSourceRef.current = eventSource

    eventSource.onmessage = (event: MessageEvent) => {
      try {
        const parsed = importEventSchema.safeParse(JSON.parse(event.data))
        if (!parsed.success) {
          console.error('Invalid SSE payload:', parsed.error)
          return
        }
        const data = parsed.data
        setExportStatus(data.status)
        setMessage(data.message || '')

        if (data.status === 'completed') {
          setStatus('completed')
          setExportFiles(data.files || {})
          eventSource.close()
          eventSourceRef.current = null
        } else if (data.status === 'error') {
          setStatus('error')
          setError(data.message || 'Export failed')
          eventSource.close()
          eventSourceRef.current = null
        }
      } catch (err) {
        console.error('Error parsing SSE data:', err)
      }
    }

    eventSource.onerror = () => {
      eventSource.close()
      eventSourceRef.current = null
      // Surface the failure so the UI doesn't get stuck in 'processing' (L11):
      // if the export already completed before the stream dropped, keep that
      // success; otherwise mark the flow as errored.
      setStatus((prev) => (prev === 'completed' ? prev : 'error'))
      setError((prev) => prev ?? 'Lost connection to export stream')
    }
  }

  // Extension to use when the backend didn't report a concrete filename.
  // routes_excel is an .xlsx workbook; the rest are JSON.
  const fallbackExt: Record<ExportFileType, string> = {
    model: 'json',
    des_inputs: 'json',
    ledger: 'json',
    routes_excel: 'xlsx',
  }

  const handleDownloadFile = async (fileType: ExportFileType, filename?: string) => {
    try {
      const response = await fetch(
        `/api/imports/${encodeURIComponent(importBaseName)}/files/${fileType}`,
      )
      if (!response.ok) throw new Error('Download failed')
      const blob = await response.blob()
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

  const handleImport = async (files: FileList) => {
    if (files.length !== 1) {
      setError('Please upload exactly one ZIP file')
      return
    }
    const file = files[0]
    if (!file.name.toLowerCase().endsWith('.zip')) {
      setError('Only ZIP files are allowed')
      return
    }

    try {
      setImporting(true)
      setStatus('uploading')
      setMessage('Uploading files...')
      setError(null)
      setExportStatus(null)
      setExportFiles(null)

      const baseName = extractBaseName(file.name) || DEFAULT_SITE_NAME
      setImportBaseName(baseName)

      const formData = new FormData()
      formData.append('site_name', DEFAULT_SITE_NAME)
      formData.append('output_base_name', baseName)
      formData.append('export', 'true')
      formData.append('export_model', exportModel ? 'true' : 'false')
      formData.append('export_simulation', exportSimulation ? 'true' : 'false')
      formData.append('export_routes_excel', exportRoutesExcel ? 'true' : 'false')
      formData.append('files', file)

      const xhr = new XMLHttpRequest()

      xhr.upload.addEventListener('progress', (e: ProgressEvent) => {
        if (e.lengthComputable) {
          const percentComplete = Math.round((e.loaded / e.total) * 100)
          setMessage(`Uploading... ${percentComplete}%`)
        }
      })

      xhr.addEventListener('load', () => {
        if (xhr.status === 202) {
          let responseData: ImportResponse
          try {
            const parsed = importResponseSchema.safeParse(JSON.parse(xhr.responseText))
            if (!parsed.success) throw parsed.error
            responseData = parsed.data
          } catch {
            setStatus('error')
            setError('Failed to parse response')
            setImporting(false)
            return
          }

          setStatus('processing')
          setMessage('Import completed. Exporting simulation files...')

          const sseBaseName = responseData.output_base_name || baseName
          startSSE(sseBaseName)
          setImporting(false)
          if (onImportComplete) onImportComplete(responseData)
        } else {
          let serverMessage = `Server error: ${xhr.status}`
          try {
            const parsed = importResponseSchema.safeParse(JSON.parse(xhr.responseText))
            if (parsed.success) serverMessage = parsed.data.error || serverMessage
          } catch {
            // keep default message
          }
          setStatus('error')
          setError(serverMessage)
          setImporting(false)
        }
      })

      xhr.addEventListener('error', () => {
        setImporting(false)
        setStatus('error')
        setError('Network error occurred')
      })

      xhr.addEventListener('abort', () => {
        setImporting(false)
        setStatus('error')
        setError('Upload cancelled')
      })

      xhr.open('POST', '/api/imports')
      setStatus('parsing')
      setMessage('Parsing files...')
      xhr.send(formData)
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      setImporting(false)
      setStatus('error')
      setError(msg)
    }
  }

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    setDragActive(false)
    const files = event.dataTransfer.files
    if (files.length > 0) handleImport(files)
  }

  const handleDragOver = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
  }

  const handleDragEnter = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    if (!importing) setDragActive(true)
  }

  const handleDragLeave = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    event.stopPropagation()
    setDragActive(false)
  }

  const onlyOne = (self: boolean, a: boolean, b: boolean): boolean => self && !a && !b

  const statusMeta: { color: string; Icon: IconFn; label: string } =
    status === 'completed'
      ? { color: 'green.600', Icon: Icon.check, label: 'Completed' }
      : status === 'error'
        ? { color: 'red.600', Icon: Icon.alert, label: 'Error' }
        : { color: 'link', Icon: Icon.clock, label: status ?? '' }

  const downloads = (
    [
      ['model', 'Model', exportFiles?.model],
      ['des_inputs', 'DES Inputs', exportFiles?.des_inputs],
      ['ledger', 'Ledger', exportFiles?.ledger],
      ['routes_excel', 'Routes Excel', exportFiles?.routes_excel],
    ] as Array<[ExportFileType, string, string | undefined]>
  ).filter(([, , f]) => Boolean(f))

  const disabledToggles = importing || status === 'processing'

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
      {/* Card header — black band, CAT-yellow accent + text. */}
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
        <Box color="cat.yellow">{Icon.file({ size: 18 })}</Box>
        <Heading
          as="h2"
          fontFamily="heading"
          fontWeight="700"
          fontSize="lg"
          lineHeight="1"
          color="white"
        >
          Upload &amp; Export
        </Heading>
      </Flex>

      <Box p="4">
        <Flex direction="column" gap="5">
          {/* Status */}
          {status && (
            <Box
              borderRadius="md"
              borderWidth="1px"
              borderColor="line"
              bg="#fafafa"
              p="3"
              role="status"
              aria-live="polite"
            >
              <Flex align="center" gap="2">
                <Box color={statusMeta.color}>{statusMeta.Icon({ size: 16 })}</Box>
                <Text fontSize="sm" fontWeight="600" color="muted">
                  Status:
                </Text>
                <Flex
                  align="center"
                  borderRadius="sm"
                  borderWidth="1px"
                  borderColor={statusMeta.color}
                  color={statusMeta.color}
                  px="2"
                  py="0.5"
                  fontSize="xs"
                  fontWeight="700"
                  textTransform="uppercase"
                >
                  {statusMeta.label}
                </Flex>
              </Flex>
              {message && (
                <Text mt="2" fontSize="sm" color="muted">
                  {message}
                </Text>
              )}
            </Box>
          )}

          {error && (
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
                <b>Error:</b> {error}
              </Text>
            </Flex>
          )}

          {/* Export Options */}
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

          {/* Export completed -> downloads */}
          {exportStatus === 'completed' && downloads.length > 0 && (
            <Box borderRadius="md" borderWidth="1px" borderColor="green.200" bg="green.50" p="3">
              <Flex align="center" gap="2" mb="2" color="green.700">
                {Icon.check({ size: 16 })}
                <Text fontSize="sm" fontWeight="700">
                  Export Completed
                </Text>
              </Flex>
              <Flex wrap="wrap" gap="2">
                {downloads.map(([type, label, filename]) => (
                  <Button
                    key={type}
                    size="sm"
                    {...secondaryBtn}
                    onClick={() => handleDownloadFile(type, filename)}
                  >
                    <Box as="span" mr="1.5">
                      {Icon.download({ size: 14 })}
                    </Box>
                    {label}
                  </Button>
                ))}
              </Flex>
            </Box>
          )}

          {/* Upload dropzone */}
          <Box
            role="button"
            tabIndex={importing ? -1 : 0}
            aria-label="Upload a ZIP file, or drag and drop"
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragEnter={handleDragEnter}
            onDragLeave={handleDragLeave}
            onClick={() => {
              if (!importing) fileInputRef.current?.click()
            }}
            onKeyDown={(e: KeyboardEvent) => {
              if (!importing && (e.key === 'Enter' || e.key === ' ')) {
                e.preventDefault()
                fileInputRef.current?.click()
              }
            }}
            borderRadius="md"
            borderWidth="2px"
            borderStyle="dashed"
            p="8"
            textAlign="center"
            transition="background 0.15s, border-color 0.15s"
            cursor={importing ? 'not-allowed' : 'pointer'}
            bg={dragActive ? 'rgba(255,205,17,0.10)' : '#fafafa'}
            borderColor={dragActive ? 'cat.yellowEdge' : 'line'}
            _hover={importing ? {} : { borderColor: 'blackAlpha.500' }}
            _focusVisible={{ outline: '2px solid', outlineColor: 'link', outlineOffset: '2px' }}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              style={{ display: 'none' }}
              onChange={handleFileSelect}
              disabled={importing}
              aria-hidden="true"
              tabIndex={-1}
            />
            {importing ? (
              <Flex direction="column" align="center" gap="3">
                <Spinner size="lg" color="cat.yellowEdge" borderWidth="3px" />
                <Text fontSize="sm" color="muted">
                  {message}
                </Text>
              </Flex>
            ) : (
              <Flex direction="column" align="center" gap="2">
                <Box color="muted">{Icon.upload({ size: 40 })}</Box>
                <Text fontSize="md" color="ink">
                  <b>Click to upload</b> or drag and drop
                </Text>
                <Text fontSize="sm" color="muted">
                  ZIP file only (supports large files up to 5GB)
                </Text>
              </Flex>
            )}
          </Box>

          {/* Reset (secondary action) */}
          {(status === 'completed' || exportStatus === 'completed') && (
            <Button
              w="full"
              {...secondaryBtn}
              onClick={() => {
                setStatus(null)
                setMessage('')
                setError(null)
                setExportStatus(null)
                setExportFiles(null)
                if (eventSourceRef.current) {
                  eventSourceRef.current.close()
                  eventSourceRef.current = null
                }
                if (fileInputRef.current) fileInputRef.current.value = ''
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

export default ImportButton
