/**
 * ComparatorOverlay.tsx — modal side-by-side de 2 propiedades.
 *
 * Disparado desde PropertyDrawer "⇄ Comparar" cuando ya hay 1 propiedad seleccionada.
 * Resaltado verde/rojo automático según métrica.
 */

import { useEffect } from 'react'
import { X, ArrowLeftRight, MapPin } from 'lucide-react'
import type { Candidate } from './HomeShell'
import {
  fmtUFFull, fmtUF, scoreColor, scoreLabel, scoreStars, gapText, PROPERTY_TYPE_LABELS,
} from '../lib/format'

interface Props {
  a: Candidate
  b: Candidate
  onClose: () => void
}

function compareCell(a: number | null | undefined, b: number | null | undefined, higherIsBetter = true): { winner: 'a' | 'b' | 'tie' } {
  if (a === null || a === undefined || b === null || b === undefined) return { winner: 'tie' }
  const aN = Number(a), bN = Number(b)
  if (isNaN(aN) || isNaN(bN)) return { winner: 'tie' }
  if (Math.abs(aN - bN) / Math.max(aN, bN, 1) < 0.02) return { winner: 'tie' }
  if (higherIsBetter) return { winner: aN > bN ? 'a' : 'b' }
  return { winner: aN < bN ? 'a' : 'b' }
}

export function ComparatorOverlay({ a, b, onClose }: Props) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const aType = PROPERTY_TYPE_LABELS[a.property_type_code]
  const bType = PROPERTY_TYPE_LABELS[b.property_type_code]
  const aGap = gapText(a.drivers ?? undefined)
  const bGap = gapText(b.drivers ?? undefined)

  // Comparisons (higher is better unless noted)
  const cmpScore   = compareCell(a.opportunity_score, b.opportunity_score, true)
  const cmpPrice   = compareCell(a.estimated_uf, b.estimated_uf, false)  // lower is better
  const cmpSurface = compareCell(a.surface_land_m2, b.surface_land_m2, true)
  const cmpConf    = compareCell(a.valuation_confidence, b.valuation_confidence, true)

  const winnerColor = (winner: 'a' | 'b' | 'tie', side: 'a' | 'b') => {
    if (winner === 'tie') return 'text-gray-400'
    return winner === side ? 'text-green-400 font-semibold' : 'text-gray-500'
  }

  const Cell = ({ winner, side, children }: { winner: 'a' | 'b' | 'tie'; side: 'a' | 'b'; children: React.ReactNode }) => (
    <div className={winnerColor(winner, side)}>{children}</div>
  )

  return (
    <>
      <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-4 md:inset-12 z-50 bg-gray-950 rounded-2xl shadow-2xl border border-gray-800 flex flex-col overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
          <div className="flex items-center gap-2 text-white">
            <ArrowLeftRight size={18} />
            <span className="font-semibold">Comparar propiedades</span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white p-2">
            <X size={18} />
          </button>
        </div>

        {/* Two columns */}
        <div className="flex-1 overflow-y-auto p-6">
          <div className="grid grid-cols-2 gap-6 max-w-5xl mx-auto">
            {/* Property A */}
            <div className="bg-gray-900 rounded-xl p-5 border border-gray-800">
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">A · {aType?.label}</div>
              <h3 className="text-xl font-bold text-white mb-1">{a.county_name}</h3>
              <div className="text-sm text-gray-500 mb-3">
                {Math.round(a.surface_land_m2 || 0).toLocaleString('es-CL')} m²
              </div>
              <div className="text-2xl font-bold text-white mb-2">{fmtUFFull(a.estimated_uf)}</div>
              <div className="text-lg" style={{ color: scoreColor(a.opportunity_score) }}>
                {scoreStars(a.opportunity_score)}
              </div>
            </div>

            {/* Property B */}
            <div className="bg-gray-900 rounded-xl p-5 border border-gray-800">
              <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">B · {bType?.label}</div>
              <h3 className="text-xl font-bold text-white mb-1">{b.county_name}</h3>
              <div className="text-sm text-gray-500 mb-3">
                {Math.round(b.surface_land_m2 || 0).toLocaleString('es-CL')} m²
              </div>
              <div className="text-2xl font-bold text-white mb-2">{fmtUFFull(b.estimated_uf)}</div>
              <div className="text-lg" style={{ color: scoreColor(b.opportunity_score) }}>
                {scoreStars(b.opportunity_score)}
              </div>
            </div>
          </div>

          {/* Comparison table */}
          <div className="max-w-5xl mx-auto mt-6 bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
            <table className="w-full text-sm">
              <tbody>
                <Row label="Score oportunidad">
                  <Cell winner={cmpScore.winner} side="a">{Math.round(a.opportunity_score * 100)}/100 — {scoreLabel(a.opportunity_score)}</Cell>
                  <Cell winner={cmpScore.winner} side="b">{Math.round(b.opportunity_score * 100)}/100 — {scoreLabel(b.opportunity_score)}</Cell>
                </Row>
                <Row label="Precio estimado">
                  <Cell winner={cmpPrice.winner} side="a">{fmtUFFull(a.estimated_uf)}</Cell>
                  <Cell winner={cmpPrice.winner} side="b">{fmtUFFull(b.estimated_uf)}</Cell>
                </Row>
                <Row label="Rango justo p25-p75">
                  <span className="text-gray-300">{fmtUF(a.p25_uf)} – {fmtUF(a.p75_uf)}</span>
                  <span className="text-gray-300">{fmtUF(b.p25_uf)} – {fmtUF(b.p75_uf)}</span>
                </Row>
                <Row label="Vs precio mercado">
                  <span style={{ color: aGap.color }}>{aGap.text}</span>
                  <span style={{ color: bGap.color }}>{bGap.text}</span>
                </Row>
                <Row label="Tipo">
                  <span className="text-gray-300">{aType?.label}</span>
                  <span className="text-gray-300">{bType?.label}</span>
                </Row>
                <Row label="Superficie terreno">
                  <Cell winner={cmpSurface.winner} side="a">{Math.round(a.surface_land_m2 || 0).toLocaleString('es-CL')} m²</Cell>
                  <Cell winner={cmpSurface.winner} side="b">{Math.round(b.surface_land_m2 || 0).toLocaleString('es-CL')} m²</Cell>
                </Row>
                <Row label="Confianza valoración">
                  <Cell winner={cmpConf.winner} side="a">{a.valuation_confidence ? `${Math.round(a.valuation_confidence * 100)}%` : '—'}</Cell>
                  <Cell winner={cmpConf.winner} side="b">{b.valuation_confidence ? `${Math.round(b.valuation_confidence * 100)}%` : '—'}</Cell>
                </Row>
                <Row label="Subutilizado">
                  <span className={a.is_eriazo ? 'text-amber-400' : 'text-gray-500'}>{a.is_eriazo ? 'Sí' : 'No'}</span>
                  <span className={b.is_eriazo ? 'text-amber-400' : 'text-gray-500'}>{b.is_eriazo ? 'Sí' : 'No'}</span>
                </Row>
                <Row label="Última transacción">
                  <span className="text-gray-300">{a.last_transaction_uf ? fmtUFFull(a.last_transaction_uf) : '—'}</span>
                  <span className="text-gray-300">{b.last_transaction_uf ? fmtUFFull(b.last_transaction_uf) : '—'}</span>
                </Row>
              </tbody>
            </table>
          </div>

          <div className="max-w-5xl mx-auto mt-6 grid grid-cols-2 gap-3">
            <a
              href={`https://maps.google.com/?q=${a.latitude},${a.longitude}`}
              target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-full"
            >
              <MapPin size={12} /> A en Google Maps
            </a>
            <a
              href={`https://maps.google.com/?q=${b.latitude},${b.longitude}`}
              target="_blank" rel="noopener noreferrer"
              className="flex items-center justify-center gap-2 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 text-sm rounded-full"
            >
              <MapPin size={12} /> B en Google Maps
            </a>
          </div>
        </div>
      </div>
    </>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <tr className="border-b border-gray-800 last:border-0">
      <td className="px-5 py-3 text-xs text-gray-500 font-medium w-44">{label}</td>
      {Array.isArray(children) ? children.map((c, i) => (
        <td key={i} className="px-5 py-3 text-sm">{c}</td>
      )) : (
        <td className="px-5 py-3 text-sm" colSpan={2}>{children}</td>
      )}
    </tr>
  )
}
