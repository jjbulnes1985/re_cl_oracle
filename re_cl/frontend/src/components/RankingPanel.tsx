import { useQuery } from '@tanstack/react-query'
import { TrendingUp, TrendingDown, PlusCircle, Bookmark, BookmarkCheck, Download, Globe } from 'lucide-react'
import { fetchPropertiesWithCount, scoreWithProfile, exportPropertiesCSV } from '../api'
import { useAppStore } from '../store'
import type { Property } from '../types'
import { clsx } from 'clsx'

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371
  const dLat = (lat2 - lat1) * Math.PI / 180
  const dLon = (lon2 - lon1) * Math.PI / 180
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.asin(Math.sqrt(a))
}

// ── CSV export ────────────────────────────────────────────────────────────────

function exportRankingCSV(items: Property[]) {
  const headers: (keyof Property)[] = [
    'score_id', 'county_name', 'project_type', 'city_zone',
    'opportunity_score', 'uf_m2_building', 'gap_pct',
    'dist_metro_km', 'age', 'amenities_500m',
  ]
  const rows = items.map((p) => headers.map((h) => p[h] ?? ''))
  const csv = [headers, ...rows].map((r) => r.join(',')).join('\n')
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 're_cl_ranking.csv'
  a.click()
  URL.revokeObjectURL(url)
}

// ── Score badge ───────────────────────────────────────────────────────────────

interface BadgeConfig {
  label: string
  bgCls: string
  textCls: string
  barCls: string
}

function getScoreBadge(score: number): BadgeConfig {
  if (score >= 0.8) return { label: 'Alta',      bgCls: 'bg-red-600/25',    textCls: 'text-red-400',    barCls: 'bg-red-500' }
  if (score >= 0.6) return { label: 'Media-Alta', bgCls: 'bg-orange-600/25', textCls: 'text-orange-400', barCls: 'bg-orange-500' }
  if (score >= 0.4) return { label: 'Media',      bgCls: 'bg-yellow-600/25', textCls: 'text-yellow-400', barCls: 'bg-yellow-500' }
  return               { label: 'Baja',       bgCls: 'bg-blue-600/25',   textCls: 'text-blue-400',   barCls: 'bg-blue-500' }
}

// ── Component ─────────────────────────────────────────────────────────────────

export function RankingPanel() {
  const {
    filters, setSelectedProperty, setActiveTab,
    compareA, compareB, setCompareA, setCompareB,
    addToWatchlist, removeFromWatchlist, isInWatchlist,
    userLocation, maxDistFromUser,
  } = useAppStore()
  const isCustomProfile = filters.profileName !== 'default'

  const { data: baseFetch, isLoading: loadingBase } = useQuery({
    queryKey: ['properties-rank', filters.minScore, filters.projectTypes],
    queryFn: () =>
      fetchPropertiesWithCount({ min_score: filters.minScore, limit: 200 }),
    enabled: !isCustomProfile,
  })
  const baseProps = baseFetch?.data ?? []
  const totalCount = baseFetch?.total ?? 0

  const profileWeights = filters.profileName === 'custom'
    ? { weights: filters.customWeights }
    : { profile: filters.profileName }

  const { data: scoredProps = [], isLoading: loadingScored } = useQuery({
    queryKey: ['scored-rank', filters.profileName, filters.customWeights, filters.minScore],
    queryFn: () => scoreWithProfile({ ...profileWeights, limit: 200 }),
    enabled: isCustomProfile,
  })

  const loading = loadingBase || loadingScored

  const applyNewFilters = (p: Property) => {
    const { searchText, cityZone, maxDistMetro } = filters
    if (searchText) {
      const q = searchText.toLowerCase()
      if (!(p.county_name ?? '').toLowerCase().includes(q)) return false
    }
    if (cityZone.length > 0) {
      if (!cityZone.includes(p.city_zone ?? '')) return false
    }
    if (maxDistMetro > 0) {
      const dist = p.dist_metro_km
      if (dist == null || dist > maxDistMetro) return false
    }
    return true
  }

  const items = (isCustomProfile ? scoredProps : baseProps)
    .filter((p) => (p.opportunity_score ?? 0) >= filters.minScore && applyNewFilters(p as Property))
    .filter((p) => {
      if (!userLocation || maxDistFromUser === 0) return true
      const prop = p as Property
      if (!prop.latitude || !prop.longitude) return false
      return haversineKm(userLocation.lat, userLocation.lon, prop.latitude, prop.longitude) <= maxDistFromUser
    })
    .slice(0, 100)

  // Breakdown counts for header
  const alta     = items.filter((p) => (p.opportunity_score ?? 0) >= 0.8).length
  const mediaAlta = items.filter((p) => { const s = p.opportunity_score ?? 0; return s >= 0.6 && s < 0.8 }).length
  const media    = items.filter((p) => { const s = p.opportunity_score ?? 0; return s >= 0.4 && s < 0.6 }).length
  const baja     = items.filter((p) => (p.opportunity_score ?? 0) < 0.4).length

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-white">Top Oportunidades</h2>
          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-500">{items.length} propiedades</span>
            {items.length > 0 && (
              <button
                onClick={() => exportRankingCSV(items as Property[])}
                title="Exportar CSV"
                className="flex items-center gap-1 text-xs text-gray-400 hover:text-white border border-gray-700 hover:border-gray-500 px-2 py-0.5 rounded transition-colors"
              >
                <Download size={11} />
                CSV
              </button>
            )}
            <button
              onClick={() => exportPropertiesCSV({ min_score: filters.minScore, limit: 1000 })}
              title="Exportar todo (CSV)"
              className="flex items-center gap-1 text-xs text-green-400 hover:text-green-300 border border-gray-700 hover:border-gray-500 px-2 py-0.5 rounded transition-colors"
            >
              <Globe size={11} />
              Exportar todo (CSV)
            </button>
          </div>
        </div>
        {/* Score breakdown pills */}
        {!loading && items.length > 0 && (
          <div className="flex gap-1.5 flex-wrap">
            {alta > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-red-600/25 text-red-400 border border-red-600/30">
                <span className="w-1.5 h-1.5 rounded-full bg-red-500 inline-block" />
                {alta} alta
              </span>
            )}
            {mediaAlta > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-orange-600/25 text-orange-400 border border-orange-600/30">
                <span className="w-1.5 h-1.5 rounded-full bg-orange-500 inline-block" />
                {mediaAlta} m-alta
              </span>
            )}
            {media > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-yellow-600/25 text-yellow-400 border border-yellow-600/30">
                <span className="w-1.5 h-1.5 rounded-full bg-yellow-500 inline-block" />
                {media} media
              </span>
            )}
            {baja > 0 && (
              <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full bg-blue-600/25 text-blue-400 border border-blue-600/30">
                <span className="w-1.5 h-1.5 rounded-full bg-blue-500 inline-block" />
                {baja} baja
              </span>
            )}
          </div>
        )}
      </div>

      {!isCustomProfile && !loading && totalCount > 0 && (
        <div className="text-xs text-gray-500 px-3 py-1.5 border-b border-gray-800">
          Mostrando {items.length} de {totalCount.toLocaleString()} propiedades
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center h-24 text-gray-500 text-sm">
          Cargando…
        </div>
      )}

      {!loading && items.length === 0 && (
        <div className="flex flex-col items-center justify-center py-12 gap-2 text-center px-4">
          <p className="text-gray-500 text-sm">Sin propiedades con score ≥ {(filters.minScore * 100).toFixed(0)}%</p>
          <p className="text-gray-600 text-xs">
            El scoring puede estar corriendo en background. Intenta bajar el score mínimo o espera unos minutos.
          </p>
        </div>
      )}

      <div className="overflow-y-auto flex-1 divide-y divide-gray-800">
        {items.map((prop, i) => {
          const score = prop.opportunity_score ?? 0
          const gap   = ((prop as Property).calibrated_gap_pct ?? prop.gap_pct ?? 0) * 100
          const isUndervalued = gap < 0
          const badge = getScoreBadge(score)

          const isCompareA = compareA?.score_id === prop.score_id
          const isCompareB = compareB?.score_id === prop.score_id
          const compareSlot = isCompareA ? 'A' : isCompareB ? 'B' : null
          const inWatchlist = isInWatchlist(prop.score_id)

          function handleBookmark(e: React.MouseEvent) {
            e.stopPropagation()
            if (inWatchlist) {
              removeFromWatchlist(prop.score_id)
            } else {
              addToWatchlist(prop as Property)
            }
          }

          function handleCompare(e: React.MouseEvent) {
            e.stopPropagation()
            const p = prop as Property
            if (isCompareA) { setCompareA(null); return }
            if (isCompareB) { setCompareB(null); return }
            if (compareA === null) { setCompareA(p); return }
            if (compareB === null) { setCompareB(p); return }
            // Both slots full — replace A (cycle)
            setCompareA(p)
          }

          return (
            <button
              key={prop.score_id}
              onClick={() => {
                setSelectedProperty(prop as Property)
                setActiveTab('detail')
              }}
              className="w-full text-left px-4 py-3 min-h-[44px] hover:bg-gray-800 transition-colors"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-xs text-gray-600 w-5 shrink-0">{i + 1}</span>
                  <div className="min-w-0">
                    <p className="text-xs font-medium text-white truncate">
                      {prop.county_name} · {prop.project_type}
                    </p>
                    <div className="flex items-center gap-1 mt-0.5">
                      {isUndervalued
                        ? <TrendingDown size={10} className="text-green-400" />
                        : <TrendingUp   size={10} className="text-red-400" />}
                      <span className={clsx('text-xs', isUndervalued ? 'text-green-400' : 'text-red-400')}>
                        {gap.toFixed(1)}% vs modelo
                      </span>
                    </div>
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {/* Watchlist bookmark button */}
                  <button
                    onClick={handleBookmark}
                    title={inWatchlist ? 'Quitar de watchlist' : 'Guardar en watchlist'}
                    className={clsx(
                      'transition-colors',
                      inWatchlist ? 'text-yellow-400 hover:text-yellow-300' : 'text-gray-600 hover:text-gray-300'
                    )}
                  >
                    {inWatchlist ? <BookmarkCheck size={13} /> : <Bookmark size={13} />}
                  </button>

                  {/* Compare button */}
                  <button
                    onClick={handleCompare}
                    title={compareSlot ? `Quitar de slot ${compareSlot}` : 'Agregar a comparador'}
                    className={clsx(
                      'flex items-center justify-center w-5 h-5 rounded-full text-[10px] font-bold transition-colors',
                      compareSlot === 'A'
                        ? 'bg-blue-600 text-white'
                        : compareSlot === 'B'
                        ? 'bg-purple-600 text-white'
                        : 'text-gray-600 hover:text-gray-300'
                    )}
                  >
                    {compareSlot ?? <PlusCircle size={13} />}
                  </button>

                  {/* Score badge + bar */}
                  <div className="text-right">
                    <div className={clsx(
                      'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold mb-1',
                      badge.bgCls, badge.textCls
                    )}>
                      {score.toFixed(3)}
                      <span className="text-[10px] opacity-75">· {badge.label}</span>
                    </div>
                    <div className="w-16 h-1.5 bg-gray-700 rounded-full">
                      <div
                        className={clsx('h-full rounded-full', badge.barCls)}
                        style={{ width: `${score * 100}%` }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
