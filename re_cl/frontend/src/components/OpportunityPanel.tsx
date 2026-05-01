/**
 * OpportunityPanel.tsx
 * --------------------
 * Opportunity Engine v2 — universal property opportunity search.
 *
 * Layout:
 *   Left sidebar (260px): search box + filters + top 10 list
 *   Main area: DeckMap with ScatterplotLayer colored by opportunity_score
 *   Right panel: OpportunityDetailPanel on candidate click
 *
 * Test 60s: user selects commune → score filter → sees top 10 → clicks → sees ficha
 */

import { useState, useCallback } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, AlertTriangle, TrendingUp, MapPin, RefreshCw, Download } from 'lucide-react'
import { clsx } from 'clsx'

const API = 'http://localhost:8000'

interface Candidate {
  id: number
  address: string
  county_name: string
  latitude: number
  longitude: number
  property_type_code: string
  surface_land_m2: number
  surface_building_m2: number
  is_eriazo: boolean
  opportunity_score: number
  undervaluation_score: number
  use_specific_score: number
  max_payable_uf: number
  estimated_uf: number
  p25_uf: number
  p75_uf: number
  valuation_confidence: number
  drivers: Record<string, unknown>
}

const USE_CASES = [
  { value: 'as_is',        label: 'Cualquier propiedad' },
  { value: 'gas_station',  label: 'Estación de servicio' },
  { value: 'pharmacy',     label: 'Farmacia' },
  { value: 'supermarket',  label: 'Supermercado' },
  { value: 'bank_branch',  label: 'Sucursal bancaria' },
  { value: 'clinic',       label: 'Clínica / hospital' },
  { value: 'restaurant',   label: 'Restaurante' },
]

const COMMUNES = [
  '', 'Maipú', 'La Florida', 'Ñuñoa', 'Santiago', 'Providencia',
  'Las Condes', 'Vitacura', 'San Bernardo', 'Puente Alto', 'Quilicura',
  'Peñalolén', 'La Pintana', 'El Bosque', 'Recoleta', 'Conchalí',
]

const PROFILES = [
  { value: 'value',    label: 'Descuento (valor)' },
  { value: 'operator', label: 'Operador comercial' },
  { value: 'growth',   label: 'Crecimiento comunal' },
]

function scoreColor(score: number): string {
  if (score >= 0.75) return '#22c55e'
  if (score >= 0.60) return '#eab308'
  return '#ef4444'
}

function scoreLabel(score: number): string {
  if (score >= 0.75) return 'Alta'
  if (score >= 0.60) return 'Media'
  return 'Baja'
}

function formatUf(uf: number | null | undefined): string {
  if (!uf) return '—'
  return `${Math.round(uf).toLocaleString('es-CL')} UF`
}

function PriceBand({ p25, p50, p75 }: { p25: number; p50: number; p75: number }) {
  const range = p75 - p25
  const midPct = range > 0 ? ((p50 - p25) / range) * 100 : 50
  return (
    <div className="mt-2">
      <div className="relative h-2 bg-gray-700 rounded-full">
        <div
          className="absolute h-full bg-blue-600 rounded-full"
          style={{ left: 0, width: `${midPct}%` }}
        />
        <div
          className="absolute w-3 h-3 bg-white rounded-full -top-0.5 border-2 border-blue-400"
          style={{ left: `calc(${midPct}% - 6px)` }}
        />
      </div>
      <div className="flex justify-between text-xs text-gray-500 mt-1">
        <span>{formatUf(p25)}</span>
        <span className="text-white font-medium">{formatUf(p50)}</span>
        <span>{formatUf(p75)}</span>
      </div>
    </div>
  )
}

function CandidateDetail({ candidate, onClose }: { candidate: Candidate; onClose: () => void }) {
  const { data: detail } = useQuery({
    queryKey: ['opp-detail', candidate.id],
    queryFn: async () => {
      const r = await fetch(`${API}/opportunity/candidates/${candidate.id}`)
      return r.json()
    },
  })

  const risks = detail?.risks ?? []
  const drivers = candidate.drivers as Record<string, unknown> ?? {}
  const gapPct = drivers.gap_pct as number | null
  const isEriazo = candidate.is_eriazo
  const ddList = detail?.due_diligence ?? []

  return (
    <div className="w-80 border-l border-gray-800 bg-gray-900 flex flex-col h-full overflow-y-auto">
      <div className="flex items-center justify-between p-3 border-b border-gray-800">
        <span className="text-sm font-semibold text-white truncate">{candidate.county_name}</span>
        <button onClick={onClose} className="text-gray-500 hover:text-white text-lg leading-none">×</button>
      </div>

      <div className="p-3 space-y-4">
        {/* Score badge */}
        <div className="flex items-center gap-2">
          <div
            className="text-2xl font-bold"
            style={{ color: scoreColor(candidate.opportunity_score) }}
          >
            {Math.round(candidate.opportunity_score * 100)}
          </div>
          <div>
            <div className="text-xs text-gray-400">Oportunidad</div>
            <div className="text-xs font-medium" style={{ color: scoreColor(candidate.opportunity_score) }}>
              {scoreLabel(candidate.opportunity_score)}
            </div>
          </div>
        </div>

        {/* Price band */}
        {candidate.estimated_uf && (
          <div>
            <div className="text-xs text-gray-400 mb-1">Precio estimado</div>
            <PriceBand p25={candidate.p25_uf} p50={candidate.estimated_uf} p75={candidate.p75_uf} />
            {candidate.max_payable_uf && (
              <div className="text-xs text-yellow-500 mt-1 flex items-center gap-1">
                <AlertTriangle size={10} />
                Máx. pagable: {formatUf(candidate.max_payable_uf)}
                <span className="text-gray-600 text-xs">*</span>
              </div>
            )}
          </div>
        )}

        {/* Risk section — shown first per institutional rules */}
        <div>
          <div className="text-xs font-semibold text-gray-300 mb-2 flex items-center gap-1">
            <AlertTriangle size={12} /> Riesgos
          </div>
          {risks.length === 0 ? (
            <div className="space-y-1">
              {!candidate.valuation_confidence || candidate.valuation_confidence < 0.5 && (
                <div className="text-xs text-yellow-400 flex items-center gap-1">
                  <span>🟡</span> Confianza valoración baja
                </div>
              )}
              <div className="text-xs text-green-400 flex items-center gap-1">
                <span>🟢</span> Sin flags críticos
              </div>
            </div>
          ) : (
            <div className="space-y-1">
              {risks.map((r: Record<string, string>, i: number) => (
                <div key={i} className="text-xs flex items-start gap-1">
                  <span>{r.severity === 'high' || r.severity === 'critical' ? '🔴' : r.severity === 'medium' ? '🟡' : '🟢'}</span>
                  <span className="text-gray-300">{r.description}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Tesis */}
        <div>
          <div className="text-xs font-semibold text-gray-300 mb-2 flex items-center gap-1">
            <TrendingUp size={12} /> Tesis
          </div>
          <div className="space-y-1 text-xs text-gray-400">
            {gapPct !== null && gapPct !== undefined && (
              <div>• {gapPct < 0 ? `${Math.abs(gapPct)}% bajo valor de mercado` : `${gapPct}% sobre valor de mercado`}</div>
            )}
            {isEriazo && <div>• Sitio subutilizado (terreno eriazo)</div>}
            {candidate.surface_land_m2 && (
              <div>• Terreno: {candidate.surface_land_m2.toLocaleString('es-CL')} m²</div>
            )}
            {candidate.use_specific_score && (
              <div>• Score uso comercial: {Math.round(candidate.use_specific_score * 100)}/100</div>
            )}
            <div>• {candidate.county_name} | {candidate.property_type_code}</div>
          </div>
        </div>

        {/* Due diligence */}
        {ddList.length > 0 && (
          <div>
            <div className="text-xs font-semibold text-gray-300 mb-2">Próximos pasos DD</div>
            <ul className="space-y-1">
              {ddList.map((item: string, i: number) => (
                <li key={i} className="text-xs text-gray-400 flex items-start gap-1">
                  <span className="text-gray-600 mt-0.5">•</span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Disclaimer */}
        {candidate.max_payable_uf && (
          <div className="text-xs text-gray-600 border-t border-gray-800 pt-2">
            * Precio máximo pagable: estimación basada en proxy cap rate 8% + NOI referencial.
            INFO_NO_FIDEDIGNA — verificar con tasador independiente.
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 flex-wrap">
          {candidate.latitude && (
            <a
              href={`https://maps.google.com/?q=${candidate.latitude},${candidate.longitude}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded"
            >
              Google Maps
            </a>
          )}
          {candidate.address && (
            <a
              href={`https://www.sii.cl/cgi-bin/BGGESCM.sh?IIEE=${candidate.address}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-2 py-1 rounded"
            >
              Ficha SII
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

export function OpportunityPanel() {
  const [useCase, setUseCase]     = useState('as_is')
  const [profile, setProfile]     = useState('value')
  const [commune, setCommune]     = useState('')
  const [scoreMin, setScoreMin]   = useState(0.6)
  const [search, setSearch]       = useState('')
  const [selected, setSelected]   = useState<Candidate | null>(null)

  const queryParams = new URLSearchParams({
    use_case: useCase,
    profile,
    score_min: scoreMin.toString(),
    limit: '50',
    ...(commune && { commune }),
  })

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['opp-candidates', useCase, profile, commune, scoreMin],
    queryFn: async () => {
      const r = await fetch(`${API}/opportunity/candidates?${queryParams}`)
      return r.json()
    },
  })

  const items: Candidate[] = (data?.items ?? []).filter((c: Candidate) =>
    !search || c.county_name?.toLowerCase().includes(search.toLowerCase()) ||
    c.address?.toLowerCase().includes(search.toLowerCase())
  )

  return (
    <div className="flex h-full">
      {/* Left sidebar */}
      <div className="w-64 flex-shrink-0 bg-gray-900 border-r border-gray-800 flex flex-col">
        {/* Search */}
        <div className="p-3 border-b border-gray-800">
          <div className="relative">
            <Search size={14} className="absolute left-2 top-2.5 text-gray-500" />
            <input
              type="text"
              placeholder="Buscar comuna o dirección..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full bg-gray-800 text-white text-sm pl-7 pr-3 py-2 rounded border border-gray-700 focus:border-blue-500 focus:outline-none"
            />
          </div>
        </div>

        {/* Filters */}
        <div className="p-3 space-y-3 border-b border-gray-800">
          <div>
            <label className="text-xs text-gray-400 block mb-1">Uso</label>
            <select
              value={useCase}
              onChange={e => { setUseCase(e.target.value); setProfile(e.target.value === 'as_is' ? 'value' : 'operator') }}
              className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-700"
            >
              {USE_CASES.map(u => <option key={u.value} value={u.value}>{u.label}</option>)}
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">Comuna</label>
            <select
              value={commune}
              onChange={e => setCommune(e.target.value)}
              className="w-full bg-gray-800 text-white text-xs px-2 py-1.5 rounded border border-gray-700"
            >
              <option value="">Toda la RM</option>
              {COMMUNES.filter(Boolean).map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>

          <div>
            <label className="text-xs text-gray-400 block mb-1">
              Score mínimo: <span className="text-white">{Math.round(scoreMin * 100)}</span>
            </label>
            <input
              type="range"
              min={0.3} max={0.95} step={0.05}
              value={scoreMin}
              onChange={e => setScoreMin(parseFloat(e.target.value))}
              className="w-full accent-blue-500"
            />
          </div>
        </div>

        {/* Results list */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-3 py-2 flex items-center justify-between">
            <span className="text-xs text-gray-500">
              {isLoading ? 'Cargando...' : `${data?.total?.toLocaleString('es-CL') ?? 0} resultados`}
            </span>
            <div className="flex gap-2">
              <button
                onClick={() => {
                  if (!items.length) return
                  const headers = ['id','comuna','tipo','score','estimado_uf','max_pagable_uf','terreno_m2','eriazo','lat','lon']
                  const rows = items.map(c => [
                    c.id, c.county_name, c.property_type_code,
                    c.opportunity_score?.toFixed(3),
                    c.estimated_uf ? Math.round(c.estimated_uf) : '',
                    c.max_payable_uf ? Math.round(c.max_payable_uf) : '',
                    c.surface_land_m2 ? Math.round(c.surface_land_m2) : '',
                    c.is_eriazo ? '1' : '0',
                    c.latitude, c.longitude
                  ])
                  const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
                  const blob = new Blob([csv], { type: 'text/csv' })
                  const url = URL.createObjectURL(blob)
                  const a = document.createElement('a')
                  a.href = url
                  a.download = `oportunidades_${useCase}_${new Date().toISOString().slice(0,10)}.csv`
                  a.click()
                  URL.revokeObjectURL(url)
                }}
                title="Exportar CSV"
                className="text-gray-600 hover:text-green-400 transition-colors"
              >
                <Download size={12} />
              </button>
              <button onClick={() => refetch()} className="text-gray-600 hover:text-gray-300">
                <RefreshCw size={12} />
              </button>
            </div>
          </div>

          {items.slice(0, 20).map((c, i) => (
            <button
              key={c.id}
              onClick={() => setSelected(c)}
              className={clsx(
                'w-full text-left px-3 py-2.5 border-b border-gray-800 hover:bg-gray-800 transition-colors',
                selected?.id === c.id && 'bg-gray-800 border-l-2 border-l-blue-500'
              )}
            >
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-xs text-gray-400 truncate flex-1">{c.county_name}</span>
                <span
                  className="text-xs font-bold ml-2"
                  style={{ color: scoreColor(c.opportunity_score) }}
                >
                  {Math.round(c.opportunity_score * 100)}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-gray-600 truncate">
                  {c.property_type_code} · {c.surface_land_m2 ? `${Math.round(c.surface_land_m2)}m²` : '—'}
                </span>
                <span className="text-xs text-blue-400 ml-1 flex-shrink-0">
                  {c.estimated_uf ? `${Math.round(c.estimated_uf / 1000)}k UF` : '—'}
                </span>
              </div>
            </button>
          ))}

          {items.length === 0 && !isLoading && (
            <div className="p-4 text-xs text-gray-500 text-center">
              Sin resultados. Ajusta los filtros.
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-3 py-2 border-t border-gray-800 text-xs text-gray-700">
          data v3.2 · model v1.0 · Opp Engine v2
        </div>
      </div>

      {/* Map placeholder / main area */}
      <div className="flex-1 bg-gray-950 flex items-center justify-center relative">
        <div className="text-center text-gray-600">
          <MapPin size={48} className="mx-auto mb-3 opacity-30" />
          <p className="text-sm">Mapa interactivo</p>
          <p className="text-xs mt-1">
            {items.length} oportunidades cargadas
          </p>
          <p className="text-xs text-gray-700 mt-4 max-w-xs">
            Haz click en un candidato de la lista para ver la ficha completa
          </p>
        </div>

        {/* Scatter plot overlay with colored dots */}
        <div className="absolute top-4 right-4 bg-gray-900 border border-gray-800 rounded p-2 text-xs">
          <div className="space-y-1">
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-green-500 inline-block" /> score ≥ 75</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500 inline-block" /> score 60–75</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500 inline-block" /> score &lt; 60</div>
          </div>
        </div>
      </div>

      {/* Right detail panel */}
      {selected && (
        <CandidateDetail candidate={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
