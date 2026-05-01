/**
 * SettingsDrawer.tsx — drawer lateral derecho con preferencias del usuario.
 *
 * Incluye:
 *   - ExpertModeToggle (revela SHAP, scores numéricos, vocabulario técnico)
 *   - Reset onboarding
 *   - Versión del modelo y data
 */

import { useState, useEffect } from 'react'
import { X, Settings as SettingsIcon, Brain, RefreshCw, Info } from 'lucide-react'

interface Props {
  onClose: () => void
}

const EXPERT_KEY = 're_cl_expert_mode'
const ONBOARDING_KEY = 're_cl_onboarding_v2'

export function SettingsDrawer({ onClose }: Props) {
  const [expert, setExpert] = useState(localStorage.getItem(EXPERT_KEY) === '1')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const toggleExpert = () => {
    const next = !expert
    setExpert(next)
    localStorage.setItem(EXPERT_KEY, next ? '1' : '0')
    window.dispatchEvent(new Event('expert-mode-changed'))
  }

  const resetOnboarding = () => {
    if (confirm('¿Resetear preferencias y volver al onboarding?')) {
      localStorage.removeItem(ONBOARDING_KEY)
      window.location.reload()
    }
  }

  return (
    <>
      <div className="fixed inset-0 z-40 bg-black/50" onClick={onClose} />
      <aside className="fixed inset-y-0 right-0 z-50 w-96 bg-gray-950 border-l border-gray-800 shadow-2xl flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-800">
          <div className="flex items-center gap-2 text-white">
            <SettingsIcon size={16} />
            <span className="text-sm font-semibold">Configuración</span>
          </div>
          <button onClick={onClose} className="text-gray-500 hover:text-white p-1">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-6">
          {/* Expert mode */}
          <section>
            <div className="flex items-start justify-between gap-4">
              <div className="flex-1">
                <div className="flex items-center gap-2 mb-1">
                  <Brain size={14} className="text-blue-400" />
                  <span className="text-sm font-semibold text-white">Modo experto</span>
                </div>
                <p className="text-xs text-gray-500 leading-relaxed">
                  Muestra scores numéricos, factores SHAP, vocabulario técnico (cap rate, IRR, gap_pct, profile)
                  en cada propiedad y herramientas avanzadas.
                </p>
              </div>
              <button
                onClick={toggleExpert}
                role="switch"
                aria-checked={expert}
                className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${
                  expert ? 'bg-blue-600' : 'bg-gray-700'
                }`}
              >
                <span
                  className={`absolute top-0.5 left-0.5 w-5 h-5 bg-white rounded-full transition-transform ${
                    expert ? 'translate-x-5' : ''
                  }`}
                />
              </button>
            </div>
          </section>

          {/* Reset onboarding */}
          <section>
            <button
              onClick={resetOnboarding}
              className="w-full flex items-center justify-center gap-2 py-2.5 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-full text-sm"
            >
              <RefreshCw size={12} /> Resetear preferencias y volver al onboarding
            </button>
          </section>

          {/* About */}
          <section className="pt-4 border-t border-gray-800">
            <div className="flex items-center gap-2 mb-2">
              <Info size={12} className="text-gray-500" />
              <span className="text-xs text-gray-400 font-semibold">Sobre RE_CL</span>
            </div>
            <div className="space-y-1 text-xs text-gray-500">
              <div>data v3.2 · model v1.0</div>
              <div>R²=0.6712 · 520k transacciones train</div>
              <div>842,227 candidatos · 7 use cases</div>
              <div>10/40 comunas DI 2019-2026</div>
            </div>
          </section>

          {/* Disclaimer */}
          <section>
            <div className="bg-yellow-950/20 border border-yellow-900/40 rounded-lg p-3">
              <div className="text-[10px] text-yellow-500 font-semibold mb-1">DISCLAIMER</div>
              <p className="text-[11px] text-gray-400 leading-relaxed">
                Las estimaciones financieras (cap rate, NOI, plusvalía) son INFO_NO_FIDEDIGNA y
                deben validarse con tasador profesional independiente antes de cualquier decisión
                de inversión. Los scores son orientativos.
              </p>
            </div>
          </section>
        </div>
      </aside>
    </>
  )
}

/** Hook para leer modo experto desde cualquier componente */
export function useExpertMode(): boolean {
  const [enabled, setEnabled] = useState(localStorage.getItem(EXPERT_KEY) === '1')
  useEffect(() => {
    const handler = () => setEnabled(localStorage.getItem(EXPERT_KEY) === '1')
    window.addEventListener('expert-mode-changed', handler)
    return () => window.removeEventListener('expert-mode-changed', handler)
  }, [])
  return enabled
}
