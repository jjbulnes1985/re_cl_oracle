import { X } from 'lucide-react'
import type { Property } from '../types'
import { clsx } from 'clsx'

// ── Mini SVG Radar ─────────────────────────────────────────────────────────────

interface RadarDimension {
  label: string
  value: number // 0–1
}

function MiniRadar({ dimensions, color }: { dimensions: RadarDimension[]; color: string }) {
  const cx = 60
  const cy = 60
  const r  = 42
  const n  = dimensions.length

  const point = (index: number, fraction: number) => {
    const angle = (Math.PI * 2 * index) / n - Math.PI / 2
    return {
      x: cx + r * fraction * Math.cos(angle),
      y: cy + r * fraction * Math.sin(angle),
    }
  }

  const rings = [0.25, 0.5, 0.75, 1.0]

  const ringPath = (frac: number) =>
    dimensions
      .map((_, i) => {
        const p = point(i, frac)
        return `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`
      })
      .join(' ') + ' Z'

  const dataPoints = dimensions.map((d, i) => point(i, Math.max(0, Math.min(1, d.value))))
  const polyPath =
    dataPoints.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x.toFixed(1)} ${p.y.toFixed(1)}`).join(' ') + ' Z'

  const axes = dimensions.map((_, i) => point(i, 1))

  const labelOffset = 1.30
  const labels = dimensions.map((d, i) => {
    const p = point(i, labelOffset)
    return { ...p, label: d.label }
  })

  const fillColor = `${color}30`

  return (
    <svg viewBox="0 0 120 120" className="w-full" style={{ maxHeight: 120 }}>
      {rings.map((frac) => (
        <path key={frac} d={ringPath(frac)} fill="none" stroke="#374151" strokeWidth={frac === 1 ? 1 : 0.6} />
      ))}
      {axes.map((end, i) => (
        <line key={i} x1={cx} y1={cy} x2={end.x.toFixed(1)} y2={end.y.toFixed(1)} stroke="#374151" strokeWidth={0.6} />
      ))}
      <path d={polyPath} fill={fillColor} stroke={color} strokeWidth={1.2} />
      {dataPoints.map((p, i) => (
        <circle key={i} cx={p.x.toFixed(1)} cy={p.y.toFixed(1)} r={2} fill={color} />
      ))}
      {labels.map((l, i) => {
        const anchor = l.x < cx - 6 ? 'end' : l.x > cx + 6 ? 'start' : 'middle'
        return (
          <text key={i} x={l.x.toFixed(1)} y={l.y.toFixed(1)} fontSize={6} fill="#9ca3af" textAnchor={anchor} dominantBaseline="middle">
            {l.label}
          </text>
        )
      })}
    </svg>
  )
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function buildRadarDimensions(p: Property): RadarDimension[] {
  const score    = Math.max(0, Math.min(1, p.opportunity_score ?? 0))
  const conf     = Math.max(0, Math.min(1, p.data_confidence ?? 0))
  // Metro access: invert distance so closer = higher (cap at 5 km → 0)
  const metro    = p.dist_metro_km != null ? Math.max(0, 1 - p.dist_metro_km / 5) : 0.5
  // Amenities: cap at 20
  const amenities = Math.min(1, (p.amenities_500m ?? 0) / 20)
  // Precio relativo: negative gap = undervalued = good; map gap_pct [-1, 0] → [1, 0.5]
  const gap      = p.gap_pct ?? 0
  const precioRel = Math.max(0, Math.min(1, 0.5 + (-gap) * 0.5))

  return [
    { label: 'Score',    value: score },
    { label: 'Confianza', value: conf },
    { label: 'Metro',    value: metro },
    { label: 'Amenid.',  value: amenities },
    { label: 'Precio',   value: precioRel },
  ]
}

type BetterFn = (a: number | null, b: number | null) => 'a' | 'b' | 'tie'

// Higher is better
const higherBetter: BetterFn = (a, b) => {
  if (a == null && b == null) return 'tie'
  if (a == null) return 'b'
  if (b == null) return 'a'
  if (a > b + 1e-9) return 'a'
  if (b > a + 1e-9) return 'b'
  return 'tie'
}

// Lower is better
const lowerBetter: BetterFn = (a, b) => {
  if (a == null && b == null) return 'tie'
  if (a == null) return 'b'
  if (b == null) return 'a'
  if (a < b - 1e-9) return 'a'
  if (b < a - 1e-9) return 'b'
  return 'tie'
}

// More negative is better (gap_pct)
const morNegBetter: BetterFn = (a, b) => {
  if (a == null && b == null) return 'tie'
  if (a == null) return 'b'
  if (b == null) return 'a'
  if (a < b - 1e-9) return 'a'
  if (b < a - 1e-9) return 'b'
  return 'tie'
}

function betterCls(winner: 'a' | 'b' | 'tie', side: 'a' | 'b') {
  if (winner === 'tie') return ''
  return winner === side ? 'text-green-400 font-semibold' : 'text-gray-400'
}

// ── Slot ──────────────────────────────────────────────────────────────────────

function EmptySlot({ label }: { label: string }) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center border-2 border-dashed border-gray-700 rounded-lg h-32 text-gray-600 text-sm gap-1">
      <span className="text-lg font-bold text-gray-700">{label}</span>
      <span>Seleccione una propiedad</span>
      <span className="text-xs text-gray-700">desde el Ranking o el Mapa</span>
    </div>
  )
}

// ── Props ─────────────────────────────────────────────────────────────────────

export interface ComparatorPanelProps {
  propA: Property | null
  propB: Property | null
  onClearA: () => void
  onClearB: () => void
}

// ── Main component ────────────────────────────────────────────────────────────

export function ComparatorPanel({ propA, propB, onClearA, onClearB }: ComparatorPanelProps) {
  const bothLoaded = propA !== null && propB !== null

  // Comparison rows definition
  type Row = {
    label: string
    aVal: string
    bVal: string
    aRaw: number | null
    bRaw: number | null
    better: BetterFn
  }

  const rows: Row[] = bothLoaded
    ? [
        {
          label: 'Score',
          aVal:  (propA.opportunity_score ?? 0).toFixed(3),
          bVal:  (propB.opportunity_score ?? 0).toFixed(3),
          aRaw:  propA.opportunity_score,
          bRaw:  propB.opportunity_score,
          better: higherBetter,
        },
        {
          label: 'Tipo',
          aVal:  propA.project_type ?? '–',
          bVal:  propB.project_type ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'Comuna',
          aVal:  propA.county_name ?? '–',
          bVal:  propB.county_name ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'Año',
          aVal:  propA.year?.toString() ?? '–',
          bVal:  propB.year?.toString() ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'UF/m²',
          aVal:  propA.uf_m2_building?.toFixed(1) ?? '–',
          bVal:  propB.uf_m2_building?.toFixed(1) ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'Superficie m²',
          aVal:  propA.surface_m2?.toFixed(0) ?? '–',
          bVal:  propB.surface_m2?.toFixed(0) ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'Gap %',
          aVal:  propA.gap_pct != null ? `${(propA.gap_pct * 100).toFixed(1)}%` : '–',
          bVal:  propB.gap_pct != null ? `${(propB.gap_pct * 100).toFixed(1)}%` : '–',
          aRaw:  propA.gap_pct,
          bRaw:  propB.gap_pct,
          better: morNegBetter, // more negative = more undervalued = better
        },
        {
          label: 'Confianza',
          aVal:  propA.data_confidence?.toFixed(2) ?? '–',
          bVal:  propB.data_confidence?.toFixed(2) ?? '–',
          aRaw:  propA.data_confidence,
          bRaw:  propB.data_confidence,
          better: higherBetter,
        },
        {
          label: 'Zona',
          aVal:  propA.city_zone ?? '–',
          bVal:  propB.city_zone ?? '–',
          aRaw:  null,
          bRaw:  null,
          better: () => 'tie',
        },
        {
          label: 'Antigüedad',
          aVal:  propA.age != null ? `${propA.age} años` : '–',
          bVal:  propB.age != null ? `${propB.age} años` : '–',
          aRaw:  propA.age ?? null,
          bRaw:  propB.age ?? null,
          better: lowerBetter, // newer = better
        },
        {
          label: 'Dist. Metro',
          aVal:  propA.dist_metro_km != null ? `${propA.dist_metro_km.toFixed(2)} km` : '–',
          bVal:  propB.dist_metro_km != null ? `${propB.dist_metro_km.toFixed(2)} km` : '–',
          aRaw:  propA.dist_metro_km ?? null,
          bRaw:  propB.dist_metro_km ?? null,
          better: lowerBetter,
        },
        {
          label: 'Amenidades 500m',
          aVal:  propA.amenities_500m?.toString() ?? '–',
          bVal:  propB.amenities_500m?.toString() ?? '–',
          aRaw:  propA.amenities_500m ?? null,
          bRaw:  propB.amenities_500m ?? null,
          better: higherBetter,
        },
      ]
    : []

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-y-auto">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800 shrink-0">
        <h2 className="text-sm font-semibold text-white">Comparador de propiedades</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Selecciona dos propiedades desde el Ranking para compararlas
        </p>
      </div>

      <div className="p-4 flex flex-col gap-4">
        {/* Slots */}
        <div className="flex gap-3">
          {/* Slot A */}
          {propA ? (
            <div className="flex-1 bg-gray-800 rounded-lg p-3 border border-blue-600/40">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-blue-400 bg-blue-600/20 px-2 py-0.5 rounded-full">A</span>
                <button onClick={onClearA} className="text-gray-500 hover:text-white">
                  <X size={14} />
                </button>
              </div>
              <p className="text-sm font-semibold text-white truncate">
                {propA.county_name} · {propA.project_type}
              </p>
              <p className="text-xs text-gray-500">Score: {propA.opportunity_score?.toFixed(3) ?? '–'}</p>
            </div>
          ) : (
            <EmptySlot label="A" />
          )}

          {/* VS divider */}
          <div className="flex items-center justify-center px-1">
            <span className="text-xs font-bold text-gray-600">VS</span>
          </div>

          {/* Slot B */}
          {propB ? (
            <div className="flex-1 bg-gray-800 rounded-lg p-3 border border-purple-600/40">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-bold text-purple-400 bg-purple-600/20 px-2 py-0.5 rounded-full">B</span>
                <button onClick={onClearB} className="text-gray-500 hover:text-white">
                  <X size={14} />
                </button>
              </div>
              <p className="text-sm font-semibold text-white truncate">
                {propB.county_name} · {propB.project_type}
              </p>
              <p className="text-xs text-gray-500">Score: {propB.opportunity_score?.toFixed(3) ?? '–'}</p>
            </div>
          ) : (
            <EmptySlot label="B" />
          )}
        </div>

        {/* Radar charts side by side */}
        {bothLoaded && (
          <div className="grid grid-cols-2 gap-3">
            <div className="bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-blue-400 font-semibold mb-1 text-center">Prop A</p>
              <MiniRadar dimensions={buildRadarDimensions(propA!)} color="#3b82f6" />
            </div>
            <div className="bg-gray-800 rounded-lg p-3">
              <p className="text-xs text-purple-400 font-semibold mb-1 text-center">Prop B</p>
              <MiniRadar dimensions={buildRadarDimensions(propB!)} color="#a855f7" />
            </div>
          </div>
        )}

        {/* Comparison table */}
        {bothLoaded && (
          <div className="bg-gray-800 rounded-lg overflow-hidden">
            {/* Table header */}
            <div className="grid grid-cols-3 text-xs font-semibold text-gray-400 border-b border-gray-700 px-3 py-2">
              <span>Atributo</span>
              <span className="text-center text-blue-400">Prop A</span>
              <span className="text-center text-purple-400">Prop B</span>
            </div>

            {rows.map((row, i) => {
              const winner = row.better(row.aRaw, row.bRaw)
              return (
                <div
                  key={row.label}
                  className={clsx(
                    'grid grid-cols-3 text-xs px-3 py-2 border-b border-gray-700/50',
                    i % 2 === 0 ? 'bg-gray-800' : 'bg-gray-800/60'
                  )}
                >
                  <span className="text-gray-500">{row.label}</span>
                  <span className={clsx('text-center', betterCls(winner, 'a'))}>
                    {row.aVal}
                    {winner === 'a' && (
                      <span className="ml-1 text-green-500">▲</span>
                    )}
                  </span>
                  <span className={clsx('text-center', betterCls(winner, 'b'))}>
                    {row.bVal}
                    {winner === 'b' && (
                      <span className="ml-1 text-green-500">▲</span>
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}

        {/* Empty state hint */}
        {!bothLoaded && !propA && !propB && (
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
            <div className="w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center text-gray-600 text-2xl">
              ⊕
            </div>
            <p className="text-gray-500 text-sm">
              Ve al tab <span className="text-white font-medium">Ranking</span> y pulsa{' '}
              <span className="text-white font-medium">⊕</span> en dos propiedades
            </p>
          </div>
        )}
      </div>
    </div>
  )
}
