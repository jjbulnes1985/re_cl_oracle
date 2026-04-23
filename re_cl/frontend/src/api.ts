import type {
  Property, PropertyDetail, CommuneStat, CommuneEnriched, ScoreSummary,
  ProfileInfo, ScoreRequest, ScoredProperty, AuthToken, AuthUser, SavedSearch,
} from './types'

const BASE = '/api'

async function get<T>(path: string, params?: Record<string, string | number | boolean>): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API ${path}: ${res.status} ${res.statusText}`)
  return res.json()
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(`API ${path}: ${res.status} ${res.statusText}`)
  return res.json()
}

// ── Properties ───────────────────────────────────────────────────────────────

export const fetchProperties = (params: {
  project_type?: string
  county_name?: string
  min_score?: number
  max_score?: number
  limit?: number
  offset?: number
}): Promise<Property[]> =>
  get('/properties', params as Record<string, string | number>)

export const fetchProperty = (id: number): Promise<PropertyDetail> =>
  get(`/properties/${id}`)

export const fetchPropertyById = (scoreId: number): Promise<Property> =>
  get(`/properties/${scoreId}`)

export const fetchCommunes = (): Promise<CommuneStat[]> =>
  get('/properties/communes')

export const fetchCommunesEnriched = (): Promise<CommuneEnriched[]> =>
  get('/properties/communes/enriched')

// ── Scores ───────────────────────────────────────────────────────────────────

export const fetchScoreSummary = (): Promise<ScoreSummary> =>
  get('/scores/summary')

export const fetchTopScores = (n: number = 10, project_type?: string): Promise<ScoredProperty[]> =>
  get('/scores/top', { n, ...(project_type ? { project_type } : {}) })

// ── Profiles ─────────────────────────────────────────────────────────────────

export const fetchProfiles = (): Promise<ProfileInfo[]> =>
  get('/profiles')

export const scoreWithProfile = (req: ScoreRequest): Promise<ScoredProperty[]> =>
  post('/profiles/score', req)

// ── Health ───────────────────────────────────────────────────────────────────

export const fetchHealth = (): Promise<{ status: string; model_version: string }> =>
  get('/health')

// ── Analytics ────────────────────────────────────────────────────────────────

export interface PriceTrendPoint {
  year: number
  quarter: number
  period: string
  median_uf_m2: number
  mean_uf_m2: number
  p25_uf_m2?: number
  p75_uf_m2?: number
  n_transactions: number
}

export async function fetchPriceTrend(params?: {
  project_type?: string
  county_name?: string
}): Promise<PriceTrendPoint[]> {
  const q = new URLSearchParams()
  if (params?.project_type) q.set('project_type', params.project_type)
  if (params?.county_name) q.set('county_name', params.county_name)
  const r = await fetch(`${BASE}/analytics/price-trend?${q}`)
  if (!r.ok) return []
  return r.json()
}

export async function fetchPriceTrendByCommune(
  communes: string[]
): Promise<Array<{ county_name: string; trend: PriceTrendPoint[] }>> {
  const results = await Promise.all(
    communes.map((c) =>
      fetchPriceTrend({ county_name: c }).then((trend) => ({ county_name: c, trend }))
    )
  )
  return results
}

export async function fetchScoreDistribution(): Promise<
  { decile: number; n: number; mean_score: number; mean_gap_pct: number }[]
> {
  const r = await fetch(`${BASE}/analytics/score-distribution`)
  if (!r.ok) return []
  return r.json()
}

export async function fetchPropertiesWithCount(
  params: Parameters<typeof fetchProperties>[0]
): Promise<{ data: Property[]; total: number }> {
  const url = new URL(`${BASE}/properties`, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) url.searchParams.set(k, String(v))
    })
  }
  const res = await fetch(url.toString())
  if (!res.ok) throw new Error(`API /properties: ${res.status}`)
  const total = parseInt(res.headers.get('X-Total-Count') ?? '0', 10)
  const data: Property[] = await res.json()
  return { data, total }
}

// ── OSM / POI layers ─────────────────────────────────────────────────────────

export interface BusStop {
  stop_id: string
  name: string
  lat: number
  lon: number
}

export async function fetchBusStops(): Promise<BusStop[]> {
  const r = await fetch(`${BASE}/properties/osm/bus-stops`)
  if (!r.ok) return []
  return r.json()
}

// ── Search ───────────────────────────────────────────────────────────────────

export const searchProperties = (q: string, params?: { min_score?: number; limit?: number }): Promise<Property[]> =>
  get('/properties/search', { q, ...params } as Record<string, string | number>)

// ── Comparables ──────────────────────────────────────────────────────────────

export async function fetchComparables(scoreId: number, n = 5): Promise<Property[]> {
  const url = new URL(`${BASE}/properties/${scoreId}/comparables`, window.location.origin)
  url.searchParams.set('n', String(n))
  const r = await fetch(url.toString())
  if (!r.ok) return []
  return r.json()
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export async function authRegister(
  email: string, password: string
): Promise<{ ok: true; token: AuthToken } | { ok: false; error: string }> {
  const res = await fetch(`${BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.ok) return { ok: true, token: await res.json() }
  const body = await res.json().catch(() => ({}))
  return { ok: false, error: body.detail ?? `Error ${res.status}` }
}

export async function authLogin(
  email: string, password: string
): Promise<{ ok: true; token: AuthToken } | { ok: false; error: string }> {
  const res = await fetch(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (res.ok) return { ok: true, token: await res.json() }
  const body = await res.json().catch(() => ({}))
  return { ok: false, error: body.detail ?? `Error ${res.status}` }
}

export async function authMe(token: string): Promise<AuthUser> {
  const res = await fetch(`${BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Unauthorized')
  return res.json()
}

export async function fetchSavedSearches(token: string): Promise<SavedSearch[]> {
  const res = await fetch(`${BASE}/searches`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) return []
  return res.json()
}

export async function createSavedSearch(
  token: string, name: string, filters: Record<string, unknown>
): Promise<SavedSearch> {
  const res = await fetch(`${BASE}/searches`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${token}` },
    body: JSON.stringify({ name, filters }),
  })
  if (!res.ok) throw new Error(`Error ${res.status}`)
  return res.json()
}

export async function deleteSavedSearch(token: string, id: number): Promise<void> {
  await fetch(`${BASE}/searches/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
}

export function exportPropertiesCSV(params: {
  min_score?: number
  county_name?: string
  project_type?: string
  limit?: number
} = {}): void {
  const url = new URL(`${BASE}/properties/export`, window.location.origin)
  url.searchParams.set('format', 'csv')
  if (params.min_score !== undefined) url.searchParams.set('min_score', String(params.min_score))
  if (params.county_name) url.searchParams.set('county_name', params.county_name)
  if (params.project_type) url.searchParams.set('project_type', params.project_type)
  if (params.limit !== undefined) url.searchParams.set('limit', String(params.limit))
  // Trigger download via anchor element
  const a = document.createElement('a')
  a.href = url.toString()
  a.download = `re_cl_oportunidades.csv`
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
}
