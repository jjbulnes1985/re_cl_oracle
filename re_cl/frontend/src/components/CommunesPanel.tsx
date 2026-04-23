import { useQuery } from '@tanstack/react-query'
import { fetchCommunes, fetchCommunesEnriched } from '../api'
import type { CommuneEnriched } from '../types'

const bar = (pct: number, max: number) => `${Math.round((pct / max) * 100)}%`

function scoreBarColor(score: number, max: number): string {
  const ratio = max > 0 ? score / max : 0
  if (ratio >= 0.8) return 'bg-red-500'
  if (ratio >= 0.6) return 'bg-orange-500'
  if (ratio >= 0.4) return 'bg-yellow-500'
  return 'bg-blue-500'
}

function scoreTextColor(score: number, max: number): string {
  const ratio = max > 0 ? score / max : 0
  if (ratio >= 0.8) return 'text-red-400'
  if (ratio >= 0.6) return 'text-orange-400'
  if (ratio >= 0.4) return 'text-yellow-400'
  return 'text-blue-400'
}

function crimeTierStyle(tier?: string): string {
  if (!tier) return 'text-gray-500'
  const t = tier.toLowerCase()
  if (t === 'alto')  return 'text-red-400 font-semibold'
  if (t === 'medio') return 'text-yellow-400 font-semibold'
  if (t === 'bajo')  return 'text-green-400 font-semibold'
  return 'text-gray-400'
}

export function CommunesPanel() {
  const { data: communes = [], isLoading } = useQuery({
    queryKey: ['communes'],
    queryFn:  fetchCommunes,
  })

  const { data: enriched = [] } = useQuery({
    queryKey: ['communes-enriched'],
    queryFn:  fetchCommunesEnriched,
  })

  // Build a lookup map from enriched data keyed by county_name
  const enrichedMap = new Map<string, CommuneEnriched>(
    enriched.map((e) => [e.county_name, e])
  )

  const maxScore = Math.max(...communes.map((c) => c.median_score ?? 0), 0.01)
  const maxPct   = Math.max(...communes.map((c) => c.pct_subvaloradas ?? 0), 0.01)
  const maxN     = Math.max(...communes.map((c) => c.n_transactions ?? 0), 1)

  // Summary stats
  const totalProps = communes.reduce((s, c) => s + c.n_transactions, 0)
  const avgScore   = communes.length > 0
    ? communes.reduce((s, c) => s + (c.median_score ?? 0), 0) / communes.length
    : 0
  const avgSubval  = communes.length > 0
    ? communes.reduce((s, c) => s + (c.pct_subvaloradas ?? 0), 0) / communes.length
    : 0

  return (
    <div className="flex flex-col h-full bg-gray-900 overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-800">
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-sm font-semibold text-white">Ranking Comunal</h2>
          <span className="text-xs text-gray-500">{communes.length} comunas con datos</span>
        </div>

        {/* Summary stats row */}
        {communes.length > 0 && (
          <div className="flex gap-2">
            <div className="flex-1 bg-gray-800 rounded px-2.5 py-1.5 text-center">
              <p className="text-xs font-bold text-white">{totalProps.toLocaleString()}</p>
              <p className="text-[10px] text-gray-500">transacciones</p>
            </div>
            <div className="flex-1 bg-gray-800 rounded px-2.5 py-1.5 text-center">
              <p className="text-xs font-bold text-blue-400">{avgScore.toFixed(3)}</p>
              <p className="text-[10px] text-gray-500">score promedio</p>
            </div>
            <div className="flex-1 bg-gray-800 rounded px-2.5 py-1.5 text-center">
              <p className="text-xs font-bold text-orange-400">{avgSubval.toFixed(1)}%</p>
              <p className="text-[10px] text-gray-500">subval. media</p>
            </div>
          </div>
        )}
      </div>

      {isLoading && (
        <div className="flex items-center justify-center h-24 text-gray-500 text-sm">Cargando…</div>
      )}

      {/* Header row */}
      <div className="overflow-x-auto">
        <table className="min-w-full text-xs">
          <thead>
            <tr className="text-gray-500 font-semibold border-b border-gray-800">
              <th className="text-left px-4 py-2">Comuna</th>
              <th className="text-right px-2 py-2">Score</th>
              <th className="hidden md:table-cell text-right px-2 py-2">% Subval</th>
              <th className="hidden md:table-cell text-right px-2 py-2">N</th>
              <th className="hidden lg:table-cell text-right px-2 py-2">Crimen</th>
              <th className="hidden lg:table-cell text-right px-2 py-2">Educac.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-800">
            {communes.map((c, i) => {
              const score = c.median_score ?? 0
              const pct   = c.pct_subvaloradas ?? 0
              const n     = c.n_transactions
              const enr   = enrichedMap.get(c.county_name)

              const scoreBar  = scoreBarColor(score, maxScore)
              const scoreTxt  = scoreTextColor(score, maxScore)

              return (
                <tr key={c.county_name} className="hover:bg-gray-800 transition-colors">
                  {/* Rank + name */}
                  <td className="px-4 py-2.5">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-gray-600 w-4 shrink-0 font-mono">{i + 1}</span>
                      <div className="min-w-0">
                        <span className="text-gray-200 truncate block">{c.county_name}</span>
                        <div className="h-1 bg-gray-700 rounded-full mt-1 w-full">
                          <div
                            className="h-full rounded-full bg-gray-500"
                            style={{ width: `${Math.round((n / maxN) * 100)}%` }}
                          />
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* Score med + colored bar */}
                  <td className="text-right px-2 py-2.5">
                    <span className={`font-semibold ${scoreTxt}`}>{score.toFixed(3)}</span>
                    <div className="h-1.5 bg-gray-700 rounded-full mt-1">
                      <div
                        className={`h-full rounded-full ${scoreBar}`}
                        style={{ width: bar(score, maxScore) }}
                      />
                    </div>
                  </td>

                  {/* % Subvaloradas */}
                  <td className="hidden md:table-cell text-right px-2 py-2.5">
                    <span className="font-semibold text-orange-400">{pct.toFixed(1)}%</span>
                    <div className="h-1.5 bg-gray-700 rounded-full mt-1">
                      <div
                        className="h-full rounded-full bg-orange-500"
                        style={{ width: bar(pct, maxPct) }}
                      />
                    </div>
                  </td>

                  {/* N transactions */}
                  <td className="hidden md:table-cell text-right px-2 py-2.5 text-gray-400">
                    {n.toLocaleString()}
                  </td>

                  {/* Crime tier */}
                  <td className="hidden lg:table-cell text-right px-2 py-2.5">
                    {enr?.crime_tier
                      ? <span className={crimeTierStyle(enr.crime_tier)}>{enr.crime_tier}</span>
                      : <span className="text-gray-600">—</span>
                    }
                  </td>

                  {/* Educacion score */}
                  <td className="hidden lg:table-cell text-right px-2 py-2.5">
                    {enr?.educacion_score != null
                      ? <span className="text-cyan-400">{enr.educacion_score.toFixed(2)}</span>
                      : <span className="text-gray-600">—</span>
                    }
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </div>
  )
}
