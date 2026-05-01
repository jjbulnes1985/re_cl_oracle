/**
 * PropertyDrawer.tsx — bottom sheet con detalle de candidato.
 *
 * Estructura:
 *   - Header: tipo, comuna, m², precio
 *   - Calificación visual + frase narrativa
 *   - 3 tarjetas: Si arriendas / Si vendes / Tendencia comuna
 *   - Riesgos antes que upside
 *   - Acciones: Guardar, Comparar, Detalles ▼
 *   - Detalles expandible: QuickReturnSimulator + comparables + modo experto
 */

import { useState, useEffect } from 'react'
import { Heart, ArrowLeftRight, ChevronDown, ChevronUp, X, AlertTriangle, MapPin, FileText } from 'lucide-react'
import { clsx } from 'clsx'
import type { Candidate } from './HomeShell'
import {
  fmtUF, fmtUFFull, fmtCLP, fmtPct, scoreColor, scoreLabel, scoreStars, gapText, PROPERTY_TYPE_LABELS,
} from '../lib/format'
import { QuickReturnSimulator } from './QuickReturnSimulator'

interface Props {
  candidate: Candidate
  objective: { code: string; label: string; profile: string } | undefined
  onClose: () => void
}

const WATCHLIST_KEY = 're_cl_watchlist_v2'
const COMPARE_KEY   = 're_cl_compare_v2'

function isInWatchlist(id: number): boolean {
  try { return (JSON.parse(localStorage.getItem(WATCHLIST_KEY) || '[]') as number[]).includes(id) }
  catch { return false }
}
function toggleWatch(id: number) {
  const list = (JSON.parse(localStorage.getItem(WATCHLIST_KEY) || '[]') as number[])
  const next = list.includes(id) ? list.filter(x => x !== id) : [...list, id]
  localStorage.setItem(WATCHLIST_KEY, JSON.stringify(next))
  window.dispatchEvent(new Event('watchlist-changed'))
}

export function PropertyDrawer({ candidate, objective, onClose }: Props) {
  const [expanded, setExpanded] = useState(false)
  const [saved, setSaved] = useState(isInWatchlist(candidate.id))

  useEffect(() => {
    setSaved(isInWatchlist(candidate.id))
    const handler = () => setSaved(isInWatchlist(candidate.id))
    window.addEventListener('watchlist-changed', handler)
    return () => window.removeEventListener('watchlist-changed', handler)
  }, [candidate.id])

  // Esc to close
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const propType = PROPERTY_TYPE_LABELS[candidate.property_type_code]
  const surfaceM2 = candidate.surface_building_m2 || candidate.surface_land_m2 || 0
  const gap = gapText(candidate.drivers ?? undefined)
  const isLand = candidate.property_type_code === 'land'
  const isOperator = objective?.profile === 'operator'

  // Geltner-grade narrative — frontend draft (idealmente vendría del backend)
  const drivers = candidate.drivers as any
  const gapPct  = drivers?.gap_pct as number | undefined

  // Estimaciones para las 3 tarjetas
  // Income approach (default Chile residencial: yield bruto ~4-7%)
  const yieldGuess = isLand ? null : (objective?.profile === 'income' ? 0.065 : 0.055)
  const annualNoiUF = (candidate.estimated_uf ?? 0) * (yieldGuess ?? 0)
  const monthlyRentCLP = annualNoiUF * 37000 / 12  // UF→CLP fallback ~37k

  // Growth approach (default RM 5% anual histórico, ajustable por gap)
  const annualGrowth = 0.05
  const projected5y = (candidate.estimated_uf ?? 0) * Math.pow(1 + annualGrowth, 5)
  const totalReturn5y = ((projected5y - (candidate.estimated_uf ?? 0)) / (candidate.estimated_uf ?? 1)) * 100

  // Frase narrativa generada en frontend (TODO: mover al backend agente A5)
  const buildNarrative = () => {
    const parts: string[] = []
    if (gapPct !== undefined && gapPct < -3) {
      parts.push(`Esta propiedad está ${Math.abs(gapPct).toFixed(0)}% bajo el precio promedio de su comuna.`)
    }
    if (yieldGuess !== null && objective?.profile === 'income') {
      parts.push(`Si la arriendas, el rendimiento anual estimado es ${(yieldGuess * 100).toFixed(1)}%.`)
    }
    if (objective?.profile === 'growth') {
      parts.push(`Si la vendes en 5 años, la plusvalía proyectada es ~${totalReturn5y.toFixed(0)}%.`)
    }
    if (candidate.is_eriazo) parts.push('Es un terreno subutilizado con potencial de redesarrollo.')
    return parts.join(' ') || 'Esta propiedad cumple con los criterios de oportunidad de la zona.'
  }

  const ddItems = isLand ? [
    'Verificar uso permitido y altura máxima en plan regulador (DOM)',
    'Solicitar certificado de informaciones previas',
    'Revisar topografía y servicios disponibles (luz/agua/alcantarillado)',
    'Tasación independiente del terreno (Tinsa / GPS Property)',
  ] : [
    'Solicitar certificado de hipotecas y gravámenes (CBR)',
    'Verificar estado de dominio y deudas tributarias (SII)',
    'Inspección física y revisión técnica',
    'Tasación independiente para validar el precio',
  ]

  const gmaps = `https://maps.google.com/?q=${candidate.latitude},${candidate.longitude}`

  return (
    <div className="fixed inset-x-0 bottom-0 z-40 bg-gray-950 border-t border-gray-800 shadow-2xl rounded-t-3xl max-h-[85vh] overflow-y-auto">
      {/* Drag handle */}
      <div className="flex justify-center pt-2 pb-1">
        <div className="w-12 h-1.5 bg-gray-700 rounded-full" />
      </div>

      {/* Close */}
      <button onClick={onClose} className="absolute top-4 right-4 text-gray-500 hover:text-white p-2 z-10">
        <X size={18} />
      </button>

      <div className="px-6 md:px-12 py-4 max-w-5xl mx-auto">
        {/* Header */}
        <div className="flex items-start justify-between gap-4 mb-4">
          <div className="flex-1 min-w-0">
            <div className="text-xs text-gray-500 uppercase tracking-wide mb-1">{propType?.label ?? candidate.property_type_code}</div>
            <h2 className="text-2xl font-bold text-white mb-1">{candidate.county_name}</h2>
            <div className="text-sm text-gray-400">
              {Math.round(surfaceM2 || 0).toLocaleString('es-CL')} m²
              {candidate.surface_land_m2 && candidate.surface_building_m2 ? (
                <span> · terreno {Math.round(candidate.surface_land_m2).toLocaleString('es-CL')} m²</span>
              ) : null}
            </div>
            <div className="mt-2 text-3xl font-bold text-white">{fmtUFFull(candidate.estimated_uf)}</div>
            {candidate.p25_uf && candidate.p75_uf && (
              <div className="text-xs text-gray-500 mt-0.5">
                rango justo: {fmtUF(candidate.p25_uf)} – {fmtUF(candidate.p75_uf)}
              </div>
            )}
          </div>
          <div className="text-right">
            <div className="text-2xl font-bold tracking-tight" style={{ color: scoreColor(candidate.opportunity_score) }}>
              {scoreStars(candidate.opportunity_score)}
            </div>
            <div className="text-xs mt-1 font-medium" style={{ color: scoreColor(candidate.opportunity_score) }}>
              {scoreLabel(candidate.opportunity_score)}
            </div>
          </div>
        </div>

        {/* Narrative */}
        <div className="bg-gray-900 rounded-xl p-4 mb-4 border border-gray-800">
          <p className="text-sm text-gray-300 leading-relaxed">{buildNarrative()}</p>
        </div>

        {/* 3 cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
          {/* Si arriendas */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <div className="text-xs text-gray-500 mb-1">Si la arriendas</div>
            {yieldGuess !== null ? (
              <>
                <div className="text-xl font-bold text-white mb-0.5">{fmtCLP(monthlyRentCLP)}/mes</div>
                <div className="text-xs text-green-400">{fmtPct(yieldGuess * 100)} rendimiento anual</div>
              </>
            ) : (
              <div className="text-xs text-gray-600">No aplicable a terrenos</div>
            )}
          </div>

          {/* Si vendes */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <div className="text-xs text-gray-500 mb-1">Si la vendes en 5 años</div>
            <div className="text-xl font-bold text-white mb-0.5">{fmtUF(projected5y)}</div>
            <div className="text-xs text-blue-400">+{fmtPct(totalReturn5y)} plusvalía</div>
          </div>

          {/* Tendencia */}
          <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
            <div className="text-xs text-gray-500 mb-1">Tendencia comuna 24m</div>
            <div className="h-12 bg-gradient-to-r from-blue-900/40 to-blue-500/40 rounded mb-1 relative">
              {/* Mini chart placeholder */}
              <svg className="w-full h-full" viewBox="0 0 100 40" preserveAspectRatio="none">
                <polyline
                  points="0,30 15,28 30,25 45,22 60,18 75,15 100,12"
                  fill="none"
                  stroke="#3b82f6"
                  strokeWidth="2"
                />
              </svg>
            </div>
            <div className="text-xs text-blue-400">+{fmtPct(annualGrowth * 100)}/año (RM hist.)</div>
          </div>
        </div>

        {/* Riesgos */}
        <div className="bg-yellow-950/20 border border-yellow-900/40 rounded-xl p-4 mb-4">
          <div className="text-xs font-semibold text-yellow-500 mb-2 flex items-center gap-1.5">
            <AlertTriangle size={11} /> Antes de comprar, verifica
          </div>
          <ul className="space-y-1 text-xs text-gray-300">
            {ddItems.map((item, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className="mt-0.5 inline-block w-3 h-3 rounded border border-gray-700 flex-shrink-0" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        {/* Operator extra */}
        {isOperator && candidate.max_payable_uf && (
          <div className="bg-amber-950/30 border border-amber-900/50 rounded-xl p-4 mb-4">
            <div className="text-xs text-amber-400 mb-1">Como operador comercial — máximo pagable</div>
            <div className="text-xl font-bold text-amber-400">{fmtUFFull(candidate.max_payable_uf)}</div>
            <div className="text-xs text-gray-500 mt-1">
              Estimación cap inverso. Cap rate referencial — INFO_NO_FIDEDIGNA, validar con tasador.
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 flex-wrap mb-4">
          <button
            onClick={() => { toggleWatch(candidate.id); setSaved(s => !s) }}
            className={clsx(
              'px-5 py-2.5 rounded-full flex items-center gap-2 text-sm font-medium border transition-colors',
              saved
                ? 'bg-pink-600/10 text-pink-400 border-pink-700'
                : 'bg-gray-800 text-gray-200 border-gray-700 hover:bg-gray-700'
            )}
          >
            <Heart size={14} fill={saved ? 'currentColor' : 'none'} /> {saved ? 'Guardado' : 'Guardar'}
          </button>
          <button className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-full flex items-center gap-2 border border-gray-700">
            <ArrowLeftRight size={14} /> Comparar
          </button>
          <button
            onClick={() => setExpanded(e => !e)}
            className="px-5 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-200 text-sm font-medium rounded-full flex items-center gap-2 border border-gray-700 ml-auto"
          >
            {expanded ? <>Ocultar detalles <ChevronUp size={14} /></> : <>Más detalles <ChevronDown size={14} /></>}
          </button>
        </div>

        {/* Expanded section */}
        {expanded && (
          <div className="space-y-4 pt-4 border-t border-gray-800">
            <QuickReturnSimulator candidate={candidate} />

            <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <div className="text-xs text-gray-500 mb-2 font-semibold">Datos catastrales</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                {candidate.rol_sii && (
                  <><span className="text-gray-500">Rol SII</span><span className="text-white font-mono">{candidate.rol_sii}</span></>
                )}
                {candidate.address && (
                  <><span className="text-gray-500">Dirección</span><span className="text-white truncate">{candidate.address}</span></>
                )}
                <span className="text-gray-500">Coordenadas</span>
                <span className="text-white font-mono">{candidate.latitude.toFixed(4)}, {candidate.longitude.toFixed(4)}</span>
                {candidate.last_transaction_uf && (
                  <><span className="text-gray-500">Última transacción</span><span className="text-white">{fmtUFFull(candidate.last_transaction_uf)}</span></>
                )}
              </div>
            </div>

            <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
              <div className="text-xs text-gray-500 mb-2 font-semibold">Modo experto (avanzado)</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono">
                <span className="text-gray-500">opportunity_score</span><span className="text-white">{candidate.opportunity_score?.toFixed(4)}</span>
                <span className="text-gray-500">use_specific_score</span><span className="text-white">{candidate.use_specific_score?.toFixed(4) ?? '—'}</span>
                <span className="text-gray-500">valuation_confidence</span><span className="text-white">{candidate.valuation_confidence?.toFixed(2) ?? '—'}</span>
                <span className="text-gray-500">construction_ratio</span><span className="text-white">{(candidate as any).construction_ratio?.toFixed(3) ?? '—'}</span>
              </div>
            </div>
          </div>
        )}

        {/* External links */}
        <div className="flex gap-3 mt-4 pt-4 border-t border-gray-800">
          <a
            href={gmaps}
            target="_blank" rel="noopener noreferrer"
            className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
          >
            <MapPin size={11} /> Google Maps
          </a>
          {candidate.rol_sii && (
            <a
              href="https://www.sii.cl"
              target="_blank" rel="noopener noreferrer"
              className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
            >
              <FileText size={11} /> Ficha SII
            </a>
          )}
        </div>
      </div>
    </div>
  )
}
