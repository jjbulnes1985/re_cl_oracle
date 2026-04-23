import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronLeft, ChevronRight, SlidersHorizontal, Bookmark } from 'lucide-react'
import { fetchCommunes, fetchProfiles, fetchScoreSummary, createSavedSearch, fetchSavedSearches } from '../api'
import { useAppStore } from '../store'
import type { ProfileName, CustomWeights } from '../types'
import { clsx } from 'clsx'

const TYPOLOGIES = ['apartments', 'residential', 'land', 'retail']
const TYPOLOGY_LABELS: Record<string, string> = {
  apartments:  'Departamentos',
  residential: 'Casas',
  land:        'Terrenos',
  retail:      'Local Comercial',
}

const PROFILE_LABELS: Record<ProfileName, string> = {
  default:   'Estándar',
  location:  'Ubicación',
  growth:    'Crecimiento',
  liquidity: 'Liquidez',
  custom:    'Personalizado',
}

const WEIGHT_KEYS: (keyof CustomWeights)[] = [
  'undervaluation', 'confidence', 'location', 'growth', 'volume'
]
const WEIGHT_LABELS: Record<keyof CustomWeights, string> = {
  undervaluation: 'Subvaloración',
  confidence:     'Confianza datos',
  location:       'Ubicación',
  growth:         'Crecimiento',
  volume:         'Liquidez',
}

// ── Stats bar ─────────────────────────────────────────────────────────────────

function StatsBadge({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="flex flex-col items-center gap-0.5 min-w-0">
      <span className={clsx('text-xs font-bold truncate', highlight ? 'text-blue-400' : 'text-white')}>
        {value}
      </span>
      <span className="text-[10px] text-gray-500 truncate text-center leading-tight">{label}</span>
    </div>
  )
}

function StatsBar() {
  const { data: summary } = useQuery({
    queryKey: ['score-summary'],
    queryFn: fetchScoreSummary,
    staleTime: 60_000,
  })
  const { data: communes = [] } = useQuery({ queryKey: ['communes'], queryFn: fetchCommunes })

  if (!summary) return null

  const topCommune = communes.length > 0
    ? communes.reduce((best, c) =>
        (c.median_score ?? 0) > (best.median_score ?? 0) ? c : best
      , communes[0])
    : null

  return (
    <div className="flex items-center justify-between gap-1 bg-gray-800 border border-gray-700 rounded-lg px-3 py-2 mb-1">
      <StatsBadge label="propiedades" value={summary.total_scored.toLocaleString()} />
      <div className="w-px h-6 bg-gray-700 shrink-0" />
      <StatsBadge label="score medio" value={summary.mean_score.toFixed(2)} highlight />
      <div className="w-px h-6 bg-gray-700 shrink-0" />
      <StatsBadge
        label="top comuna"
        value={topCommune ? topCommune.county_name.split(' ').slice(0, 2).join(' ') : '–'}
      />
    </div>
  )
}

// ── Location section ──────────────────────────────────────────────────────────

function LocationSection() {
  const { userLocation, maxDistFromUser, setUserLocation, setMaxDistFromUser } = useAppStore()
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const getLocation = () => {
    if (!navigator.geolocation) {
      setError('Geolocalización no disponible')
      return
    }
    setLoading(true)
    setError(null)
    navigator.geolocation.getCurrentPosition(
      pos => {
        setUserLocation({ lat: pos.coords.latitude, lon: pos.coords.longitude })
        setLoading(false)
      },
      () => {
        setError('No se pudo obtener la ubicación')
        setLoading(false)
      },
      { timeout: 10000 }
    )
  }

  return (
    <section>
      <label className="text-xs text-gray-400 uppercase tracking-wide">Mi ubicación</label>
      <div className="mt-1 flex gap-2">
        <button
          onClick={getLocation}
          disabled={loading}
          className="flex-1 py-1.5 rounded text-xs bg-gray-700 text-gray-300 hover:bg-gray-600 disabled:opacity-50"
        >
          {loading ? 'Localizando...' : userLocation ? '✓ Ubicación activa' : '📍 Detectar ubicación'}
        </button>
        {userLocation && (
          <button
            onClick={() => setUserLocation(null)}
            className="px-2 py-1.5 rounded text-xs bg-red-900/50 text-red-300 hover:bg-red-900"
          >×</button>
        )}
      </div>
      {error && <p className="text-red-400 text-xs mt-1">{error}</p>}
      {userLocation && (
        <div className="mt-2">
          <label className="text-xs text-gray-400 uppercase tracking-wide">
            Radio: {maxDistFromUser === 0 ? 'Sin filtro' : `${maxDistFromUser} km`}
          </label>
          <input
            type="range" min={0} max={10} step={0.5}
            value={maxDistFromUser}
            onChange={e => setMaxDistFromUser(parseFloat(e.target.value))}
            className="w-full mt-1 accent-blue-500"
          />
        </div>
      )}
    </section>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export function Sidebar() {
  const { filters, setFilters, sidebarOpen, setSidebarOpen, setCityZone, setMaxDistMetro, setSearchText, setActiveTab,
          authToken, authUser, setSavedSearches, setAuthModalOpen } = useAppStore()
  const [saving, setSaving] = useState(false)
  const [saveMsg, setSaveMsg] = useState<string | null>(null)
  const { data: communes = [] } = useQuery({ queryKey: ['communes'], queryFn: fetchCommunes })
  const { data: profiles = [] } = useQuery({ queryKey: ['profiles'], queryFn: fetchProfiles })

  const allCounties = communes.map((c) => c.county_name)

  const toggleType = (t: string) => {
    const cur = filters.projectTypes
    setFilters({ projectTypes: cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t] })
  }

  const toggleCounty = (c: string) => {
    const cur = filters.counties
    setFilters({ counties: cur.includes(c) ? cur.filter((x) => x !== c) : [...cur, c] })
  }

  const toggleZone = (zone: string) => {
    const cur = filters.cityZone
    setCityZone(cur.includes(zone) ? cur.filter((z) => z !== zone) : [...cur, zone])
  }

  const totalCustomWeight = WEIGHT_KEYS.reduce((s, k) => s + filters.customWeights[k], 0)

  return (
    <>
      {/* Mobile toggle button */}
      <button
        className="md:hidden fixed top-14 left-3 z-40 bg-gray-800 border border-gray-700 rounded p-2"
        onClick={() => setSidebarOpen(!sidebarOpen)}
      >
        <SlidersHorizontal size={16} className="text-gray-300" />
      </button>

      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="md:hidden fixed inset-0 z-20 bg-black/50"
          onClick={() => setSidebarOpen(false)}
        />
      )}

    <aside
      className={clsx(
        'flex flex-col bg-gray-900 border-r border-gray-800 transition-all duration-300 h-screen overflow-y-auto',
        'fixed md:relative inset-y-0 left-0 z-30 transition-transform',
        sidebarOpen ? 'translate-x-0 w-72' : '-translate-x-full md:translate-x-0 md:w-12 w-72'
      )}
    >
      {/* Desktop toggle */}
      <button
        onClick={() => setSidebarOpen(!sidebarOpen)}
        className="hidden md:flex items-center justify-center h-12 text-gray-400 hover:text-white hover:bg-gray-800 border-b border-gray-800 shrink-0"
      >
        {sidebarOpen ? <ChevronLeft size={18} /> : <ChevronRight size={18} />}
      </button>

      {/* Desktop collapsed icon */}
      {!sidebarOpen && (
        <div className="hidden md:flex flex-col items-center py-4 gap-4 text-gray-500">
          <SlidersHorizontal size={18} />
        </div>
      )}

      {sidebarOpen && (
        <div className="flex flex-col gap-5 p-4 text-sm">
          {/* Header */}
          <div>
            <h1 className="text-base font-bold text-white">RE_CL</h1>
            <p className="text-xs text-gray-500">Oportunidades Inmobiliarias RM</p>
          </div>

          {/* Stats bar */}
          <StatsBar />

          {/* Min score */}
          <section>
            <label className="block text-xs font-semibold text-gray-400 mb-1">
              Score mínimo: <span className="text-white">{filters.minScore.toFixed(2)}</span>
            </label>
            <input
              type="range" min={0} max={1} step={0.05}
              value={filters.minScore}
              onChange={(e) => setFilters({ minScore: parseFloat(e.target.value) })}
              className="w-full accent-blue-500"
            />
          </section>

          {/* Typologies */}
          <section>
            <p className="text-xs font-semibold text-gray-400 mb-2">Tipología</p>
            <div className="flex flex-col gap-1">
              {TYPOLOGIES.map((t) => (
                <label key={t} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filters.projectTypes.includes(t)}
                    onChange={() => toggleType(t)}
                    className="accent-blue-500"
                  />
                  <span className="text-gray-300">{TYPOLOGY_LABELS[t]}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Communes */}
          <section>
            <p className="text-xs font-semibold text-gray-400 mb-2">
              Comunas {filters.counties.length > 0 && `(${filters.counties.length})`}
            </p>
            <div className="flex flex-col gap-1 max-h-40 overflow-y-auto">
              {allCounties.map((c) => (
                <label key={c} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={filters.counties.length === 0 || filters.counties.includes(c)}
                    onChange={() => toggleCounty(c)}
                    className="accent-blue-500"
                  />
                  <span className="text-gray-300 text-xs">{c}</span>
                </label>
              ))}
            </div>
          </section>

          {/* Search by commune */}
          <section>
            <label className="text-xs text-gray-400 uppercase tracking-wide">Buscar comuna</label>
            <input
              type="text"
              value={filters.searchText}
              onChange={e => setSearchText(e.target.value)}
              onKeyDown={e => {
                if (e.key === 'Enter' && filters.searchText.length >= 3) {
                  setActiveTab('ranking')
                }
              }}
              placeholder="Ej: Las Condes..."
              className="w-full mt-1 px-2 py-1.5 rounded bg-gray-700 text-gray-200 text-sm border border-gray-600 focus:border-blue-500 focus:outline-none"
            />
            {filters.searchText.length >= 3 && (
              <p className="text-xs text-blue-400 mt-1 opacity-75">
                Presiona Enter para buscar en servidor →
              </p>
            )}
          </section>

          {/* Zona ciudad */}
          <section>
            <label className="text-xs text-gray-400 uppercase tracking-wide">Zona ciudad</label>
            <div className="flex flex-wrap gap-1 mt-1">
              {(['centro_norte', 'este', 'oeste', 'sur'] as const).map(zone => (
                <button
                  key={zone}
                  onClick={() => toggleZone(zone)}
                  className={`px-2 py-1 rounded text-xs transition-colors ${
                    filters.cityZone.includes(zone)
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
                  }`}
                >
                  {zone.replace('_', '-')}
                </button>
              ))}
            </div>
          </section>

          {/* Mi ubicación */}
          <LocationSection />

          {/* Distancia metro */}
          <section>
            <label className="block text-xs text-gray-400 uppercase tracking-wide mb-1">
              Dist. máx. metro:{' '}
              <span className="text-white normal-case">
                {filters.maxDistMetro === 0 ? 'Sin filtro' : `${filters.maxDistMetro} km`}
              </span>
            </label>
            <input
              type="range"
              min={0} max={5} step={0.5}
              value={filters.maxDistMetro}
              onChange={e => setMaxDistMetro(parseFloat(e.target.value))}
              className="w-full accent-blue-500"
            />
          </section>

          {/* Scoring profile */}
          <section>
            <p className="text-xs font-semibold text-gray-400 mb-2">Perfil de Scoring</p>
            <div className="flex flex-col gap-1">
              {(Object.keys(PROFILE_LABELS) as ProfileName[]).map((name) => (
                <label key={name} className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="radio"
                    name="profile"
                    value={name}
                    checked={filters.profileName === name}
                    onChange={() => setFilters({ profileName: name })}
                    className="accent-blue-500"
                  />
                  <span className="text-gray-300">{PROFILE_LABELS[name]}</span>
                </label>
              ))}
            </div>

            {/* Profile weight summary for non-custom */}
            {filters.profileName !== 'custom' && (
              <div className="mt-2 bg-gray-800 rounded p-2 text-xs text-gray-400">
                {profiles.find((p) => p.name === filters.profileName)?.description}
              </div>
            )}

            {/* Custom weight sliders */}
            {filters.profileName === 'custom' && (
              <div className="mt-3 flex flex-col gap-3">
                {WEIGHT_KEYS.map((key) => (
                  <div key={key}>
                    <label className="flex justify-between text-xs text-gray-400 mb-1">
                      <span>{WEIGHT_LABELS[key]}</span>
                      <span className="text-white">
                        {totalCustomWeight > 0
                          ? `${((filters.customWeights[key] / totalCustomWeight) * 100).toFixed(0)}%`
                          : '0%'}
                      </span>
                    </label>
                    <input
                      type="range" min={0} max={1} step={0.05}
                      value={filters.customWeights[key]}
                      onChange={(e) =>
                        setFilters({
                          customWeights: {
                            ...filters.customWeights,
                            [key]: parseFloat(e.target.value),
                          },
                        })
                      }
                      className="w-full accent-blue-500"
                    />
                  </div>
                ))}
                {totalCustomWeight === 0 && (
                  <p className="text-red-400 text-xs">Al menos un peso debe ser &gt; 0</p>
                )}
              </div>
            )}
          </section>

          {/* Guardar búsqueda */}
          <section className="border-t border-gray-800 pt-4">
            {authUser && authToken ? (
              <div className="flex flex-col gap-2">
                <button
                  disabled={saving}
                  onClick={async () => {
                    setSaving(true)
                    setSaveMsg(null)
                    const name = `Búsqueda ${new Date().toLocaleDateString('es-CL')}`
                    const filterPayload: Record<string, unknown> = {
                      minScore: filters.minScore,
                      projectTypes: filters.projectTypes,
                      counties: filters.counties,
                      cityZone: filters.cityZone,
                      maxDistMetro: filters.maxDistMetro,
                      profileName: filters.profileName,
                    }
                    try {
                      await createSavedSearch(authToken, name, filterPayload)
                      const updated = await fetchSavedSearches(authToken)
                      setSavedSearches(updated)
                      setSaveMsg('Guardada')
                    } catch {
                      setSaveMsg('Error al guardar')
                    } finally {
                      setSaving(false)
                      setTimeout(() => setSaveMsg(null), 2500)
                    }
                  }}
                  className="flex items-center justify-center gap-1.5 w-full py-2 rounded bg-blue-700 hover:bg-blue-600 text-white text-xs font-medium disabled:opacity-50 transition-colors"
                >
                  <Bookmark size={13} />
                  {saving ? 'Guardando...' : 'Guardar búsqueda actual'}
                </button>
                {saveMsg && (
                  <p className={`text-xs text-center ${saveMsg === 'Guardada' ? 'text-green-400' : 'text-red-400'}`}>
                    {saveMsg}
                  </p>
                )}
              </div>
            ) : (
              <button
                onClick={() => setAuthModalOpen(true)}
                className="flex items-center justify-center gap-1.5 w-full py-2 rounded bg-gray-700 hover:bg-gray-600 text-gray-300 text-xs transition-colors"
              >
                <Bookmark size={13} />
                Entrar para guardar búsquedas
              </button>
            )}
          </section>
        </div>
      )}
    </aside>
    </>
  )
}
