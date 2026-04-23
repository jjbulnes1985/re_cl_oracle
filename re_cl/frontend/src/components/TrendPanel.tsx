import { useState, useEffect } from 'react'
import { fetchPriceTrend, fetchPriceTrendByCommune, type PriceTrendPoint } from '../api'

// ── Color palette for multi-commune comparison ────────────────────────────────

const COMMUNE_COLORS = [
  '#3b82f6', '#ef4444', '#10b981', '#f59e0b',
  '#8b5cf6', '#ec4899', '#06b6d4', '#84cc16',
]

const TOP_COMMUNES = [
  'Las Condes',
  'Providencia',
  'La Florida',
  'Maipú',
  'Ñuñoa',
  'Santiago',
  'La Pintana',
  'Vitacura',
]

// ── SVG Line Chart (single commune) ──────────────────────────────────────────

function LineChart({
  data,
  width = 580,
  height = 240,
}: {
  data: PriceTrendPoint[]
  width?: number
  height?: number
}) {
  if (!data.length) return null

  const pad = { top: 20, right: 20, bottom: 40, left: 64 }
  const chartW = width - pad.left - pad.right
  const chartH = height - pad.top - pad.bottom

  const prices = data.map((d) => d.median_uf_m2)
  const minP = Math.min(...prices) * 0.95
  const maxP = Math.max(...prices) * 1.05

  const xScale = (i: number) =>
    data.length === 1 ? chartW / 2 : (i / (data.length - 1)) * chartW
  const yScale = (v: number) =>
    chartH - ((v - minP) / (maxP - minP)) * chartH

  const linePath = data
    .map((d, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(d.median_uf_m2)}`)
    .join(' ')

  // IQR band (p25 → p75)
  const bandTop = data.map(
    (d, i) => `${i === 0 ? 'M' : 'L'} ${xScale(i)} ${yScale(d.p75_uf_m2 ?? d.median_uf_m2)}`
  )
  const bandBottom = [...data]
    .reverse()
    .map(
      (d, i) =>
        `L ${xScale(data.length - 1 - i)} ${yScale(d.p25_uf_m2 ?? d.median_uf_m2)}`
    )
  const bandPath = [...bandTop, ...bandBottom, 'Z'].join(' ')

  // Y-axis ticks: 4 evenly spaced
  const yTicks = [0, 1, 2, 3].map((i) => minP + ((maxP - minP) * i) / 3)

  return (
    <svg width={width} height={height} className="overflow-visible">
      <g transform={`translate(${pad.left},${pad.top})`}>
        {/* Grid lines */}
        {yTicks.map((v, i) => (
          <line
            key={i}
            x1={0}
            x2={chartW}
            y1={yScale(v)}
            y2={yScale(v)}
            stroke="#374151"
            strokeDasharray="4 3"
            strokeWidth={1}
          />
        ))}

        {/* IQR band */}
        <path d={bandPath} fill="rgba(59,130,246,0.12)" />

        {/* Median line */}
        <path d={linePath} fill="none" stroke="#3b82f6" strokeWidth={2} strokeLinejoin="round" />

        {/* Data points */}
        {data.map((d, i) => (
          <g key={i}>
            <circle
              cx={xScale(i)}
              cy={yScale(d.median_uf_m2)}
              r={5}
              fill="#3b82f6"
              stroke="#1e3a5f"
              strokeWidth={1.5}
            />
            {/* Tooltip on hover via title */}
            <title>
              {d.period}: mediana {d.median_uf_m2} UF/m² | n={d.n_transactions.toLocaleString()}
            </title>
          </g>
        ))}

        {/* X-axis labels */}
        {data.map((d, i) => (
          <text
            key={i}
            x={xScale(i)}
            y={chartH + 18}
            textAnchor="middle"
            fill="#9ca3af"
            fontSize={10}
          >
            {d.period}
          </text>
        ))}

        {/* Y-axis labels */}
        {yTicks.map((v, i) => (
          <text
            key={i}
            x={-8}
            y={yScale(v)}
            textAnchor="end"
            dominantBaseline="middle"
            fill="#9ca3af"
            fontSize={10}
          >
            {v.toFixed(0)}
          </text>
        ))}

        {/* Axes */}
        <line x1={0} x2={0} y1={0} y2={chartH} stroke="#4b5563" strokeWidth={1} />
        <line x1={0} x2={chartW} y1={chartH} y2={chartH} stroke="#4b5563" strokeWidth={1} />
      </g>
    </svg>
  )
}

// ── SVG Multi-line Chart ──────────────────────────────────────────────────────

interface CommunceSeries {
  commune: string
  data: PriceTrendPoint[]
  color: string
}

function MultiLineChart({
  series,
  width = 580,
  height = 240,
}: {
  series: CommunceSeries[]
  width?: number
  height?: number
}) {
  const allData = series.flatMap((s) => s.data)
  if (!allData.length) return null

  const pad = { top: 20, right: 20, bottom: 40, left: 64 }
  const chartW = width - pad.left - pad.right
  const chartH = height - pad.top - pad.bottom

  // Collect all unique periods (sorted) to build a common x-axis
  const allPeriods = Array.from(new Set(allData.map((d) => d.period))).sort()

  const prices = allData.map((d) => d.median_uf_m2)
  const minP = Math.min(...prices) * 0.95
  const maxP = Math.max(...prices) * 1.05

  const xScale = (periodIndex: number) =>
    allPeriods.length === 1 ? chartW / 2 : (periodIndex / (allPeriods.length - 1)) * chartW
  const yScale = (v: number) =>
    chartH - ((v - minP) / (maxP - minP)) * chartH

  const yTicks = [0, 1, 2, 3].map((i) => minP + ((maxP - minP) * i) / 3)

  return (
    <svg width={width} height={height} className="overflow-visible">
      <g transform={`translate(${pad.left},${pad.top})`}>
        {/* Grid lines */}
        {yTicks.map((v, i) => (
          <line
            key={i}
            x1={0}
            x2={chartW}
            y1={yScale(v)}
            y2={yScale(v)}
            stroke="#374151"
            strokeDasharray="4 3"
            strokeWidth={1}
          />
        ))}

        {/* One line per commune */}
        {series.map((s) => {
          const linePath = s.data
            .map((d) => {
              const xi = allPeriods.indexOf(d.period)
              return `${xi === 0 ? 'M' : 'L'} ${xScale(xi)} ${yScale(d.median_uf_m2)}`
            })
            .join(' ')
          return (
            <path
              key={s.commune}
              d={linePath}
              fill="none"
              stroke={s.color}
              strokeWidth={2}
              strokeLinejoin="round"
            />
          )
        })}

        {/* Data points per commune */}
        {series.map((s) =>
          s.data.map((d, pi) => {
            const xi = allPeriods.indexOf(d.period)
            return (
              <g key={`${s.commune}-${pi}`}>
                <circle
                  cx={xScale(xi)}
                  cy={yScale(d.median_uf_m2)}
                  r={4}
                  fill={s.color}
                  stroke="#111827"
                  strokeWidth={1.5}
                />
                <title>
                  {s.commune} {d.period}: mediana {d.median_uf_m2} UF/m² | n={d.n_transactions.toLocaleString()}
                </title>
              </g>
            )
          })
        )}

        {/* X-axis labels */}
        {allPeriods.map((p, i) => (
          <text
            key={i}
            x={xScale(i)}
            y={chartH + 18}
            textAnchor="middle"
            fill="#9ca3af"
            fontSize={10}
          >
            {p}
          </text>
        ))}

        {/* Y-axis labels */}
        {yTicks.map((v, i) => (
          <text
            key={i}
            x={-8}
            y={yScale(v)}
            textAnchor="end"
            dominantBaseline="middle"
            fill="#9ca3af"
            fontSize={10}
          >
            {v.toFixed(0)}
          </text>
        ))}

        {/* Axes */}
        <line x1={0} x2={0} y1={0} y2={chartH} stroke="#4b5563" strokeWidth={1} />
        <line x1={0} x2={chartW} y1={chartH} y2={chartH} stroke="#4b5563" strokeWidth={1} />
      </g>
    </svg>
  )
}

// ── Main Panel ────────────────────────────────────────────────────────────────

const PROJECT_TYPES = [
  '',
  'Departamento',
  'Casa',
  'Oficina',
  'Local Comercial',
  'Bodega',
  'Terreno',
  'Estacionamiento',
]

export function TrendPanel() {
  const [projectType, setProjectType] = useState('')
  const [countyName, setCountyName] = useState('')
  const [data, setData] = useState<PriceTrendPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // ── Comparison mode state ────────────────────────────────────────────────
  const [compareMode, setCompareMode] = useState(false)
  const [selectedCommunes, setSelectedCommunes] = useState<string[]>(['Las Condes', 'Providencia'])
  const [communeData, setCommuneData] = useState<Array<{ county_name: string; trend: PriceTrendPoint[] }>>([])
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareError, setCompareError] = useState<string | null>(null)

  // Single-commune fetch
  useEffect(() => {
    if (compareMode) return
    setLoading(true)
    setError(null)
    fetchPriceTrend({
      project_type: projectType || undefined,
      county_name: countyName.trim() || undefined,
    })
      .then((rows) => {
        setData(rows)
        setLoading(false)
      })
      .catch((e) => {
        setError(String(e))
        setLoading(false)
      })
  }, [projectType, countyName, compareMode])

  // Multi-commune fetch
  useEffect(() => {
    if (!compareMode || selectedCommunes.length === 0) return
    setCompareLoading(true)
    setCompareError(null)
    fetchPriceTrendByCommune(selectedCommunes)
      .then((results) => {
        setCommuneData(results)
        setCompareLoading(false)
      })
      .catch((e) => {
        setCompareError(String(e))
        setCompareLoading(false)
      })
  }, [compareMode, selectedCommunes])

  const allSeries: CommunceSeries[] = communeData.map((c, i) => ({
    commune: c.county_name,
    data: c.trend,
    color: COMMUNE_COLORS[i % COMMUNE_COLORS.length],
  }))

  const toggleCommune = (commune: string) => {
    setSelectedCommunes((prev) =>
      prev.includes(commune) ? prev.filter((c) => c !== commune) : [...prev, commune]
    )
  }

  return (
    <div className="h-full overflow-y-auto bg-gray-950 text-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white">Tendencias de Precio</h2>
        <button
          onClick={() => setCompareMode((v) => !v)}
          className={`px-3 py-1.5 rounded text-sm font-medium transition-colors ${
            compareMode
              ? 'bg-blue-600 text-white hover:bg-blue-700'
              : 'bg-gray-700 text-gray-300 hover:bg-gray-600'
          }`}
        >
          {compareMode ? 'Comparando comunas' : 'Comparar comunas'}
        </button>
      </div>

      {compareMode ? (
        /* ── Comparison mode ── */
        <>
          <div className="mb-5">
            <p className="text-xs text-gray-400 mb-2">Selecciona comunas a comparar:</p>
            <div className="flex flex-wrap gap-2">
              {TOP_COMMUNES.map((c) => (
                <label
                  key={c}
                  className={`flex items-center gap-1.5 px-3 py-1 rounded-full text-xs cursor-pointer border transition-colors ${
                    selectedCommunes.includes(c)
                      ? 'border-blue-500 bg-blue-900/30 text-blue-300'
                      : 'border-gray-600 bg-gray-800 text-gray-400 hover:border-gray-500'
                  }`}
                >
                  <input
                    type="checkbox"
                    checked={selectedCommunes.includes(c)}
                    onChange={() => toggleCommune(c)}
                    className="sr-only"
                  />
                  <span
                    className="w-2 h-2 rounded-full flex-shrink-0"
                    style={{
                      backgroundColor: selectedCommunes.includes(c)
                        ? COMMUNE_COLORS[selectedCommunes.indexOf(c) % COMMUNE_COLORS.length]
                        : '#4b5563',
                    }}
                  />
                  {c}
                </label>
              ))}
            </div>
          </div>

          <div className="bg-gray-900 rounded-lg p-4 mb-6">
            {compareLoading && (
              <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
                Cargando datos de comunas...
              </div>
            )}
            {compareError && (
              <div className="flex items-center justify-center h-40 text-red-400 text-sm">
                Error: {compareError}
              </div>
            )}
            {!compareLoading && !compareError && allSeries.length > 0 && (
              <>
                <MultiLineChart series={allSeries} />
                {/* Legend */}
                <div className="flex flex-wrap gap-3 mt-2">
                  {allSeries.map((s) => (
                    <div key={s.commune} className="flex items-center gap-1.5 text-xs">
                      <div className="w-4 h-0.5" style={{ backgroundColor: s.color }} />
                      <span className="text-gray-300">{s.commune}</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            {!compareLoading && !compareError && selectedCommunes.length === 0 && (
              <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
                Selecciona al menos una comuna para comparar.
              </div>
            )}
          </div>
        </>
      ) : (
        /* ── Single commune mode ── */
        <>
          {/* Filters */}
          <div className="flex flex-wrap gap-4 mb-6">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-400">Tipo de propiedad</label>
              <select
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 focus:outline-none focus:border-blue-500"
              >
                {PROJECT_TYPES.map((t) => (
                  <option key={t} value={t}>
                    {t || 'Todos'}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-400">Comuna</label>
              <input
                type="text"
                value={countyName}
                onChange={(e) => setCountyName(e.target.value)}
                placeholder="Ej: Las Condes"
                className="bg-gray-800 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 w-44"
              />
            </div>
          </div>

          {/* Chart area */}
          <div className="bg-gray-900 rounded-lg p-4 mb-6">
            {loading && (
              <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
                Cargando datos...
              </div>
            )}
            {error && (
              <div className="flex items-center justify-center h-40 text-red-400 text-sm">
                Error: {error}
              </div>
            )}
            {!loading && !error && data.length === 0 && (
              <div className="flex items-center justify-center h-40 text-gray-500 text-sm">
                Sin datos para los filtros seleccionados.
              </div>
            )}
            {!loading && !error && data.length > 0 && (
              <>
                <div className="flex items-center gap-4 mb-3 text-xs text-gray-400">
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-6 h-0.5 bg-blue-500" /> Mediana UF/m²
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="inline-block w-6 h-3 rounded" style={{ background: 'rgba(59,130,246,0.2)' }} />
                    Rango IQR (P25–P75)
                  </span>
                </div>
                <LineChart data={data} />
              </>
            )}
          </div>

          {/* Summary table */}
          {!loading && data.length > 0 && (
            <div className="bg-gray-900 rounded-lg overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-800 text-gray-400 text-xs">
                    <th className="px-4 py-2 text-left">Período</th>
                    <th className="px-4 py-2 text-right">Mediana UF/m²</th>
                    <th className="px-4 py-2 text-right">Media UF/m²</th>
                    <th className="px-4 py-2 text-right">P25</th>
                    <th className="px-4 py-2 text-right">P75</th>
                    <th className="px-4 py-2 text-right">N transacciones</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((row, i) => (
                    <tr
                      key={i}
                      className={i % 2 === 0 ? 'bg-gray-900' : 'bg-gray-850'}
                    >
                      <td className="px-4 py-2 font-medium text-white">{row.period}</td>
                      <td className="px-4 py-2 text-right text-blue-400">{row.median_uf_m2.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right text-gray-300">{row.mean_uf_m2.toFixed(2)}</td>
                      <td className="px-4 py-2 text-right text-gray-400">
                        {row.p25_uf_m2 != null ? row.p25_uf_m2.toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-400">
                        {row.p75_uf_m2 != null ? row.p75_uf_m2.toFixed(2) : '—'}
                      </td>
                      <td className="px-4 py-2 text-right text-gray-300">
                        {row.n_transactions.toLocaleString()}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </div>
  )
}
