/**
 * OpportunityPanel.tsx — UX Phase 4 (Simplificación Radical)
 *
 * Layout estilo Idealista:
 *   - Filter bar prominente arriba (chips dropdown explícitos)
 *   - Mapa fullscreen al centro
 *   - Lista lateral derecha con cards
 *   - Click en pin → preview tooltip → ficha 1 pantalla
 *
 * Test 3s: usuario sabe qué ve y dónde clicar
 * Test 30s: filtra y abre detalle
 */

import { useMemo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import DeckGL from '@deck.gl/react'
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { Map as MapLibre } from 'react-map-gl/maplibre'
import {
  AlertTriangle, X, Download, MapPin, Briefcase, Home, ChevronDown,
  Building2, Trees, Store, Factory, Filter, Save, FileText
} from 'lucide-react'
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
  county_name: string
  latitude: number
  longitude: number
  property_type_code: string
  surface_land_m2: number
  surface_building_m2: number
  is_eriazo: boolean
  opportunity_score: number
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
  'Quinta Normal', 'San Miguel', 'La Cisterna', 'Huechuraba', 'San Joaquín',
  'Lo Espejo', 'Pedro Aguirre Cerda', 'Lo Prado', 'San Ramón', 'La Granja',
  'Independencia', 'Cerrillos', 'Lampa', 'Colina', 'Buin', 'Melipilla',
  'Pirque', 'Talagante', 'Calera de Tango',
]

const PROPERTY_TYPES = [
  { code: 'house',      label: 'Casas',      icon: Home },
  { code: 'apartment',  label: 'Deptos',     icon: Building2 },
  { code: 'land',       label: 'Terrenos',   icon: Trees },
  { code: 'retail',     label: 'Locales',    icon: Store },
  { code: 'warehouse',  label: 'Bodegas',    icon: Factory },
]

const COMMERCIAL_USES = [
  { value: 'gas_station',  label: '⛽ Estación servicio' },
  { value: 'pharmacy',     label: '💊 Farmacia' },
  { value: 'supermarket',  label: '🛒 Supermercado' },
  { value: 'bank_branch',  label: '🏦 Banco' },
  { value: 'clinic',       label: '🏥 Clínica' },
  { value: 'restaurant',   label: '🍽 Restaurante' },
]

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

function scoreColor(score: number): [number, number, number, number] {
  if (score >= 0.75) return [34, 197, 94, 220]
  if (score >= 0.60) return [234, 179, 8, 220]
  return [239, 68, 68, 200]
}
function scoreColorHex(score: number): string {
  if (score >= 0.75) return '#22c55e'
  if (score >= 0.60) return '#eab308'
  return '#ef4444'
}
function scoreLabel(score: number): string {
  if (score >= 0.75) return 'Alta oportunidad'
  if (score >= 0.60) return 'Buena oportunidad'
  return 'Baja oportunidad'
}

function gapText(drivers: Record<string, unknown> | undefined): { text: string; color: string } {
  const gap = drivers?.gap_pct as number | null | undefined
  if (gap === null || gap === undefined) return { text: '—', color: '#666' }
  const g = Number(gap)
  if (g < 0) return { text: `${Math.abs(g).toFixed(0)}% bajo valor`, color: '#22c55e' }
  if (g > 0) return { text: `${g.toFixed(0)}% sobre valor`, color: '#ef4444' }
  return { text: 'En valor de mercado', color: '#888' }
}

// ── Filter components ──────────────────────────────────────────────────

interface FilterDropdownProps {
  label: string
  icon?: React.ReactNode
  isOpen: boolean
  onToggle: () => void
  children: React.ReactNode
  active?: boolean
  badge?: string
}
function FilterDropdown({ label, icon, isOpen, onToggle, children, active, badge }: FilterDropdownProps) {
  return (
    <div className="relative">
      <button
        onClick={onToggle}
        className={clsx(
          'flex items-center gap-2 px-4 py-2 rounded-full text-sm font-medium border transition-all',
          active
            ? 'bg-blue-600 text-white border-blue-500'
            : 'bg-gray-900 text-gray-300 border-gray-700 hover:border-gray-500 hover:text-white'
        )}
      >
        {icon}
        <span>{label}</span>
        {badge && <span className="text-xs opacity-80">· {badge}</span>}
        <ChevronDown size={14} className={clsx('transition-transform', isOpen && 'rotate-180')} />
      </button>
      {isOpen && (
        <>
          <div className="fixed inset-0 z-30" onClick={onToggle} />
          <div className="absolute top-full mt-2 left-0 z-40 bg-gray-900 border border-gray-700 rounded-xl shadow-2xl min-w-[280px] p-4">
            {children}
          </div>
        </>
      )}
    </div>
  )
}

// ── Property card (sidebar list) ────────────────────────────────────────

function PropertyCard({ candidate, onClick, isHovered }: { candidate: Candidate; onClick: () => void; isHovered?: boolean }) {
  const gap = gapText(candidate.drivers)
  const propType = PROPERTY_TYPES.find(p => p.code === candidate.property_type_code)
  const Icon = propType?.icon ?? Home

  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left p-3 border-b border-gray-800 hover:bg-gray-800 transition-colors block',
        isHovered && 'bg-gray-800 border-l-2 border-l-blue-500'
      )}
    >
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-white text-sm font-semibold truncate">{candidate.county_name}</span>
        <span className="text-xs px-2 py-0.5 rounded-full" style={{ backgroundColor: scoreColorHex(candidate.opportunity_score) + '33', color: scoreColorHex(candidate.opportunity_score) }}>
          {Math.round(candidate.opportunity_score * 100)}
        </span>
      </div>
      <div className="text-xl font-bold text-white mb-1">{fmtUFFull(candidate.estimated_uf)}</div>
      <div className="flex items-center gap-3 text-xs">
        <span style={{ color: gap.color }}>{gap.text}</span>
        <span className="text-gray-500 flex items-center gap-1">
          <Icon size={11} />
          {Math.round(candidate.surface_land_m2 || 0).toLocaleString('es-CL')} m²
        </span>
        {candidate.is_eriazo && <span className="text-amber-400 text-[10px]">SUBUTILIZADO</span>}
      </div>
    </button>
  )
}

// ── Detail page (1 viewport, no scroll) ─────────────────────────────────

function DetailPage({ candidate, mode, onClose }: { candidate: Candidate; mode: 'investor' | 'operator'; onClose: () => void }) {
  const propType = PROPERTY_TYPES.find(p => p.code === candidate.property_type_code)
  const propLabel = propType?.label?.replace(/s$/, '') ?? candidate.property_type_code
  const gap = gapText(candidate.drivers)
  const drivers = candidate.drivers ?? {}
  const nCompetitors = (drivers.n_competitors_2km as number | undefined) ??
                       (drivers[`n_competitors_${candidate.property_type_code}`] as number | undefined)

  return (
    <div className="absolute inset-0 z-50 bg-gray-950 flex flex-col">
      <div className="flex items-center justify-between p-4 border-b border-gray-800">
        <button onClick={onClose} className="text-gray-400 hover:text-white text-sm flex items-center gap-2">
          ← Volver al mapa
        </button>
        <div className="text-xs text-gray-600">data v3.2 · model v1.0</div>
      </div>

      <div className="flex-1 overflow-hidden p-8">
        <div className="max-w-6xl mx-auto h-full flex flex-col">
          <div className="flex items-baseline justify-between mb-6">
            <div>
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{propLabel}</div>
              <h1 className="text-3xl font-bold text-white">{candidate.county_name}</h1>
            </div>
            <div className="text-right">
              <div className="text-5xl font-bold" style={{ color: scoreColorHex(candidate.opportunity_score) }}>
                {Math.round(candidate.opportunity_score * 100)}
              </div>
              <div className="text-xs" style={{ color: scoreColorHex(candidate.opportunity_score) }}>
                {scoreLabel(candidate.opportunity_score)}
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-8 flex-1 min-h-0">
            {/* Left: mini map */}
            <div className="bg-gray-900 rounded-2xl overflow-hidden relative">
              <DeckGL
                initialViewState={{ longitude: candidate.longitude, latitude: candidate.latitude, zoom: 14, pitch: 0, bearing: 0 }}
                controller={true}
                layers={[
                  new ScatterplotLayer({
                    id: 'detail-pin',
                    data: [candidate],
                    getPosition: (d: Candidate) => [d.longitude, d.latitude],
                    getRadius: 60,
                    getFillColor: (d: Candidate) => scoreColor(d.opportunity_score),
                    radiusUnits: 'meters',
                    radiusMinPixels: 12,
                  }),
                ]}
              >
                <MapLibre mapStyle={MAP_STYLE} />
              </DeckGL>
            </div>

            {/* Right: data */}
            <div className="flex flex-col gap-4 overflow-y-auto pr-2">
              {/* Precio justo */}
              <div>
                <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">Precio justo según comparables</div>
                <div className="text-3xl font-bold text-white mb-1">{fmtUFFull(candidate.estimated_uf)}</div>
                <div className="text-xs text-gray-500 mb-3">Rango {fmtUF(candidate.p25_uf)} – {fmtUF(candidate.p75_uf)}</div>
                <div className="relative h-2 bg-gray-800 rounded-full mb-1">
                  <div className="absolute h-full bg-blue-600 rounded-full" style={{ left: '25%', width: '50%' }} />
                  <div className="absolute w-3 h-3 bg-white rounded-full -top-0.5 border-2 border-blue-400" style={{ left: 'calc(50% - 6px)' }} />
                </div>
              </div>

              {/* Descuento */}
              <div className="bg-gray-900 rounded-xl p-4">
                <div className="text-xs text-gray-500 mb-1">Diferencia con valor de mercado</div>
                <div className="text-2xl font-bold" style={{ color: gap.color }}>{gap.text}</div>
              </div>

              {/* Datos */}
              <div className="bg-gray-900 rounded-xl p-4 grid grid-cols-2 gap-3">
                <div>
                  <div className="text-xs text-gray-500">Tipo</div>
                  <div className="text-white text-sm font-medium">{propLabel}</div>
                </div>
                <div>
                  <div className="text-xs text-gray-500">Terreno</div>
                  <div className="text-white text-sm font-medium">{Math.round(candidate.surface_land_m2 || 0).toLocaleString('es-CL')} m²</div>
                </div>
                {candidate.surface_building_m2 ? (
                  <div>
                    <div className="text-xs text-gray-500">Construcción</div>
                    <div className="text-white text-sm font-medium">{Math.round(candidate.surface_building_m2).toLocaleString('es-CL')} m²</div>
                  </div>
                ) : null}
                {candidate.is_eriazo && (
                  <div>
                    <div className="text-xs text-gray-500">Estado</div>
                    <div className="text-amber-400 text-sm font-medium">Subutilizado</div>
                  </div>
                )}
              </div>

              {/* Operador only */}
              {mode === 'operator' && candidate.max_payable_uf && (
                <div className="bg-amber-950/30 border border-amber-900/50 rounded-xl p-4">
                  <div className="text-xs text-amber-400 mb-1 flex items-center gap-1.5">
                    <Briefcase size={11} /> Como operador comercial
                  </div>
                  <div className="text-2xl font-bold text-amber-400 mb-1">{fmtUFFull(candidate.max_payable_uf)}</div>
                  <div className="text-xs text-gray-500">Máximo pagable. Cap rate referencial — validar.</div>
                  {typeof nCompetitors === 'number' && (
                    <div className="text-xs text-gray-400 mt-2">{nCompetitors} competidores en radio 2 km</div>
                  )}
                </div>
              )}

              {/* Riesgos */}
              <div className="bg-yellow-950/20 border border-yellow-900/40 rounded-xl p-4">
                <div className="text-xs font-semibold text-yellow-500 mb-2 flex items-center gap-1.5">
                  <AlertTriangle size={11} /> Antes de comprar, verifica
                </div>
                <ul className="space-y-1 text-xs text-gray-300">
                  <li>☐ Certificado de hipotecas y gravámenes (CBR)</li>
                  <li>☐ Verificar uso permitido en plan regulador</li>
                  <li>☐ Tasación independiente</li>
                  <li>☐ Inspección física de la propiedad</li>
                </ul>
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="flex gap-3 mt-6">
            <a
              href={`https://maps.google.com/?q=${candidate.latitude},${candidate.longitude}`}
              target="_blank"
              rel="noopener noreferrer"
              className="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded-full flex items-center gap-2"
            >
              <MapPin size={14} /> Ver en Google Maps
            </a>
            <button className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-full flex items-center gap-2">
              <Save size={14} /> Guardar
            </button>
            <button className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-full flex items-center gap-2">
              <FileText size={14} /> Descargar PDF
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main panel ──────────────────────────────────────────────────────────

export function OpportunityPanel() {
  const [mode, setMode]               = useState<'investor' | 'operator'>('investor')
  const [useCase, setUseCase]         = useState('as_is')
  const [selected, setSelected]       = useState<Candidate | null>(null)
  const [hoveredId, setHoveredId]     = useState<number | null>(null)
  const [viewState, setViewState]     = useState(INITIAL_VIEW)
  const [openDropdown, setOpenDropdown] = useState<string | null>(null)

  // Filter state
  const [communes, setCommunes]   = useState<string[]>([])
  const [types, setTypes]         = useState<string[]>([])
  const [priceMax, setPriceMax]   = useState<number>(50000)
  const [surfaceMin, setSurfaceMin] = useState<number>(0)
  const [surfaceMax, setSurfaceMax] = useState<number>(10000)
  const [scoreFilter, setScoreFilter] = useState<'all' | 'good' | 'top'>('all')
  const [eriazo, setEriazo]       = useState(false)
  const [communeSearch, setCommuneSearch] = useState('')

  const scoreMin = scoreFilter === 'top' ? 0.75 : scoreFilter === 'good' ? 0.6 : 0.5
  const profile = mode === 'operator' ? 'operator' : 'value'
  const activeUseCase = mode === 'operator' ? useCase : 'as_is'

  // Server-side filters: use first commune (multi-commune handled client-side)
  const queryParams = new URLSearchParams({
    use_case: activeUseCase,
    profile,
    score_min: scoreMin.toString(),
    limit: '500',
    ...(communes.length === 1 ? { commune: communes[0] } : {}),
  })

  const { data, isLoading } = useQuery({
    queryKey: ['opp-v4', activeUseCase, profile, communes[0], scoreMin],
    queryFn: async () => {
      const r = await fetch(`${API}/opportunity/candidates?${queryParams}`)
      return r.json()
    },
  })

  // Client-side filters
  const items: Candidate[] = useMemo(() => {
    return (data?.items ?? []).filter((c: Candidate) => {
      if (!c.latitude || !c.longitude) return false
      if (communes.length > 1 && !communes.includes(c.county_name)) return false
      if (types.length > 0 && !types.includes(c.property_type_code)) return false
      if ((c.estimated_uf ?? 0) > priceMax) return false
      const m2 = c.surface_land_m2 ?? 0
      if (m2 < surfaceMin || m2 > surfaceMax) return false
      if (eriazo && !c.is_eriazo) return false
      return true
    })
  }, [data, communes, types, priceMax, surfaceMin, surfaceMax, eriazo])

  // Auto-fit when commune changes
  useEffect(() => {
    if (communes.length === 1 && items.length > 0) {
      const lats = items.map(c => c.latitude).filter(Boolean)
      const lons = items.map(c => c.longitude).filter(Boolean)
      if (lats.length > 0) {
        const cLat = (Math.min(...lats) + Math.max(...lats)) / 2
        const cLon = (Math.min(...lons) + Math.max(...lons)) / 2
        setViewState({ longitude: cLon, latitude: cLat, zoom: 13, pitch: 0, bearing: 0 })
      }
    }
  }, [communes, items.length])

  const layers = [
    new ScatterplotLayer({
      id: 'pins',
      data: items,
      getPosition: (d: Candidate) => [d.longitude, d.latitude],
      getRadius: (d: Candidate) => Math.max(60, Math.min(200, Math.sqrt((d.surface_land_m2 ?? 100)) * 4)),
      getFillColor: (d: Candidate) => scoreColor(d.opportunity_score),
      getLineColor: (d: Candidate) => (d.id === hoveredId ? [255, 255, 255, 255] : [0, 0, 0, 100]),
      lineWidthMinPixels: 1,
      stroked: true,
      pickable: true,
      onClick: ({ object }: { object: Candidate }) => setSelected(object),
      onHover: ({ object }: { object: Candidate | null }) => setHoveredId(object?.id ?? null),
      radiusUnits: 'meters',
      radiusMinPixels: 5,
      radiusMaxPixels: 18,
      updateTriggers: {
        getLineColor: [hoveredId],
      },
    }),
    new TextLayer({
      id: 'prices',
      data: items.slice(0, 30),
      getPosition: (d: Candidate) => [d.longitude, d.latitude],
      getText: (d: Candidate) => fmtUF(d.estimated_uf),
      getColor: [255, 255, 255, 230],
      getSize: 11,
      sizeUnits: 'pixels',
      getPixelOffset: [0, -18],
      background: true,
      backgroundPadding: [4, 2],
      getBackgroundColor: [10, 10, 30, 200],
      fontFamily: 'system-ui',
      fontWeight: 600,
    }),
  ]

  const filteredCommunes = COMMUNES.filter(c => c.toLowerCase().includes(communeSearch.toLowerCase()))
  const hasFilters = communes.length > 0 || types.length > 0 || priceMax < 50000 || surfaceMin > 0 || surfaceMax < 10000 || scoreFilter !== 'all' || eriazo

  const clearFilters = () => {
    setCommunes([])
    setTypes([])
    setPriceMax(50000)
    setSurfaceMin(0)
    setSurfaceMax(10000)
    setScoreFilter('all')
    setEriazo(false)
  }

  return (
    <div className="relative h-full w-full bg-gray-950 flex flex-col overflow-hidden">
      {/* Header — mode toggle */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-gray-800 bg-gray-950 z-10">
        <div className="text-white font-semibold">Oportunidades</div>
        <div className="flex bg-gray-900 rounded-full p-1 border border-gray-800">
          <button
            onClick={() => { setMode('investor'); setUseCase('as_is') }}
            className={clsx('px-4 py-1.5 rounded-full text-xs font-medium flex items-center gap-1.5',
              mode === 'investor' ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white')}
          >
            <Home size={12} /> Inversión
          </button>
          <button
            onClick={() => { setMode('operator'); setUseCase('gas_station') }}
            className={clsx('px-4 py-1.5 rounded-full text-xs font-medium flex items-center gap-1.5',
              mode === 'operator' ? 'bg-amber-600 text-white' : 'text-gray-400 hover:text-white')}
          >
            <Briefcase size={12} /> Operador
          </button>
        </div>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 px-6 py-3 border-b border-gray-800 bg-gray-950 z-10 overflow-x-auto">
        {/* Comuna */}
        <FilterDropdown
          label="Comuna"
          icon={<MapPin size={14} />}
          isOpen={openDropdown === 'comuna'}
          onToggle={() => setOpenDropdown(openDropdown === 'comuna' ? null : 'comuna')}
          active={communes.length > 0}
          badge={communes.length > 0 ? `${communes.length}` : undefined}
        >
          <input
            type="text"
            placeholder="Buscar comuna..."
            value={communeSearch}
            onChange={e => setCommuneSearch(e.target.value)}
            className="w-full bg-gray-800 text-white text-sm px-3 py-2 rounded-lg border border-gray-700 mb-3"
          />
          <div className="max-h-64 overflow-y-auto space-y-1">
            {filteredCommunes.map(c => (
              <label key={c} className="flex items-center gap-2 px-2 py-1 hover:bg-gray-800 rounded cursor-pointer">
                <input
                  type="checkbox"
                  checked={communes.includes(c)}
                  onChange={() => setCommunes(p => p.includes(c) ? p.filter(x => x !== c) : [...p, c])}
                  className="accent-blue-500"
                />
                <span className="text-sm text-gray-300">{c}</span>
              </label>
            ))}
          </div>
          {communes.length > 0 && (
            <button onClick={() => setCommunes([])} className="text-xs text-gray-500 hover:text-white mt-2">
              Limpiar selección
            </button>
          )}
        </FilterDropdown>

        {/* Tipo */}
        <FilterDropdown
          label="Tipo"
          icon={<Home size={14} />}
          isOpen={openDropdown === 'tipo'}
          onToggle={() => setOpenDropdown(openDropdown === 'tipo' ? null : 'tipo')}
          active={types.length > 0}
          badge={types.length > 0 ? `${types.length}` : undefined}
        >
          <div className="grid grid-cols-2 gap-2">
            {PROPERTY_TYPES.map(({ code, label, icon: Icon }) => (
              <button
                key={code}
                onClick={() => setTypes(p => p.includes(code) ? p.filter(x => x !== code) : [...p, code])}
                className={clsx(
                  'flex items-center gap-2 px-3 py-2 rounded-lg text-sm border',
                  types.includes(code)
                    ? 'bg-blue-600 text-white border-blue-500'
                    : 'bg-gray-800 text-gray-300 border-gray-700 hover:border-gray-500'
                )}
              >
                <Icon size={14} /> {label}
              </button>
            ))}
          </div>
        </FilterDropdown>

        {/* Precio máximo */}
        <FilterDropdown
          label="Precio"
          isOpen={openDropdown === 'precio'}
          onToggle={() => setOpenDropdown(openDropdown === 'precio' ? null : 'precio')}
          active={priceMax < 50000}
          badge={priceMax < 50000 ? `≤ ${(priceMax / 1000).toFixed(0)}k UF` : undefined}
        >
          <div className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm text-gray-400">Máximo</span>
                <span className="text-white font-semibold">{(priceMax / 1000).toFixed(0)}k UF</span>
              </div>
              <input
                type="range" min={1000} max={50000} step={500}
                value={priceMax}
                onChange={e => setPriceMax(Number(e.target.value))}
                className="w-full accent-blue-500"
              />
              <div className="flex justify-between text-xs text-gray-600 mt-1">
                <span>1k</span><span>10k</span><span>25k</span><span>50k+</span>
              </div>
            </div>
            <div className="flex gap-2">
              {[5000, 10000, 20000, 50000].map(p => (
                <button
                  key={p}
                  onClick={() => setPriceMax(p)}
                  className={clsx(
                    'flex-1 py-1 rounded text-xs',
                    priceMax === p ? 'bg-blue-600 text-white' : 'bg-gray-800 text-gray-400 hover:text-white'
                  )}
                >
                  ≤{(p / 1000).toFixed(0)}k
                </button>
              ))}
            </div>
          </div>
        </FilterDropdown>

        {/* Tamaño */}
        <FilterDropdown
          label="Tamaño"
          isOpen={openDropdown === 'tamano'}
          onToggle={() => setOpenDropdown(openDropdown === 'tamano' ? null : 'tamano')}
          active={surfaceMin > 0 || surfaceMax < 10000}
          badge={(surfaceMin > 0 || surfaceMax < 10000) ? `${surfaceMin}–${surfaceMax}m²` : undefined}
        >
          <div className="space-y-3">
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-gray-400">Mínimo</span>
                <span className="text-white font-semibold">{surfaceMin.toLocaleString('es-CL')} m²</span>
              </div>
              <input
                type="range" min={0} max={5000} step={50}
                value={surfaceMin}
                onChange={e => setSurfaceMin(Number(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>
            <div>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm text-gray-400">Máximo</span>
                <span className="text-white font-semibold">{surfaceMax.toLocaleString('es-CL')} m²</span>
              </div>
              <input
                type="range" min={100} max={10000} step={100}
                value={surfaceMax}
                onChange={e => setSurfaceMax(Number(e.target.value))}
                className="w-full accent-blue-500"
              />
            </div>
          </div>
        </FilterDropdown>

        {/* Score */}
        <div className="bg-gray-900 rounded-full p-1 border border-gray-700 flex gap-1">
          {([
            { v: 'all',  label: 'Cualquiera' },
            { v: 'good', label: '⭐ Buena' },
            { v: 'top',  label: '🔥 Top' },
          ] as const).map(({ v, label }) => (
            <button
              key={v}
              onClick={() => setScoreFilter(v)}
              className={clsx(
                'px-3 py-1.5 rounded-full text-xs font-medium',
                scoreFilter === v ? 'bg-white text-black' : 'text-gray-400 hover:text-white'
              )}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Eriazo */}
        <button
          onClick={() => setEriazo(!eriazo)}
          className={clsx(
            'px-3 py-2 rounded-full text-xs font-medium border',
            eriazo
              ? 'bg-amber-600 text-white border-amber-500'
              : 'bg-gray-900 text-gray-400 border-gray-700 hover:text-white'
          )}
        >
          {eriazo ? '✓ ' : ''}Solo subutilizados
        </button>

        {/* Use case (operador only) */}
        {mode === 'operator' && (
          <select
            value={useCase}
            onChange={e => setUseCase(e.target.value)}
            className="bg-amber-950 text-amber-300 text-sm px-3 py-2 rounded-full border border-amber-700"
          >
            {COMMERCIAL_USES.map(u => <option key={u.value} value={u.value}>{u.label}</option>)}
          </select>
        )}

        {/* Clear */}
        {hasFilters && (
          <button
            onClick={clearFilters}
            className="px-3 py-2 rounded-full text-xs text-red-400 hover:bg-red-950/30 flex items-center gap-1 ml-auto"
          >
            <X size={12} /> Limpiar
          </button>
        )}
      </div>

      {/* Main: map + sidebar */}
      <div className="flex-1 flex relative min-h-0">
        {/* Map */}
        <div className="flex-1 relative">
          <DeckGL
            initialViewState={INITIAL_VIEW}
            viewState={viewState}
            controller={true}
            layers={layers}
            onViewStateChange={({ viewState: v }) => setViewState(v as typeof INITIAL_VIEW)}
            getCursor={({ isHovering }) => (isHovering ? 'pointer' : 'grab')}
          >
            <MapLibre mapStyle={MAP_STYLE} reuseMaps />
          </DeckGL>

          {/* Legend */}
          <div className="absolute bottom-4 left-4 z-10 bg-gray-900/95 backdrop-blur rounded-xl p-3 border border-gray-800 text-xs space-y-1 shadow-lg">
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-green-500" /> Alta oportunidad</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500" /> Buena</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Baja</div>
          </div>

          {/* Footer info */}
          <div className="absolute top-4 right-4 z-10 bg-gray-900/95 backdrop-blur rounded-full px-4 py-2 border border-gray-800 shadow-lg text-xs text-gray-300">
            {isLoading ? 'Buscando...' : `${items.length.toLocaleString('es-CL')} oportunidades`}
          </div>
        </div>

        {/* Sidebar list */}
        <div className="w-80 border-l border-gray-800 bg-gray-950 flex flex-col">
          <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between">
            <span className="text-sm font-semibold text-white">Top oportunidades</span>
            <button
              onClick={() => {
                if (!items.length) return
                const headers = ['comuna','tipo','score','estimado_uf','m2','lat','lon']
                const rows = items.map(c => [
                  c.county_name, c.property_type_code, c.opportunity_score?.toFixed(3),
                  c.estimated_uf ? Math.round(c.estimated_uf) : '',
                  c.surface_land_m2 ? Math.round(c.surface_land_m2) : '', c.latitude, c.longitude,
                ])
                const csv = [headers, ...rows].map(r => r.join(',')).join('\n')
                const blob = new Blob([csv], { type: 'text/csv' })
                const url = URL.createObjectURL(blob)
                const a = document.createElement('a'); a.href = url
                a.download = `oportunidades_${new Date().toISOString().slice(0,10)}.csv`
                a.click(); URL.revokeObjectURL(url)
              }}
              className="text-gray-500 hover:text-green-400" title="Exportar CSV"
            >
              <Download size={14} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto">
            {isLoading ? (
              <div className="p-4 space-y-3">
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="animate-pulse">
                    <div className="h-3 bg-gray-800 rounded w-1/2 mb-2" />
                    <div className="h-5 bg-gray-800 rounded w-3/4 mb-1" />
                    <div className="h-3 bg-gray-800 rounded w-2/3" />
                  </div>
                ))}
              </div>
            ) : items.length === 0 ? (
              <div className="p-8 text-center text-gray-500 text-sm">
                <Filter size={32} className="mx-auto mb-3 opacity-30" />
                <div>No hay oportunidades con estos filtros.</div>
                <button onClick={clearFilters} className="text-blue-400 hover:underline text-xs mt-2">
                  Limpiar filtros
                </button>
              </div>
            ) : (
              items.slice(0, 50).map(c => (
                <PropertyCard
                  key={c.id}
                  candidate={c}
                  onClick={() => setSelected(c)}
                  isHovered={hoveredId === c.id}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {/* Detail page overlay */}
      {selected && (
        <DetailPage candidate={selected} mode={mode} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
