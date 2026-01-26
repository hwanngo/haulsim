// Shapes exchanged with the backend (/api/imports + SSE), defined as Zod schemas
// so the TypeScript types and the runtime validators stay in lockstep. The UI
// validates every parsed payload at the network boundary (safeParse) instead of
// trusting `JSON.parse(...) as T`, so a malformed/changed backend response is
// caught and surfaced rather than silently mis-rendered.

import { z } from 'zod'

export const exportFilesSchema = z.object({
  model: z.string().optional(),
  des_inputs: z.string().optional(),
  ledger: z.string().optional(),
  routes_excel: z.string().optional(),
})
export type ExportFiles = z.infer<typeof exportFilesSchema>

// Response from POST /api/imports. The backend always sends `success`; the other
// fields are present on success (202) or replaced by `error` on failure.
export const importResponseSchema = z.object({
  success: z.boolean(),
  output_base_name: z.string().optional(),
  files_processed: z.number().optional(),
  records_count: z.number().optional(),
  message: z.string().optional(),
  error: z.string().optional(),
})
export type ImportResponse = z.infer<typeof importResponseSchema>

// Lifecycle states the import/export flow can be in. `null` = not started.
export type ImportStatus = 'uploading' | 'parsing' | 'processing' | 'completed' | 'error' | null

// SSE payload pushed during import+export. The backend's set_import_status
// always serializes `status`, `message`, and `files` (the latter defaulting to
// {}), so those are required here; the code branches on the `status` literals.
export const importEventSchema = z.object({
  status: z.enum(['idle', 'uploading', 'parsing', 'processing', 'completed', 'error']),
  message: z.string(),
  files: exportFilesSchema,
})
export type ImportEvent = z.infer<typeof importEventSchema>

export const exportFileTypeSchema = z.enum(['model', 'des_inputs', 'ledger', 'routes_excel'])
export type ExportFileType = z.infer<typeof exportFileTypeSchema>

// Sub-project C: export UI schemas

export const siteSchema = z.object({
  site_name: z.string(),
  site_short: z.string(),
  site_id: z.number(),
})
export const sitesResponseSchema = z.object({ sites: z.array(siteSchema) })
export type Site = z.infer<typeof siteSchema>

export const materialSchema = z.object({ name: z.string(), display_name: z.string() })
export const materialsResponseSchema = z.object({ materials: z.array(materialSchema) })
export type Material = z.infer<typeof materialSchema>

export const loadZoneSummarySchema = z.object({
  id: z.number(),
  name: z.string(),
  hint: z.object({ x: z.number(), y: z.number(), z: z.number() }).nullable().optional(),
})
export type LoadZoneSummary = z.infer<typeof loadZoneSummarySchema>

export const exportConfigSchema = z.object({
  limit: z.number(),
  sample_interval: z.number(),
  simplify_epsilon: z.number(),
  max_node_distance: z.number(),
  merge_tolerance: z.number(),
  zone_grid_size: z.number(),
  zone_min_stops: z.number(),
  sim_time: z.number(),
  material: z.string().optional(),
  zone_materials: z.record(z.string(), z.string()).optional(),
})
export type ExportConfig = z.infer<typeof exportConfigSchema>

export const exportEventSchema = z.object({
  status: z.enum(['idle', 'processing', 'completed', 'error']),
  progress: z.number(),
  message: z.string(),
  files: exportFilesSchema,
  load_zones: z.array(loadZoneSummarySchema).optional(),
})
export type ExportEvent = z.infer<typeof exportEventSchema>
