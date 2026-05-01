/**
 * EmptyStateCoach.tsx — sugerencias inteligentes cuando 0 resultados.
 *
 * Nunca mostramos "0 resultados" sin acción sugerida.
 */

import { Lightbulb, ArrowRight, X } from 'lucide-react'
import type { OnboardingState } from './OnboardingFlow'
import { fmtUF } from '../lib/format'

interface Props {
  onboarding: OnboardingState
  onUpdateBudget: (newMax: number | null) => void
  onClearCommunes: () => void
  onChangeObjective: () => void
}

export function EmptyStateCoach({ onboarding, onUpdateBudget, onClearCommunes, onChangeObjective }: Props) {
  const suggestions: { label: string; action: () => void; primary?: boolean }[] = []

  // Si hay presupuesto bajo, sugerir subir
  if (onboarding.maxBudgetUF && onboarding.maxBudgetUF < 8000) {
    const next = Math.min(50000, Math.round(onboarding.maxBudgetUF * 1.5 / 500) * 500)
    suggestions.push({
      label: `Subir presupuesto a ${fmtUF(next)}`,
      action: () => onUpdateBudget(next),
      primary: true,
    })
  }

  // Si hay comunas filtradas, sugerir ampliar
  if (onboarding.communes.length > 0) {
    suggestions.push({
      label: 'Quitar filtro de comuna (toda la RM)',
      action: onClearCommunes,
    })
  }

  // Sugerir cambiar objetivo
  suggestions.push({
    label: 'Cambiar mi objetivo',
    action: onChangeObjective,
  })

  // Sin presupuesto definido pero 0 resultados → quitar todo
  if (!onboarding.maxBudgetUF && onboarding.communes.length === 0) {
    suggestions.length = 0
    suggestions.push({
      label: 'Cambiar mi objetivo',
      action: onChangeObjective,
      primary: true,
    })
  }

  return (
    <div className="absolute inset-0 z-20 flex items-center justify-center pointer-events-none">
      <div className="pointer-events-auto bg-gray-900/95 backdrop-blur rounded-2xl p-6 border border-gray-800 shadow-2xl max-w-md text-center">
        <Lightbulb size={32} className="text-amber-400 mx-auto mb-3" />
        <h3 className="text-white font-semibold mb-2">No encontramos oportunidades con estos criterios</h3>
        <p className="text-sm text-gray-400 mb-5">
          Es probable que el filtro sea muy restrictivo. Prueba estas alternativas:
        </p>
        <div className="space-y-2">
          {suggestions.map((s, i) => (
            <button
              key={i}
              onClick={s.action}
              className={
                s.primary
                  ? 'w-full px-4 py-2.5 bg-blue-600 hover:bg-blue-500 text-white rounded-full text-sm font-medium flex items-center justify-center gap-2'
                  : 'w-full px-4 py-2 bg-gray-800 hover:bg-gray-700 text-gray-300 rounded-full text-sm flex items-center justify-center gap-2'
              }
            >
              {s.label} <ArrowRight size={12} />
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
