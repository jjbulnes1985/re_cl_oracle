/**
 * HomeShell.tsx — Vista principal única (post-rediseño)
 *
 * Reemplaza el sistema de 9 tabs. Layout:
 *   - Header con pregunta resumida + watchlist
 *   - Mapa fullscreen al centro (Deck.gl)
 *   - Top Opportunities Rail lateral derecho
 *   - PropertyDrawer al click en pin/card (bottom sheet)
 *
 * Onboarding (3 pantallas) se ejecuta en primera carga.
 */

import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import DeckGL from '@deck.gl/react'
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { Map as MapLibre } from 'react-map-gl/maplibre'
import { Heart, Settings, ChevronRight, MapPin, Layers, X } from 'lucide-react'
import { clsx } from 'clsx'
import 'maplibre-gl/dist/maplibre-gl.css'
import { OnboardingFlow, OBJECTIVES, type OnboardingState } from './OnboardingFlow'
import { TopOpportunitiesRail } from './TopOpportunitiesRail'
import { PropertyDrawer } from './PropertyDrawer'
import { WatchlistDrawer } from './WatchlistDrawer'
import { EmptyStateCoach } from './EmptyStateCoach'
import { ComparatorOverlay } from './ComparatorOverlay'
import { HeatmapToggle } from './HeatmapToggle'
import { SettingsDrawer } from './SettingsDrawer'
import { fmtUF } from '../lib/format'

const API = (import.meta as any).env?.VITE_API_URL || 'http://localhost:8000'

const INITIAL_VIEW = {
  longitude: -70.67,
  latitude:  -33.45,
  zoom:       11,
  pitch:      0,
  bearing:    0,
}

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

export interface Candidate {
  id: number
  address: string | null
  county_name: string
  latitude: number
  longitude: number
  property_type_code: string
  surface_land_m2: number | null
  surface_building_m2: number | null
  is_eriazo: boolean
  opportunity_score: number
  use_specific_score: number | null
  max_payable_uf: number | null
  estimated_uf: number | null
  p25_uf: number | null
  p75_uf: number | null
  valuation_confidence: number | null
  drivers: Record<string, unknown> | null
}

const ONBOARDING_KEY = 're_cl_onboarding_v2'

function loadOnboardingState(): OnboardingState | null {
  try {
    const raw = localStorage.getItem(ONBOARDING_KEY)
    if (!raw) return null
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function saveOnboardingState(state: OnboardingState) {
  try {
    localStorage.setItem(ONBOARDING_KEY, JSON.stringify(state))
  } catch {/* ignore */}
}

function scoreColor(score: number): [number, number, number, number] {
  if (score >= 0.75) return [34, 197, 94, 220]
  if (score >= 0.60) return [234, 179, 8, 220]
  return [239, 68, 68, 200]
}

const LAYER_TOGGLES = [
  { key: 'heatmap',  label: 'Comunas', icon: '🗺' },
  { key: 'metro',    label: 'Metro',   icon: 'Ⓜ' },
  { key: 'schools',  label: 'Colegios', icon: '🏫' },
  { key: 'parks',    label: 'Parques', icon: '🌳' },
]

export function HomeShell() {
  const [onboarding, setOnboarding]   = useState<OnboardingState | null>(loadOnboardingState())
  const [showOnboarding, setShowOnboarding] = useState(!onboarding)
  const [selected, setSelected]       = useState<Candidate | null>(null)
  const [watchlistOpen, setWatchlistOpen] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [heatmapOpen, setHeatmapOpen] = useState(false)
  const [compareA, setCompareA]       = useState<Candidate | null>(null)
  const [compareB, setCompareB]       = useState<Candidate | null>(null)
  const [hoveredId, setHoveredId]     = useState<number | null>(null)
  const [viewState, setViewState]     = useState(INITIAL_VIEW)
  const [activeLayers, setActiveLayers] = useState<Set<string>>(new Set())

  // Fetch candidates based on onboarding answers
  const queryParams = useMemo(() => {
    if (!onboarding) return null
    const params = new URLSearchParams({
      use_case: onboarding.useCase,
      profile:  onboarding.profile,
      score_min: '0.5',
      limit: '300',
    })
    if (onboarding.communes.length === 1) {
      params.set('commune', onboarding.communes[0])
    }
    return params
  }, [onboarding])

  const { data, isLoading, error } = useQuery({
    queryKey: ['home-shell', onboarding?.useCase, onboarding?.profile, onboarding?.communes?.[0], onboarding?.maxBudgetUF],
    queryFn: async () => {
      if (!queryParams) return { items: [], total: 0 }
      const url = `${API}/opportunity/candidates?${queryParams}`
      console.log('[RE_CL] Fetching:', url)
      try {
        const r = await fetch(url)
        if (!r.ok) {
          console.error(`[RE_CL] API error ${r.status} on`, url)
          throw new Error(`API ${r.status}: ${r.statusText}`)
        }
        const json = await r.json()
        console.log(`[RE_CL] Received ${json.items?.length ?? 0} items / total=${json.total ?? 0}`)
        return json
      } catch (e) {
        console.error('[RE_CL] Fetch failed:', e)
        throw e
      }
    },
    enabled: !!queryParams,
    retry: 1,
  })

  // Client-side filtering for budget + multi-commune + bbox
  const items: Candidate[] = useMemo(() => {
    if (!data?.items || !onboarding) return []
    return data.items.filter((c: Candidate) => {
      if (!c.latitude || !c.longitude) return false
      // Budget filter
      if (onboarding.maxBudgetUF && (c.estimated_uf ?? 0) > onboarding.maxBudgetUF) return false
      // Multi-commune (if more than 1)
      if (onboarding.communes.length > 1 && !onboarding.communes.includes(c.county_name)) return false
      return true
    })
  }, [data, onboarding])

  // Auto-fit when communes change
  useEffect(() => {
    if (onboarding?.communes.length === 1 && items.length > 0) {
      const lats = items.map(c => c.latitude).filter(Boolean)
      const lons = items.map(c => c.longitude).filter(Boolean)
      if (lats.length > 0) {
        setViewState({
          longitude: (Math.min(...lons) + Math.max(...lons)) / 2,
          latitude:  (Math.min(...lats) + Math.max(...lats)) / 2,
          zoom:      13,
          pitch:     0,
          bearing:   0,
        })
      }
    }
  }, [onboarding?.communes, items.length])

  const handleOnboardingComplete = (state: OnboardingState) => {
    saveOnboardingState(state)
    setOnboarding(state)
    setShowOnboarding(false)
  }

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
      updateTriggers: { getLineColor: [hoveredId] },
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

  if (showOnboarding) {
    return (
      <OnboardingFlow
        initial={onboarding}
        onComplete={handleOnboardingComplete}
        onSkip={() => {
          const def: OnboardingState = {
            objectiveCode: 'explore',
            useCase: 'as_is',
            profile: 'value',
            maxBudgetUF: null,
            communes: [],
          }
          saveOnboardingState(def)
          setOnboarding(def)
          setShowOnboarding(false)
        }}
      />
    )
  }

  if (!onboarding) return null

  const objective = OBJECTIVES.find(o => o.code === onboarding.objectiveCode)

  return (
    <div className="h-screen w-screen flex flex-col bg-gray-950 overflow-hidden">
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-gray-800 bg-gray-950 z-30">
        <div className="flex items-center gap-3">
          <span className="text-white font-bold text-lg">RE_CL</span>
          <button
            onClick={() => setShowOnboarding(true)}
            className="text-xs text-gray-400 hover:text-white px-3 py-1.5 rounded-full bg-gray-900 border border-gray-800 truncate max-w-md"
          >
            <span className="text-gray-500">Buscando: </span>
            <span>{objective?.label ?? 'Cualquier oportunidad'}</span>
            {onboarding.maxBudgetUF && <span> · ≤ {fmtUF(onboarding.maxBudgetUF)}</span>}
            {onboarding.communes.length > 0 && <span> · {onboarding.communes.slice(0, 2).join(', ')}{onboarding.communes.length > 2 ? '...' : ''}</span>}
            <span className="text-gray-500 ml-2">[editar]</span>
          </button>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={() => setWatchlistOpen(true)}
            className="text-gray-400 hover:text-white relative p-2"
            aria-label="Watchlist"
          >
            <Heart size={18} />
          </button>
          <button
            onClick={() => setHeatmapOpen(o => !o)}
            className={clsx('text-gray-400 hover:text-white p-2', heatmapOpen && 'text-blue-400')}
            aria-label="Heatmap comunas"
            title="Heatmap comunas"
          >
            <Layers size={18} />
          </button>
          <button
            onClick={() => setSettingsOpen(true)}
            className="text-gray-400 hover:text-white p-2"
            aria-label="Settings"
          >
            <Settings size={18} />
          </button>
        </div>
      </header>

      {/* Main: map + rail */}
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

          {/* Layer toggles */}
          <div className="absolute top-4 left-4 z-10 bg-gray-900/95 backdrop-blur rounded-2xl p-2 border border-gray-800 shadow-lg flex flex-col gap-1">
            <div className="text-xs text-gray-500 px-2 py-1 flex items-center gap-1.5"><Layers size={11} /> Capas</div>
            {LAYER_TOGGLES.map(({ key, label, icon }) => (
              <button
                key={key}
                onClick={() => setActiveLayers(prev => {
                  const n = new Set(prev)
                  n.has(key) ? n.delete(key) : n.add(key)
                  return n
                })}
                className={clsx(
                  'flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors',
                  activeLayers.has(key) ? 'bg-blue-600 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'
                )}
              >
                <span>{icon}</span>
                {label}
              </button>
            ))}
          </div>

          {/* Legend */}
          <div className="absolute bottom-4 left-4 z-10 bg-gray-900/95 backdrop-blur rounded-xl p-3 border border-gray-800 text-xs space-y-1 shadow-lg">
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-green-500" /> Excelente</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-yellow-500" /> Buena</div>
            <div className="flex items-center gap-2"><span className="w-2.5 h-2.5 rounded-full bg-red-500" /> Regular</div>
          </div>

          {/* API error banner */}
          {error && (
            <div className="absolute top-4 left-1/2 -translate-x-1/2 z-30 bg-red-950/95 border border-red-700 rounded-xl px-4 py-3 max-w-md shadow-lg">
              <div className="text-xs font-semibold text-red-400 mb-1">Error de conexión con la API</div>
              <div className="text-xs text-red-300">{(error as Error).message}</div>
              <div className="text-[10px] text-red-500 mt-1">Verifica que la API esté corriendo en {API}</div>
            </div>
          )}

          {/* Empty state coach */}
          {!isLoading && !error && items.length === 0 && onboarding && (
            <EmptyStateCoach
              onboarding={onboarding}
              onUpdateBudget={(b) => {
                const next = { ...onboarding, maxBudgetUF: b }
                saveOnboardingState(next)
                setOnboarding(next)
              }}
              onClearCommunes={() => {
                const next = { ...onboarding, communes: [] }
                saveOnboardingState(next)
                setOnboarding(next)
              }}
              onChangeObjective={() => setShowOnboarding(true)}
            />
          )}

          {/* Footer info */}
          <div className="absolute bottom-1 right-1 text-[10px] text-gray-700 z-10">
            data v3.2 · model v1.0
          </div>
        </div>

        {/* Top Opportunities Rail */}
        <TopOpportunitiesRail
          items={items}
          isLoading={isLoading}
          selectedId={selected?.id ?? null}
          hoveredId={hoveredId}
          onHover={setHoveredId}
          onSelect={(c) => {
            setSelected(c)
            setViewState(prev => ({ ...prev, longitude: c.longitude, latitude: c.latitude, zoom: Math.max(prev.zoom, 14) }))
          }}
        />
      </div>

      {/* Property drawer overlay */}
      {selected && (
        <PropertyDrawer
          candidate={selected}
          objective={objective}
          onClose={() => setSelected(null)}
        />
      )}

      {/* Watchlist drawer */}
      {watchlistOpen && (
        <WatchlistDrawer
          onClose={() => setWatchlistOpen(false)}
          onSelectCandidate={(c) => {
            setSelected(c)
            setWatchlistOpen(false)
          }}
        />
      )}

      {/* Settings drawer */}
      {settingsOpen && <SettingsDrawer onClose={() => setSettingsOpen(false)} />}

      {/* Heatmap overlay */}
      {heatmapOpen && (
        <HeatmapToggle
          active={heatmapOpen}
          onClose={() => setHeatmapOpen(false)}
          onSelectCommune={(commune) => {
            const next = { ...onboarding, communes: [commune] }
            saveOnboardingState(next)
            setOnboarding(next)
            setHeatmapOpen(false)
          }}
        />
      )}

      {/* Comparator overlay */}
      {compareA && compareB && (
        <ComparatorOverlay
          a={compareA}
          b={compareB}
          onClose={() => { setCompareA(null); setCompareB(null) }}
        />
      )}
    </div>
  )
}
