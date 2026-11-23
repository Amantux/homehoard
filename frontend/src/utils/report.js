// Shared report plumbing for the registry-driven reports surface.
//
// The backend owns the report registry (backend/app/api/reports_registry.py):
// GET /api/v1/reports lists what is registered and GET /api/v1/reports/<id>
// builds one of them. Every built payload carries the shared report envelope
// (``generatedAt`` + ``currency``) alongside the report's own shape, and reports
// that declare CSV columns export through GET /api/v1/reports/<id>.csv.
//
// This module is the frontend's single home for that plumbing, so a report view
// loads and exports through the registry instead of hardcoding a report id, an
// envelope read or an export path per report.
import { api, apiUrl, getToken } from '../api'

// Fallback currency for envelopes a builder did not stamp (the builders always
// set it from the group; kept defensive so readers never crash on a bare payload).
export const DEFAULT_REPORT_CURRENCY = 'usd'

// The shared report envelope every registry builder adds: when the numbers were
// generated and in which currency they are expressed.
export function reportEnvelope(report) {
  const r = report || {}
  return { generatedAt: r.generatedAt || null, currency: r.currency || DEFAULT_REPORT_CURRENCY }
}

// Load one registered report by id through the backend registry
// (GET /api/v1/reports/<id>). The response carries the shared envelope.
export async function loadReport(id) {
  return api.getReport(id)
}

// Export a registered report's CSV (GET /api/v1/reports/<id>.csv -> text/csv) by
// turning the response into a browser download. The filename comes from the
// response's Content-Disposition, falling back to one derived from the id.
export async function downloadReportCsv(id) {
  const res = await fetch(apiUrl('/reports/' + encodeURIComponent(id) + '.csv'), {
    headers: getToken() ? { Authorization: getToken() } : {},
  })
  if (!res.ok) throw new Error('failed')
  const cd = res.headers.get('Content-Disposition') || ''
  const m = cd.match(/filename="?([^";]+)"?/)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = m ? m[1] : 'homehoard-' + id + '-report.csv'
  a.click()
  URL.revokeObjectURL(url)
}
