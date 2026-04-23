import { useQuery } from '@tanstack/react-query'
import { X, TrendingDown, TrendingUp, ArrowUpRight, ArrowDownRight } from 'lucide-react'
import { fetchProperty, fetchComparables } from '../api'
import { useAppStore } from '../store'

// ── SVG Radar Chart ──────────────────────────────────────────────────────────

interface RadarDimension {
  label: string
  value: number  // 0–1
}

function RadarChart({ dimensions }: { dimensions: RadarDimension[] }) {
  const cx = 100
  const cy = 100
  const r  = 72
  const n  = dimensions.length

  // Compute x,y for a point at angle + radius fraction
  const point = (index: number, fraction: number) => {
    const angle = (Math.PI * 2 * index) / n - Math.PI / 2
    return {
      x: cx + r * fraction * Math.cos(angle),
      y: cy + r * fraction * Math.sin(angle),
    }
  }

  // Grid rings
  const rings = [0.25, 0.5, 0.75, 1.0]

  // Axis endpoints (full radius)
  const axes = dimensions.map((_, i) => point(i, 1))

  // Data polygon
  const dataPoints = dimensions.map((d, i) => point(i, Math.max(0, Math.min(1, d.value))))
  const polyPath =
    dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ') + ' Z'

  // Ring paths
  const ringPath = (frac: number) =>
    dimensions
      .map((_, i) => {
        const p = point(i, frac)
        return `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
      })
      .join(' ') + ' Z'

  // Label positions (slightly beyond radius)
  const labelOffset = 1.22
  const labels = dimensions.map((d, i) => {
    const p = point(i, labelOffset)
    return { ...p, label: d.label, value: d.value }
  })

  return (
    <svg viewBox="0 0 200 200" className="w-full" style={{ maxHeight: 200 }}>
      {/* Grid rings */}
      {rings.map((frac) => (
        <path
          key={frac}
          d={ringPath(frac)}
          fill="none"
          stroke="#374151"
          strokeWidth={frac === 1 ? 1.5 : 0.8}
        />
      ))}

      {/* Axes */}
      {axes.map((end, i) => (
        <line
          key={i}
          x1={cx} y1={cy}
          x2={end.x.toFixed(1)} y2={end.y.toFixed(1)}
          stroke="#374151"
          strokeWidth={0.8}
        />
      ))}

      {/* Data polygon fill */}
      <path d={polyPath} fill="rgba(59,130,246,0.18)" stroke="#3b82f6" strokeWidth={1.5} />

      {/* Data point dots */}
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={3} fill="#3b82f6" />
      ))}

      {/* Labels */}
      {labels.map((l, i) => {
        // Determine text-anchor based on horizontal position
        const anchor = l.x < cx - 8 ? 'end' : l.x > cx + 8 ? 'start' : 'middle'
        const scoreColor =
          l.value >= 0.8 ? '#ef4444' :
          l.value >= 0.6 ? '#f97316' :
          l.value >= 0.4 ? '#eab308' : '#60a5fa'

        return (
          <g key={i}>
            <text
              x={l.x.toFixed(1)}
              y={(l.y - 4).toFixed(1)}
              fontSize={7.5}
              fill="#9ca3af"
              textAnchor={anchor}
            >
              {l.label}
            </text>
            <text
              x={l.x.toFixed(1)}
              y={(l.y + 5).toFixed(1)}
              fontSize={7}
              fill={scoreColor}
              textAnchor={anchor}
              fontWeight="bold"
            >
              {(l.value * 100).toFixed(0)}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ── Score badge helper ────────────────────────────────────────────────────────

function scoreBadge(score: number) {
  if (score >= 0.8) return { label: 'Alta',       cls: 'bg-red-600/30 text-red-400 border border-red-600/50' }
  if (score >= 0.6) return { label: 'Media-Alta',  cls: 'bg-orange-600/30 text-orange-400 border border-orange-600/50' }
  if (score >= 0.4) return { label: 'Media',       cls: 'bg-yellow-600/30 text-yellow-400 border border-yellow-600/50' }
  return               { label: 'Baja',        cls: 'bg-blue-600/30 text-blue-400 border border-blue-600/50' }
}

// ── Main component ────────────────────────────────────────────────────────────

export function DetailPanel() {
  const { selectedProperty, setSelectedProperty } = useAppStore()

  const { data: detail, isLoading, isError } = useQuery({
    queryKey: ['property', selectedProperty?.score_id],
    queryFn:  () => fetchProperty(selectedProperty!.score_id),
    enabled:  !!selectedProperty,
    retry: 1,
  })

  const { data: comparables = [] } = useQuery({
    queryKey: ['comparables', selectedProperty?.score_id],
    queryFn:  () => fetchComparables(selectedProperty!.score_id),
    enabled:  !!selectedProperty,
  })

  if (!selectedProperty) {
    return (
      <div className="flex items-center justify-center h-full text-gray-600 text-sm">
        Selecciona una propiedad en el mapa o el ranking
      </div>
    )
  }

  const score = detail?.opportunity_score ?? selectedProperty.opportunity_score ?? 0
  const rawGapPct = detail?.calibrated_gap_pct ?? detail?.gap_pct ?? selectedProperty.gap_pct ?? 0
  const gap   = rawGapPct * 100
  const isUndervalued = gap < 0
  const isCalibrated = detail?.calibrated_gap_pct != null
  const badge = scoreBadge(score)

  // Build radar dimensions from available data
  // Each value is normalised to 0–1
  const undervalScore  = Math.max(0, Math.min(1, (detail?.undervaluation_score ?? selectedProperty.undervaluation_score ?? 0)))
  const priceVsMedian  = Math.max(0, Math.min(1, detail?.gap_pct != null
    ? 1 - Math.abs(detail.gap_pct)  // closer to 0 gap = better median position
    : 0.5))
  const confidence     = Math.max(0, Math.min(1, detail?.data_confidence ?? selectedProperty.data_confidence ?? 0))
  // Location: use gap_percentile as proxy when available, else 0.5
  const locationScore  = Math.max(0, Math.min(1, detail?.gap_percentile != null ? detail.gap_percentile / 100 : 0.5))
  // Market score: derived from undervaluation + confidence composite
  const marketScore    = Math.max(0, Math.min(1, (undervalScore + confidence) / 2))

  const radarDimensions: RadarDimension[] = [
    { label: 'Subvaloración', value: undervalScore },
    { label: 'Pos. Precio',   value: priceVsMedian },
    { label: 'Confianza',     value: confidence },
    { label: 'Ubicación',     value: locationScore },
    { label: 'Mercado',       value: marketScore },
  ]

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div>
          <h2 className="text-sm font-semibold text-white">
            {selectedProperty.county_name} · {selectedProperty.project_type}
          </h2>
          <p className="text-xs text-gray-500">ID: {selectedProperty.score_id}</p>
        </div>
        <button
          onClick={() => setSelectedProperty(null)}
          className="text-gray-500 hover:text-white"
        >
          <X size={16} />
        </button>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center h-24 text-gray-500 text-sm">Cargando…</div>
      )}

      {isError && !isLoading && (
        <div className="flex flex-col items-center justify-center h-24 gap-2 text-sm">
          <p className="text-red-400">No se pudo cargar el detalle de esta propiedad.</p>
          <p className="text-gray-600 text-xs">
            Es posible que el scoring aún esté en proceso. Intenta de nuevo en unos momentos.
          </p>
        </div>
      )}

      {!isLoading && !isError && !detail && selectedProperty && (
        <div className="flex flex-col items-center justify-center h-24 gap-2 text-sm">
          <p className="text-gray-500">Propiedad no encontrada en el modelo de scoring.</p>
          <p className="text-gray-600 text-xs">
            Los datos de scoring pueden estar actualizándose.
          </p>
        </div>
      )}

      {detail && (
        <div className="p-4 flex flex-col gap-4">
          {/* Score + badge */}
          <div className="bg-gray-800 rounded-lg p-3">
            <div className="flex items-start justify-between mb-1">
              <p className="text-xs text-gray-400">Opportunity Score</p>
              <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${badge.cls}`}>
                {badge.label}
              </span>
            </div>
            <p className="text-3xl font-bold text-white">{score.toFixed(3)}</p>
            <div className="w-full h-2 bg-gray-700 rounded-full mt-2">
              <div
                className="h-full rounded-full bg-gradient-to-r from-blue-500 via-yellow-500 to-red-500"
                style={{ width: `${score * 100}%` }}
              />
            </div>
          </div>

          {/* Radar chart */}
          <div className="bg-gray-800 rounded-lg p-3">
            <p className="text-xs font-semibold text-gray-400 mb-2">Perfil multidimensional</p>
            <RadarChart dimensions={radarDimensions} />
          </div>

          {/* Key metrics */}
          <div className="grid grid-cols-2 gap-2">
            <Metric label="UF/m² Real"      value={`${detail.uf_m2_building?.toFixed(1) ?? '–'}`} />
            <Metric
              label={isCalibrated ? 'UF/m² Predicho (calibrado)' : 'UF/m² Predicho'}
              value={`${(detail.calibrated_predicted_uf_m2 ?? detail.predicted_uf_m2)?.toFixed(1) ?? '–'}${isCalibrated ? ' ✦' : ''}`}
            />
            <Metric
              label={isCalibrated ? 'Gap vs modelo (calibrado)' : 'Gap vs modelo'}
              value={`${gap.toFixed(1)}%${isCalibrated ? ' ✦' : ''}`}
              icon={isUndervalued ? <TrendingDown size={12} className="text-green-400" /> : <TrendingUp size={12} className="text-red-400" />}
              valueClass={isUndervalued ? 'text-green-400' : 'text-red-400'}
            />
            <Metric label="Confianza"       value={`${((detail.data_confidence ?? 0) * 100).toFixed(0)}%`} />
            <Metric label="Superficie"      value={`${detail.surface_m2?.toFixed(0) ?? '–'} m²`} />
            <Metric label="Año"             value={`${detail.year ?? '–'}`} />
          </div>

          {/* Calibration note */}
          {isCalibrated && (
            <div className="text-xs text-gray-500 -mt-2 px-1">
              ✦ calibrado por comuna
              {detail.commune_model_bias_pct != null && Math.abs(detail.commune_model_bias_pct) > 5 && (
                <span className="ml-2 inline-flex items-center px-1.5 py-0.5 rounded bg-amber-900/40 text-amber-400 border border-amber-700/50">
                  Modelo corregido {detail.commune_model_bias_pct > 0 ? '+' : ''}{detail.commune_model_bias_pct.toFixed(1)}% para esta comuna
                </span>
              )}
            </div>
          )}

          {/* SHAP drivers */}
          {detail.shap_top_features && detail.shap_top_features.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 mb-2">Principales drivers del score</p>
              <div className="flex flex-col gap-2">
                {detail.shap_top_features.map((feat) => (
                  <div key={feat.feature} className="flex items-center justify-between bg-gray-800 rounded p-2">
                    <span className="text-xs text-gray-300">{feat.feature}</span>
                    <div className="flex items-center gap-1">
                      {feat.direction === 'up'
                        ? <ArrowUpRight size={12} className="text-green-400" />
                        : <ArrowDownRight size={12} className="text-red-400" />}
                      <span className={`text-xs font-mono ${feat.direction === 'up' ? 'text-green-400' : 'text-red-400'}`}>
                        {feat.shap > 0 ? '+' : ''}{feat.shap.toFixed(3)}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* V4 thesis + OSM features */}
          {(detail.age != null || detail.city_zone != null || detail.dist_metro_km != null || detail.amenities_500m != null) && (
            <div>
              <p className="text-xs font-semibold text-gray-400 mb-2">Datos V4</p>
              <div className="grid grid-cols-2 gap-2">
                {detail.age != null && (
                  <Metric
                    label="Edad"
                    value={detail.construction_year_bucket
                      ? `${detail.age} años (${detail.construction_year_bucket})`
                      : `${detail.age} años`}
                  />
                )}
                {detail.city_zone != null && (
                  <Metric label="Zona" value={detail.city_zone} />
                )}
                {detail.dist_metro_km != null && (
                  <Metric label="Dist. Metro" value={`${detail.dist_metro_km.toFixed(2)} km`} />
                )}
                {detail.dist_school_km != null && (
                  <Metric label="Dist. Colegio" value={`${detail.dist_school_km.toFixed(2)} km`} />
                )}
                {detail.dist_park_km != null && (
                  <Metric label="Dist. Parque" value={`${detail.dist_park_km.toFixed(2)} km`} />
                )}
                {detail.dist_bus_stop_km != null && (
                  <Metric label="Dist. Bus" value={`${detail.dist_bus_stop_km.toFixed(2)} km`} />
                )}
                {detail.dist_hospital_km != null && (
                  <Metric label="Dist. Hospital" value={`${detail.dist_hospital_km.toFixed(2)} km`} />
                )}
                {detail.dist_mall_km != null && (
                  <Metric label="Dist. Mall" value={`${detail.dist_mall_km.toFixed(2)} km`} />
                )}
                {detail.amenities_500m != null && (
                  <Metric label="Amenidades 500m" value={`${detail.amenities_500m}`} />
                )}
                {detail.amenities_1km != null && (
                  <Metric label="Amenidades 1km" value={`${detail.amenities_1km}`} />
                )}
              </div>
            </div>
          )}

          {/* Location */}
          {detail.latitude && detail.longitude && (
            <div>
              <p className="text-xs font-semibold text-gray-400 mb-1">Ubicación</p>
              <p className="text-xs text-gray-400 font-mono">
                {detail.latitude.toFixed(5)}, {detail.longitude.toFixed(5)}
              </p>
            </div>
          )}

          {/* Comparables cercanos */}
          {comparables.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 mb-2">Comparables cercanos</p>
              <div className="flex flex-col gap-1">
                {comparables.map((comp) => {
                  const cb = scoreBadge(comp.opportunity_score ?? 0)
                  return (
                    <div
                      key={comp.score_id}
                      className="bg-gray-800 rounded p-2 flex items-center justify-between gap-2"
                    >
                      <div className="flex flex-col min-w-0">
                        <span className="text-xs text-gray-300 truncate">
                          {comp.county_name ?? '–'}
                        </span>
                        <span className="text-xs text-gray-500">
                          {comp.surface_m2?.toFixed(0) ?? '–'} m²
                          {comp.uf_m2_building != null ? ` · ${comp.uf_m2_building.toFixed(1)} UF/m²` : ''}
                        </span>
                      </div>
                      <span className={`text-xs font-semibold px-1.5 py-0.5 rounded-full whitespace-nowrap ${cb.cls}`}>
                        {(comp.opportunity_score ?? 0).toFixed(2)}
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Metric({
  label,
  value,
  icon,
  valueClass = 'text-white',
}: {
  label: string
  value: string
  icon?: React.ReactNode
  valueClass?: string
}) {
  return (
    <div className="bg-gray-800 rounded p-2">
      <p className="text-xs text-gray-500">{label}</p>
      <div className="flex items-center gap-1 mt-0.5">
        {icon}
        <span className={`text-sm font-semibold ${valueClass}`}>{value}</span>
      </div>
    </div>
  )
}
