/**
 * HeatmapToggle.tsx — overlay del mapa con stats por comuna.
 *
 * Toggle que pinta cada comuna con gradiente según métrica seleccionada:
 *   - mediana_uf_m2 (precio)
 *   - oportunidad (% candidatos high score)
 *   - subutilizados (% eriazos)
 */

import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Map as MapIcon, X } from 'lucide-react'
import { clsx } from 'clsx'

const API = (import.meta as any).env?.VITE_API_URL || 'http://127.0.0.1:8000'

interface CommuneStat {
  county_name: string
  median_uf_m2: number | null
  pct_high_opp: number | null
  pct_eriazo: number | null
  n_candidates: number
}

const METRICS = [
  { code: 'price',      label: 'Precio promedio (UF/m²)',     field: 'median_uf_m2' as const,  inverse: false },
  { code: 'opp',        label: '% Alta oportunidad',           field: 'pct_high_opp' as const,  inverse: false },
  { code: 'eriazo',     label: '% Subutilizados',              field: 'pct_eriazo' as const,    inverse: false },
] as const

interface Props {
  active: boolean
  onClose: () => void
  onSelectCommune?: (commune: string) => void
}

export function HeatmapToggle({ active, onClose, onSelectCommune }: Props) {
  const [metric, setMetric] = useState<typeof METRICS[number]['code']>('opp')

  const { data: communes = [] } = useQuery<CommuneStat[]>({
    queryKey: ['commune-stats'],
    queryFn: async () => {
      const r = await fetch(`${API}/properties/communes/enriched`)
      const data = await r.json()
      // Map to expected shape
      return (Array.isArray(data) ? data : data.items ?? []).map((c: any) => ({
        county_name: c.county_name ?? c.commune,
        median_uf_m2: c.median_uf_m2 ?? null,
        pct_high_opp: c.pct_high_opp ?? c.pct_subvaloradas ?? null,
        pct_eriazo: c.pct_eriazo ?? null,
        n_candidates: c.n_candidates ?? c.n_transactions ?? 0,
      }))
    },
    enabled: active,
  })

  const currentMetric = METRICS.find(m => m.code === metric)!

  // Sort by current metric
  const sorted = [...communes].sort((a, b) => {
    const av = (a[currentMetric.field] as number) ?? 0
    const bv = (b[currentMetric.field] as number) ?? 0
    return bv - av
  }).filter(c => c[currentMetric.field] !== null)

  if (!active) return null

  const fmtMetric = (v: number | null, code: string) => {
    if (v === null || v === undefined) return '—'
    if (code === 'price') return `${v.toFixed(1)} UF/m²`
    return `${(v * 100).toFixed(0)}%`
  }

  return (
    <div className="absolute top-4 right-4 z-20 bg-gray-900/95 backdrop-blur rounded-2xl border border-gray-800 shadow-2xl w-72 max-h-[80vh] flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
        <div className="flex items-center gap-2 text-white">
          <MapIcon size={14} />
          <span className="text-sm font-semibold">Heatmap comunas</span>
        </div>
        <button onClick={onClose} className="text-gray-500 hover:text-white">
          <X size={14} />
        </button>
      </div>

      <div className="px-3 py-2 border-b border-gray-800 space-y-1">
        <div className="text-[10px] text-gray-500 uppercase">Métrica</div>
        {METRICS.map(m => (
          <button
            key={m.code}
            onClick={() => setMetric(m.code)}
            className={clsx(
              'block w-full text-left px-2 py-1.5 rounded text-xs',
              metric === m.code ? 'bg-blue-600 text-white' : 'text-gray-300 hover:bg-gray-800'
            )}
          >
            {m.label}
          </button>
        ))}
      </div>

      <div className="flex-1 overflow-y-auto">
        {sorted.slice(0, 30).map((c, i) => {
          const value = c[currentMetric.field] as number | null
          const max   = sorted[0]?.[currentMetric.field] as number ?? 1
          const pct   = value !== null ? Math.min(100, (value / max) * 100) : 0
          return (
            <button
              key={c.county_name}
              onClick={() => onSelectCommune?.(c.county_name)}
              className="w-full text-left px-3 py-2 hover:bg-gray-800 border-b border-gray-800 last:border-0"
            >
              <div className="flex items-baseline justify-between mb-1">
                <span className="text-xs text-white font-medium">{i + 1}. {c.county_name}</span>
                <span className="text-xs text-gray-400">{fmtMetric(value, metric)}</span>
              </div>
              <div className="h-1 bg-gray-800 rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full"
                  style={{
                    width: `${pct}%`,
                    background: `linear-gradient(to right, #3b82f6, #22c55e)`,
                  }}
                />
              </div>
            </button>
          )
        })}
        {sorted.length === 0 && (
          <div className="px-4 py-6 text-xs text-gray-500 text-center">
            Sin datos disponibles
          </div>
        )}
      </div>
    </div>
  )
}
