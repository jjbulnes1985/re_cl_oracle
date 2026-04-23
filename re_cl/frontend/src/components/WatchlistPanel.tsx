import { useState, useEffect } from 'react'
import { Star, Trash2, ExternalLink, Download, Bookmark, Play, User } from 'lucide-react'
import { useAppStore } from '../store'
import { fetchSavedSearches, deleteSavedSearch } from '../api'
import type { Property } from '../types'
import { clsx } from 'clsx'

// ── CSV export ────────────────────────────────────────────────────────────────

function exportWatchlistCSV(watchlist: Property[]) {
  const headers: (keyof Property)[] = [
    'score_id', 'county_name', 'project_type', 'city_zone',
    'opportunity_score', 'uf_m2_building', 'gap_pct',
    'dist_metro_km', 'age', 'amenities_500m',
  ]
  const rows = watchlist.map((p) => headers.map((h) => p[h] ?? ''))
  const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 're_cl_watchlist.csv'
  a.click()
  URL.revokeObjectURL(url)
}

// ── Score badge ───────────────────────────────────────────────────────────────

function scoreBadgeClass(score: number) {
  if (score >= 0.8) return { bg: 'bg-red-600/25',    text: 'text-red-400' }
  if (score >= 0.6) return { bg: 'bg-orange-600/25', text: 'text-orange-400' }
  if (score >= 0.4) return { bg: 'bg-yellow-600/25', text: 'text-yellow-400' }
  return               { bg: 'bg-blue-600/25',   text: 'text-blue-400' }
}

// ── Property card ─────────────────────────────────────────────────────────────

function WatchCard({ prop }: { prop: Property }) {
  const { removeFromWatchlist, setSelectedProperty } = useAppStore()
  const score = prop.opportunity_score ?? 0
  const gap   = (prop.gap_pct ?? 0) * 100
  const badge = scoreBadgeClass(score)

  return (
    <div className="bg-gray-800 border border-gray-700 rounded-lg p-3 flex flex-col gap-2">
      {/* Top row: score badge + delete */}
      <div className="flex items-center justify-between">
        <span className={clsx('text-xs font-semibold px-2 py-0.5 rounded-full', badge.bg, badge.text)}>
          {score.toFixed(3)}
        </span>
        <button
          onClick={() => removeFromWatchlist(prop.score_id)}
          title="Eliminar de watchlist"
          className="text-gray-600 hover:text-red-400 transition-colors"
        >
          <Trash2 size={13} />
        </button>
      </div>

      {/* Property info */}
      <div>
        <p className="text-xs font-medium text-white truncate">
          {prop.county_name ?? '—'}
        </p>
        <p className="text-xs text-gray-400 truncate">
          {prop.project_type ?? '—'}
          {prop.city_zone ? ` · ${prop.city_zone}` : ''}
        </p>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs">
        {prop.uf_m2_building != null && (
          <>
            <span className="text-gray-500">UF/m²</span>
            <span className="text-gray-200 text-right">{prop.uf_m2_building.toFixed(1)}</span>
          </>
        )}
        <span className="text-gray-500">Gap vs modelo</span>
        <span className={clsx('text-right', gap < 0 ? 'text-green-400' : 'text-red-400')}>
          {gap.toFixed(1)}%
        </span>
        {prop.dist_metro_km != null && (
          <>
            <span className="text-gray-500">Metro</span>
            <span className="text-gray-200 text-right">{prop.dist_metro_km.toFixed(2)} km</span>
          </>
        )}
      </div>

      {/* Ver detalle */}
      <button
        onClick={() => setSelectedProperty(prop)}
        className="mt-1 flex items-center justify-center gap-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
      >
        <ExternalLink size={11} />
        Ver detalle
      </button>
    </div>
  )
}

// ── Saved searches section ────────────────────────────────────────────────────

function SavedSearchesSection() {
  const { authToken, authUser, savedSearches, setSavedSearches, setFilters, setAuthModalOpen } = useAppStore()
  const [deleting, setDeleting] = useState<number | null>(null)

  // Load saved searches whenever token changes
  useEffect(() => {
    if (!authToken) return
    fetchSavedSearches(authToken).then(setSavedSearches).catch(() => {})
  }, [authToken]) // eslint-disable-line react-hooks/exhaustive-deps

  const applySearch = (filters: Record<string, unknown>) => {
    setFilters({
      minScore:     typeof filters.minScore === 'number'    ? filters.minScore     : 0.5,
      projectTypes: Array.isArray(filters.projectTypes)     ? filters.projectTypes : [],
      counties:     Array.isArray(filters.counties)         ? filters.counties     : [],
      cityZone:     Array.isArray(filters.cityZone)         ? filters.cityZone     : [],
      maxDistMetro: typeof filters.maxDistMetro === 'number' ? filters.maxDistMetro : 0,
    })
  }

  const handleDelete = async (id: number) => {
    if (!authToken) return
    setDeleting(id)
    try {
      await deleteSavedSearch(authToken, id)
      const updated = await fetchSavedSearches(authToken)
      setSavedSearches(updated)
    } finally {
      setDeleting(null)
    }
  }

  if (!authUser || !authToken) {
    return (
      <div className="border-t border-gray-800 px-4 py-5">
        <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
          <Bookmark size={12} />Búsquedas Guardadas
        </h3>
        <button
          onClick={() => setAuthModalOpen(true)}
          className="flex items-center gap-1.5 w-full py-2 rounded bg-gray-800 hover:bg-gray-700 text-gray-400 text-xs transition-colors justify-center"
        >
          <User size={12} />Entra para ver tus búsquedas guardadas
        </button>
      </div>
    )
  }

  return (
    <div className="border-t border-gray-800 px-4 py-5">
      <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3 flex items-center gap-1.5">
        <Bookmark size={12} />Búsquedas Guardadas
        <span className="text-gray-600 font-normal normal-case">({savedSearches.length})</span>
      </h3>

      {savedSearches.length === 0 ? (
        <p className="text-xs text-gray-600 text-center py-2">
          Sin búsquedas guardadas — usa el sidebar para guardar filtros
        </p>
      ) : (
        <div className="flex flex-col gap-2">
          {savedSearches.map((s) => (
            <div key={s.id} className="flex items-center gap-2 bg-gray-800 rounded-lg px-3 py-2">
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-white truncate">{s.name}</p>
                <p className="text-[10px] text-gray-500 truncate">
                  {new Date(s.created_at).toLocaleDateString('es-CL')}
                </p>
              </div>
              <button
                onClick={() => applySearch(s.filters)}
                title="Aplicar filtros"
                className="text-blue-500 hover:text-blue-400 transition-colors shrink-0"
              >
                <Play size={13} />
              </button>
              <button
                onClick={() => handleDelete(s.id)}
                disabled={deleting === s.id}
                title="Eliminar búsqueda"
                className="text-gray-600 hover:text-red-400 transition-colors shrink-0 disabled:opacity-50"
              >
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ── Panel ─────────────────────────────────────────────────────────────────────

export function WatchlistPanel() {
  const { watchlist } = useAppStore()

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 flex items-center justify-between shrink-0">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <Star size={14} className="text-yellow-400" />
          Mi Watchlist
          <span className="text-gray-500 font-normal">({watchlist.length} propiedades)</span>
        </h2>

        {watchlist.length > 0 && (
          <button
            onClick={() => exportWatchlistCSV(watchlist)}
            className="flex items-center gap-1.5 text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 px-2.5 py-1 rounded transition-colors"
          >
            <Download size={12} />
            Exportar CSV
          </button>
        )}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto">
        <div className="p-4">
          {watchlist.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
              <Star size={40} className="text-gray-700" />
              <p className="text-sm text-gray-500">Sin propiedades guardadas</p>
              <p className="text-xs text-gray-600">
                Guarda propiedades desde el Ranking usando el icono
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {watchlist.map((prop) => (
                <WatchCard key={prop.score_id} prop={prop} />
              ))}
            </div>
          )}
        </div>

        {/* Saved searches section */}
        <SavedSearchesSection />
      </div>
    </div>
  )
}
