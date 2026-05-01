/**
 * OpportunityPanel.tsx — UX Phase 3
 *
 * Map-first interface with NLP search, dual mode (investor/operator),
 * narrative property cards, and progressive disclosure.
 *
 * Test 60s goal: user finds "casa Maipú score alto" in <60 seconds without instructions.
 */

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import DeckGL from '@deck.gl/react'
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { Map as MapLibre } from 'react-map-gl/maplibre'
import { Search, AlertTriangle, X, Download, MapPin, TrendingUp, Briefcase, Home } from 'lucide-react'
import { clsx } from 'clsx'
import 'maplibre-gl/dist/maplibre-gl.css'

const API = 'http://localhost:8000'

const INITIAL_VIEW = {
  longitude: -70.67,
  latitude:  -33.45,
  zoom:       11,
  pitch:      0,
  bearing:    0,
}

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

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
  p50_uf: number
  p75_uf: number
  valuation_confidence: number
  drivers: Record<string, unknown>
}

const COMMUNES = [
  'Maipú', 'La Florida', 'Ñuñoa', 'Santiago', 'Providencia', 'Las Condes',
  'Vitacura', 'San Bernardo', 'Puente Alto', 'Quilicura', 'Peñalolén',
  'La Pintana', 'El Bosque', 'Recoleta', 'Conchalí', 'Lo Barnechea',
  'Pudahuel', 'Macul', 'Cerro Navia', 'Renca', 'Estación Central',
  'Quinta Normal', 'San Miguel', 'La Cisterna', 'Huechuraba',
]

const PROPERTY_LABELS: Record<string, string> = {
  apartment:   'departamento',
  house:       'casa',
  land:        'terreno',
  retail:      'local',
  office:      'oficina',
  warehouse:   'bodega',
  industrial:  'industrial',
}

interface ParsedQuery {
  property_type?: string
  commune?: string
  max_price?: number
  min_score?: number
  search_text: string
}

function parseNLPQuery(input: string): ParsedQuery {
  const lower = input.toLowerCase().trim()
  const result: ParsedQuery = { search_text: input }

  // Property type
  if (/depart|apto|depto/.test(lower)) result.property_type = 'apartment'
  else if (/casa\b/.test(lower)) result.property_type = 'house'
  else if (/terren/.test(lower)) result.property_type = 'land'
  else if (/local|comerc/.test(lower)) result.property_type = 'retail'
  else if (/oficin/.test(lower)) result.property_type = 'office'
  else if (/bodeg/.test(lower)) result.property_type = 'warehouse'

  // Commune (fuzzy)
  for (const c of COMMUNES) {
    const cl = c.toLowerCase().normalize('NFD').replace(/[̀-ͯ]/g, '')
    const lowerNorm = lower.normalize('NFD').replace(/[̀-ͯ]/g, '')
    if (lowerNorm.includes(cl)) { result.commune = c; break }
  }

  // Max price
  const priceMatch = lower.match(/menos de (\d+)\s*(k|mil)?/i)
  if (priceMatch) {
    let v = parseInt(priceMatch[1], 10)
    if (priceMatch[2]) v *= 1000
    result.max_price = v
  }

  // Score
  if (/score alto|alta oportunidad|top|excelente/.test(lower)) result.min_score = 0.75
  else if (/score medio|buena oportunidad/.test(lower)) result.min_score = 0.6
  else if (/score|oportunidad/.test(lower)) result.min_score = 0.5

  return result
}

function scoreColor(score: number): [number, number, number, number] {
  if (score >= 0.75) return [34, 197, 94, 220]   // green
  if (score >= 0.60) return [234, 179, 8, 220]   // yellow
  return [239, 68, 68, 200]                       // red
}

function scoreColorHex(score: number): string {
  if (score >= 0.75) return '#22c55e'
  if (score >= 0.60) return '#eab308'
  return '#ef4444'
}

function fmtUF(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(Number(v))) return '—'
  const n = Number(v)
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k UF`
  return `${Math.round(n).toLocaleString('es-CL')} UF`
}

function fmtUFFull(v: number | null | undefined): string {
  if (v === null || v === undefined || isNaN(Number(v))) return '—'
  return `${Math.round(Number(v)).toLocaleString('es-CL')} UF`
}

function NarrativeCard({ candidate, mode, onClose }: { candidate: Candidate; mode: 'investor' | 'operator'; onClose: () => void }) {
  const drivers = (candidate.drivers ?? {}) as Record<string, unknown>
  const gapPct = drivers.gap_pct as number | null
  const nCompetitors = drivers.n_competitors_2km as number | undefined ?? drivers[`n_competitors_${candidate.property_type_code}`]
  const isEriazo = candidate.is_eriazo

  // Build narrative
  const parts: string[] = []
  if (gapPct && Number(gapPct) < 0) {
    parts.push(`**${Math.abs(Number(gapPct)).toFixed(0)}% bajo el valor de mercado**`)
  }
  if (candidate.estimated_uf) {
    parts.push(`Comparables similares en la zona se venden entre **${fmtUFFull(candidate.p25_uf)} y ${fmtUFFull(candidate.p75_uf)}**`)
  }
  if (isEriazo) parts.push('Sitio subutilizado — alto potencial de redesarrollo')
  if (typeof nCompetitors === 'number' && mode === 'operator') {
    parts.push(`${nCompetitors} competidores en radio 2km`)
  }

  const propTypeES = PROPERTY_LABELS[candidate.property_type_code] || candidate.property_type_code
  const surfaceM2 = candidate.surface_building_m2 || candidate.surface_land_m2

  const ddItems = mode === 'operator' ? [
    'Verificar uso permitido en plan regulador comunal (DOM)',
    'Solicitar certificado de informaciones previas',
    'Revisar zonificación y restricciones',
    'Cotizar tasación independiente (Tinsa / GPS Property)',
    'Confirmar cap rate con corredor comercial local',
  ] : [
    'Solicitar certificado de hipotecas y gravámenes (CBR)',
    'Verificar estado de dominio y deudas tributarias (SII)',
    'Tasación independiente',
    'Inspección física de la propiedad',
  ]

  const gmaps = `https://maps.google.com/?q=${candidate.latitude},${candidate.longitude}`

  return (
    <div className="absolute right-0 top-0 bottom-0 w-96 bg-gray-950 border-l border-gray-800 overflow-y-auto z-20 flex flex-col">
      {/* Header */}
      <div className="flex items-start justify-between p-4 border-b border-gray-800">
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{propTypeES}</div>
          <h3 className="text-white text-base font-semibold truncate">{candidate.county_name}</h3>
          <div className="text-xs text-gray-500 mt-1">{Math.round(surfaceM2 || 0).toLocaleString('es-CL')} m²</div>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white p-1">
          <X size={16} />
        </button>
      </div>

      {/* Score badge */}
      <div className="p-4 border-b border-gray-800">
        <div className="flex items-baseline gap-3">
          <div className="text-4xl font-bold" style={{ color: scoreColorHex(candidate.opportunity_score) }}>
            {Math.round(candidate.opportunity_score * 100)}
          </div>
          <div>
            <div className="text-xs text-gray-400">de oportunidad</div>
            <div className="text-xs font-medium" style={{ color: scoreColorHex(candidate.opportunity_score) }}>
              {candidate.opportunity_score >= 0.75 ? 'Alta' : candidate.opportunity_score >= 0.60 ? 'Media' : 'Baja'}
            </div>
          </div>
        </div>
      </div>

      {/* Risks first */}
      <div className="p-4 border-b border-gray-800">
        <div className="text-xs font-semibold text-gray-300 mb-2 flex items-center gap-1.5">
          <AlertTriangle size={12} className="text-yellow-500" />
          Antes de comprar, verifica
        </div>
        <ul className="space-y-1.5 text-xs text-gray-400">
          {(candidate.valuation_confidence ?? 0) < 0.5 && (
            <li className="flex gap-2"><span className="text-yellow-500">•</span> Confianza valoración baja — pocos comparables en zona</li>
          )}
          {!candidate.estimated_uf && (
            <li className="flex gap-2"><span className="text-yellow-500">•</span> Sin valoración triangulada — datos parciales</li>
          )}
          <li className="flex gap-2"><span className="text-gray-600">•</span> Plan regulador no integrado al modelo aún</li>
          {mode === 'operator' && (
            <li className="flex gap-2"><span className="text-yellow-500">•</span> Cap rate referencial — validar con tasador</li>
          )}
        </ul>
      </div>

      {/* Price band */}
      {candidate.estimated_uf && (
        <div className="p-4 border-b border-gray-800">
          <div className="text-xs font-semibold text-gray-300 mb-2">Precio justo según comparables</div>
          <div className="text-2xl font-bold text-white mb-1">{fmtUFFull(candidate.estimated_uf)}</div>
          <div className="text-xs text-gray-500 mb-3">central · banda p25-p75</div>

          {/* Visual band */}
          <div className="relative h-2 bg-gray-800 rounded-full mb-1">
            <div
              className="absolute h-full bg-blue-600 rounded-full"
              style={{ left: '25%', width: '50%' }}
            />
            <div
              className="absolute w-3 h-3 bg-white rounded-full -top-0.5 border-2 border-blue-400"
              style={{ left: 'calc(50% - 6px)' }}
            />
          </div>
          <div className="flex justify-between text-xs text-gray-500">
            <span>{fmtUF(candidate.p25_uf)}</span>
            <span>{fmtUF(candidate.p75_uf)}</span>
          </div>
        </div>
      )}

      {/* Operator-only: Max payable */}
      {mode === 'operator' && candidate.max_payable_uf && (
        <div className="p-4 border-b border-gray-800 bg-amber-950/20">
          <div className="text-xs font-semibold text-amber-500 mb-1 flex items-center gap-1">
            <Briefcase size={12} /> Máximo pagable como operador
          </div>
          <div className="text-xl font-bold text-amber-400 mb-1">{fmtUFFull(candidate.max_payable_uf)}</div>
          <div className="text-xs text-gray-500">
            Estimación cap inverso. Cap rate referencial — INFO_NO_FIDEDIGNA, validar con asesor.
          </div>
        </div>
      )}

      {/* Tesis */}
      <div className="p-4 border-b border-gray-800">
        <div className="text-xs font-semibold text-gray-300 mb-2 flex items-center gap-1.5">
          <TrendingUp size={12} className="text-green-500" />
          Por qué es oportunidad
        </div>
        <div className="space-y-2 text-xs text-gray-300 leading-relaxed">
          {parts.length === 0 ? (
            <p className="text-gray-500">Score basado en valoración hedónica + comparables zonales.</p>
          ) : (
            parts.map((p, i) => (
              <p key={i} dangerouslySetInnerHTML={{ __html: p.replace(/\*\*(.+?)\*\*/g, '<strong class="text-white">$1</strong>') }} />
            ))
          )}
        </div>
      </div>

      {/* Due diligence */}
      <div className="p-4 border-b border-gray-800">
        <div className="text-xs font-semibold text-gray-300 mb-2">Próximos pasos</div>
        <ul className="space-y-1.5">
          {ddItems.map((item, i) => (
            <li key={i} className="text-xs text-gray-400 flex items-start gap-2">
              <span className="mt-0.5 w-3 h-3 rounded border border-gray-700 flex-shrink-0" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </div>

      {/* Actions */}
      <div className="p-4 mt-auto flex gap-2 flex-wrap">
        <a
          href={gmaps}
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs bg-blue-600 hover:bg-blue-500 text-white px-3 py-1.5 rounded font-medium"
        >
          Ver en mapa
        </a>
        <button className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded">
          Guardar
        </button>
        <button className="text-xs bg-gray-800 hover:bg-gray-700 text-gray-300 px-3 py-1.5 rounded">
          PDF
        </button>
      </div>
    </div>
  )
}

export function OpportunityPanel() {
  const [searchInput, setSearchInput] = useState('')
  const [mode, setMode]               = useState<'investor' | 'operator'>('investor')
  const [useCase, setUseCase]         = useState('as_is')
  const [scoreFilter, setScoreFilter] = useState<'all' | 'top' | 'high'>('all')
  const [selected, setSelected]       = useState<Candidate | null>(null)
  const [viewState, setViewState]     = useState(INITIAL_VIEW)

  const parsed = useMemo(() => parseNLPQuery(searchInput), [searchInput])

  const scoreMin = scoreFilter === 'top' ? 0.75 : scoreFilter === 'high' ? 0.6 : 0.5
  const profile  = mode === 'operator' ? 'operator' : 'value'

  const queryParams = new URLSearchParams({
    use_case: useCase,
    profile,
    score_min: (parsed.min_score ?? scoreMin).toString(),
    limit: '300',
    ...(parsed.commune && { commune: parsed.commune }),
    ...(parsed.property_type && { property_type: parsed.property_type }),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['opp-v3', useCase, profile, parsed.commune, parsed.property_type, parsed.min_score ?? scoreMin],
    queryFn: async () => {
      const r = await fetch(`${API}/opportunity/candidates?${queryParams}`)
      return r.json()
    },
  })

  const items: Candidate[] = (data?.items ?? []).filter((c: Candidate) =>
    c.latitude && c.longitude && (!parsed.max_price || (c.estimated_uf ?? 0) <= parsed.max_price)
  )

  const layers = [
    new ScatterplotLayer({
      id: 'opp-pins',
      data: items,
      getPosition: (d: Candidate) => [d.longitude, d.latitude],
      getRadius: (d: Candidate) => Math.max(60, Math.min(200, Math.sqrt((d.surface_land_m2 ?? 100)) * 4)),
      getFillColor: (d: Candidate) => scoreColor(d.opportunity_score),
      getLineColor: [255, 255, 255, 255],
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: true,
      onClick: ({ object }: { object: Candidate }) => setSelected(object),
      radiusUnits: 'meters',
      radiusMinPixels: 4,
      radiusMaxPixels: 16,
    }),
    new TextLayer({
      id: 'opp-prices',
      data: items.filter((_, i) => i < 50),
      getPosition: (d: Candidate) => [d.longitude, d.latitude],
      getText: (d: Candidate) => fmtUF(d.estimated_uf),
      getColor: [255, 255, 255, 220],
      getSize: 11,
      sizeUnits: 'pixels',
      getPixelOffset: [0, -16],
      background: true,
      backgroundPadding: [3, 1],
      getBackgroundColor: [10, 10, 30, 180],
      fontFamily: 'system-ui',
      fontWeight: 600,
    }),
  ]

  return (
    <div className="relative h-full w-full bg-gray-950">
      {/* Map */}
      <DeckGL
        initialViewState={viewState}
        controller={true}
        layers={layers}
        onViewStateChange={({ viewState: v }) => setViewState(v as typeof INITIAL_VIEW)}
        getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'grab')}
      >
        <MapLibre mapStyle={MAP_STYLE} reuseMaps />
      </DeckGL>

      {/* Search bar — top center */}
      <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 w-full max-w-2xl px-4">
        <div className="relative">
          <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-gray-500" />
          <input
            type="text"
            placeholder='Busca: "casa Maipú score alto" o "terreno menos de 5000 UF"'
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            className="w-full bg-gray-900/95 backdrop-blur text-white text-sm pl-11 pr-10 py-3 rounded-full border border-gray-700 focus:border-blue-500 focus:outline-none shadow-lg"
          />
          {searchInput && (
            <button
              onClick={() => setSearchInput('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-white"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Active filter chips */}
        {(parsed.commune || parsed.property_type || parsed.max_price || parsed.min_score) && (
          <div className="flex gap-2 mt-2 flex-wrap">
            {parsed.commune && <Chip label={`📍 ${parsed.commune}`} />}
            {parsed.property_type && <Chip label={`🏠 ${PROPERTY_LABELS[parsed.property_type]}`} />}
            {parsed.max_price && <Chip label={`< ${parsed.max_price.toLocaleString('es-CL')} UF`} />}
            {parsed.min_score && <Chip label={`★ ${Math.round(parsed.min_score * 100)}+`} />}
          </div>
        )}
      </div>

      {/* Mode toggle — top left */}
      <div className="absolute top-4 left-4 z-10 bg-gray-900/95 backdrop-blur rounded-full p-1 border border-gray-800 flex gap-1 shadow-lg">
        <button
          onClick={() => { setMode('investor'); setUseCase('as_is') }}
          className={clsx(
            'px-3 py-1.5 rounded-full text-xs font-medium flex items-center gap-1.5 transition-colors',
            mode === 'investor' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white'
          )}
        >
          <Home size={12} /> Inversión
        </button>
        <button
          onClick={() => { setMode('operator'); setUseCase('gas_station') }}
          className={clsx(
            'px-3 py-1.5 rounded-full text-xs font-medium flex items-center gap-1.5 transition-colors',
            mode === 'operator' ? 'bg-amber-600 text-white' : 'text-gray-400 hover:text-white'
          )}
        >
          <Briefcase size={12} /> Operador
        </button>
      </div>

      {/* Quick filters — bottom center */}
      <div className="absolute bottom-4 left-1/2 -translate-x-1/2 z-10 flex gap-2">
        {mode === 'operator' && (
          <select
            value={useCase}
            onChange={e => setUseCase(e.target.value)}
            className="bg-gray-900/95 backdrop-blur text-white text-xs px-3 py-2 rounded-full border border-gray-800 shadow-lg"
          >
            <option value="gas_station">⛽ Estación servicio</option>
            <option value="pharmacy">💊 Farmacia</option>
            <option value="supermarket">🛒 Supermercado</option>
            <option value="bank_branch">🏦 Banco</option>
            <option value="clinic">🏥 Clínica</option>
            <option value="restaurant">🍽 Restaurante</option>
          </select>
        )}

        <div className="bg-gray-900/95 backdrop-blur rounded-full p-1 border border-gray-800 flex gap-1 shadow-lg">
          {(['all', 'high', 'top'] as const).map(f => (
            <button
              key={f}
              onClick={() => setScoreFilter(f)}
              className={clsx(
                'px-3 py-1.5 rounded-full text-xs font-medium',
                scoreFilter === f ? 'bg-white text-black' : 'text-gray-400 hover:text-white'
              )}
            >
              {f === 'all' ? 'Cualquiera' : f === 'high' ? '⭐ Buena' : '🔥 Top'}
            </button>
          ))}
        </div>
      </div>

      {/* Results count + CSV — bottom left */}
      <div className="absolute bottom-4 left-4 z-10 flex items-center gap-2 bg-gray-900/95 backdrop-blur rounded-full px-4 py-2 border border-gray-800 shadow-lg">
        <span className="text-xs text-gray-400">
          {isLoading ? 'Cargando...' : `${items.length.toLocaleString('es-CL')} oportunidades`}
        </span>
        <button
          onClick={() => {
            if (!items.length) return
            const headers = ['comuna','tipo','score','estimado_uf','max_pagable_uf','m2','lat','lon']
            const rows = items.map(c => [
              c.county_name, c.property_type_code,
              c.opportunity_score?.toFixed(3),
              c.estimated_uf ? Math.round(c.estimated_uf) : '',
              c.max_payable_uf ? Math.round(c.max_payable_uf) : '',
              c.surface_land_m2 ? Math.round(c.surface_land_m2) : '',
              c.latitude, c.longitude,
            ])
            const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
            const blob = new Blob([csv], { type: 'text/csv' })
            const url = URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `oportunidades_${new Date().toISOString().slice(0,10)}.csv`
            a.click()
            URL.revokeObjectURL(url)
          }}
          className="text-gray-500 hover:text-green-400 transition-colors"
          title="Exportar CSV"
        >
          <Download size={12} />
        </button>
      </div>

      {/* Legend — bottom right */}
      <div className="absolute bottom-4 right-4 z-10 bg-gray-900/95 backdrop-blur rounded-lg p-3 border border-gray-800 text-xs space-y-1 shadow-lg">
        <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-green-500" /> Alta oportunidad</div>
        <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500" /> Media</div>
        <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Baja</div>
      </div>

      {/* Footer — versioning */}
      <div className="absolute bottom-1 right-1 text-[10px] text-gray-700 z-10">
        data v3.2 · model v1.0
      </div>

      {/* Detail panel */}
      {selected && (
        <NarrativeCard candidate={selected} mode={mode} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}

function Chip({ label }: { label: string }) {
  return (
    <span className="text-xs px-2.5 py-1 rounded-full bg-gray-800/95 text-gray-300 border border-gray-700">
      {label}
    </span>
  )
}
