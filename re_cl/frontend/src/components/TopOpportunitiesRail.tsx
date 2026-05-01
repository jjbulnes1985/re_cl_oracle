/**
 * TopOpportunitiesRail.tsx — panel lateral con top 10 candidatos.
 *
 * Sticky scroll, hover sync con mapa, click → centra mapa + abre drawer.
 */

import { Heart } from 'lucide-react'
import { clsx } from 'clsx'
import type { Candidate } from './HomeShell'
import { fmtUFFull, gapText, scoreColor, scoreLabel, scoreStars, PROPERTY_TYPE_LABELS } from '../lib/format'

interface Props {
  items: Candidate[]
  isLoading: boolean
  selectedId: number | null
  hoveredId:  number | null
  onHover:    (id: number | null) => void
  onSelect:   (c: Candidate) => void
}

const WATCHLIST_KEY = 're_cl_watchlist_v2'

function loadWatchlist(): number[] {
  try { return JSON.parse(localStorage.getItem(WATCHLIST_KEY) || '[]') }
  catch { return [] }
}

function toggleWatchlist(id: number): number[] {
  const list = loadWatchlist()
  const next = list.includes(id) ? list.filter(x => x !== id) : [...list, id]
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next))
  window.dispatchEvent(new Event('watchlist-changed'))
  return next
}

export function TopOpportunitiesRail({ items, isLoading, selectedId, hoveredId, onHover, onSelect }: Props) {
  const watchlist = loadWatchlist()

  return (
    <aside className="w-80 border-l border-gray-800 bg-gray-950 flex flex-col">
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="text-sm font-semibold text-white mb-0.5">Top oportunidades</div>
        <div className="text-xs text-gray-500">
          {isLoading ? 'Buscando…' : `${items.length.toLocaleString('es-CL')} encontradas`}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="p-4 space-y-4">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="animate-pulse space-y-2">
                <div className="h-3 bg-gray-800 rounded w-1/2" />
                <div className="h-6 bg-gray-800 rounded w-3/4" />
                <div className="h-3 bg-gray-800 rounded w-2/3" />
              </div>
            ))}
          </div>
        ) : items.length === 0 ? (
          <div className="p-6 text-center text-gray-500 text-sm">
            <div className="mb-2">Sin oportunidades con estos criterios.</div>
            <div className="text-xs text-gray-600">Ajusta el presupuesto o las comunas.</div>
          </div>
        ) : (
          items.slice(0, 50).map((c, idx) => {
            const propType = PROPERTY_TYPE_LABELS[c.property_type_code]
            const gap = gapText(c.drivers ?? undefined)
            const isSaved = watchlist.includes(c.id)
            return (
              <div
                key={c.id}
                onClick={() => onSelect(c)}
                onMouseEnter={() => onHover(c.id)}
                onMouseLeave={() => onHover(null)}
                className={clsx(
                  'px-4 py-3 border-b border-gray-800 hover:bg-gray-900 cursor-pointer transition-colors',
                  selectedId === c.id && 'bg-gray-900 border-l-2 border-l-blue-500',
                  hoveredId === c.id && selectedId !== c.id && 'bg-gray-900/50'
                )}
              >
                <div className="flex items-start justify-between mb-1">
                  <div className="flex-1 min-w-0">
                    <div className="text-xs text-gray-500">#{idx + 1}</div>
                    <div className="text-white text-sm font-semibold truncate">
                      {propType?.icon} {c.county_name}
                    </div>
                  </div>
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleWatchlist(c.id)
                    }}
                    className={clsx(
                      'p-1 rounded transition-colors',
                      isSaved ? 'text-pink-500 hover:text-pink-400' : 'text-gray-600 hover:text-pink-500'
                    )}
                    aria-label={isSaved ? 'Quitar de favoritos' : 'Guardar en favoritos'}
                  >
                    <Heart size={14} fill={isSaved ? 'currentColor' : 'none'} />
                  </button>
                </div>

                <div className="text-lg font-bold text-white mb-1">{fmtUFFull(c.estimated_uf)}</div>

                <div className="flex items-center gap-2 text-xs">
                  <span style={{ color: scoreColor(c.opportunity_score) }} className="font-medium">
                    {scoreStars(c.opportunity_score)}
                  </span>
                  <span style={{ color: scoreColor(c.opportunity_score) }} className="text-[11px]">
                    {scoreLabel(c.opportunity_score).split(' ')[0]}
                  </span>
                </div>

                <div className="text-xs text-gray-400 mt-1.5" style={{ color: gap.color === '#888' ? undefined : gap.color }}>
                  {gap.text !== 'Sin comparación' && gap.text}
                </div>

                {c.is_eriazo && (
                  <div className="mt-1 inline-block text-[10px] px-1.5 py-0.5 bg-amber-950/50 text-amber-400 rounded">
                    SUBUTILIZADO
                  </div>
                )}
              </div>
            )
          })
        )}
      </div>
    </aside>
  )
}
