/**
 * WatchlistDrawer.tsx — drawer lateral con favoritos guardados.
 *
 * Carga IDs de localStorage y resuelve via /opportunity/candidates/{id}.
 */

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { X, Heart, MapPin } from 'lucide-react'
import type { Candidate } from './HomeShell'
import { fmtUFFull, scoreColor, scoreStars, PROPERTY_TYPE_LABELS } from '../lib/format'

const API = (import.meta as any).env?.VITE_API_URL || 'http://127.0.0.1:8000'
const WATCHLIST_KEY = 're_cl_watchlist_v2'

interface Props {
  onClose: () => void
  onSelectCandidate: (c: Candidate) => void
}

function loadWatchlist(): number[] {
  try { return JSON.parse(localStorage.getItem(WATCHLIST_KEY) || '[]') }
  catch { return [] }
}

export function WatchlistDrawer({ onClose, onSelectCandidate }: Props) {
  const [ids, setIds] = useState<number[]>(loadWatchlist())

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const onChange = () => setIds(loadWatchlist())
    window.addEventListener('watchlist-changed', onChange)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.removeEventListener('watchlist-changed', onChange)
    }
  }, [onClose])

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['watchlist', ids],
    queryFn: async () => {
      const results = await Promise.all(
        ids.map(async id => {
          try {
            const r = await fetch(`${API}/opportunity/candidates/${id}`)
            if (!r.ok) return null
            return await r.json()
          } catch { return null }
        })
      )
      return results.filter(Boolean) as Candidate[]
    },
    enabled: ids.length > 0,
  })

  const remove = (id: number) => {
    const next = ids.filter(x => x !== id)
    localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next))
    setIds(next)
    window.dispatchEvent(new Event('watchlist-changed'))
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 w-96 bg-gray-950 border-l border-gray-800 shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <div className="flex items-center gap-2">
            <Heart size={16} className="text-pink-500" />
            <span className="text-sm font-semibold text-white">Mis favoritos</span>
            <span className="text-xs text-gray-500">({ids.length})</span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white p-1">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {ids.length === 0 ? (
            <div className="p-8 text-center text-sm text-gray-500">
              <Heart size={32} className="mx-auto mb-3 opacity-30" />
              <div className="mb-2">Aún no tienes favoritos.</div>
              <div className="text-xs text-gray-600">Click en ♥ en cualquier oportunidad para guardarla.</div>
            </div>
          ) : isLoading ? (
            <div className="p-4 space-y-3">
              {[...Array(3)].map((_, i) => (
                <div key={i} className="animate-pulse space-y-2">
                  <div className="h-3 bg-gray-800 rounded w-1/2" />
                  <div className="h-5 bg-gray-800 rounded w-3/4" />
                </div>
              ))}
            </div>
          ) : (
            items.map(c => {
              const propType = PROPERTY_TYPE_LABELS[c.property_type_code]
              return (
                <div key={c.id} className="px-4 py-3 border-b border-gray-800 hover:bg-gray-900 cursor-pointer relative" onClick={() => onSelectCandidate(c)}>
                  <button
                    onClick={(e) => { e.stopPropagation(); remove(c.id) }}
                    className="absolute top-3 right-3 text-pink-500 hover:text-pink-400"
                    title="Quitar"
                  >
                    <Heart size={14} fill="currentColor" />
                  </button>
                  <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">
                    {propType?.icon} {propType?.label}
                  </div>
                  <div className="text-white text-sm font-semibold mb-1">{c.county_name}</div>
                  <div className="text-lg font-bold text-white mb-1">{fmtUFFull(c.estimated_uf)}</div>
                  <div className="text-xs" style={{ color: scoreColor(c.opportunity_score) }}>
                    {scoreStars(c.opportunity_score)} · {Math.round(c.opportunity_score * 100)}/100
                  </div>
                </div>
              )
            })
          )}
        </div>
      </aside>
    </>
  )
}
