/**
 * OnboardingFlow.tsx — 3 pantallas, máximo 30 segundos.
 *
 * 1. ¿Qué buscas? — 4 objetivos
 * 2. ¿Cuánto puedes invertir? — slider UF + opción "no sé"
 * 3. ¿En qué zonas? — chips multi-select
 *
 * Mapping interno objetivo → use_case + investor_profile (no expuesto).
 */

import { useState } from 'react'
import { Home, TrendingUp, Trees, Eye, ArrowRight, ArrowLeft, X } from 'lucide-react'
import { clsx } from 'clsx'
import { fmtUF } from '../lib/format'

export interface OnboardingState {
  objectiveCode: 'rent' | 'flip' | 'develop' | 'explore'
  useCase:       string
  profile:       string
  maxBudgetUF:   number | null
  communes:      string[]
}

export const OBJECTIVES = [
  {
    code:    'rent',
    label:   'Comprar para arrendar',
    desc:    'Genero ingresos mensuales con renta',
    icon:    Home,
    useCase: 'as_is',
    profile: 'income',
  },
  {
    code:    'flip',
    label:   'Comprar para revender en 3-5 años',
    desc:    'Apuesto a la plusvalía',
    icon:    TrendingUp,
    useCase: 'as_is',
    profile: 'growth',
  },
  {
    code:    'develop',
    label:   'Comprar terreno para desarrollar',
    desc:    'Construyo o subdivido',
    icon:    Trees,
    useCase: 'as_is',
    profile: 'redevelopment',
  },
  {
    code:    'explore',
    label:   'Solo estoy explorando',
    desc:    'Quiero ver qué hay disponible',
    icon:    Eye,
    useCase: 'as_is',
    profile: 'value',
  },
] as const

const POPULAR_COMMUNES = [
  'Maipú', 'La Florida', 'Ñuñoa', 'Santiago', 'Providencia',
  'Las Condes', 'Vitacura', 'Puente Alto', 'San Bernardo',
  'Quilicura', 'Peñalolén', 'La Reina',
]

const ALL_COMMUNES = [
  'Maipú', 'La Florida', 'Ñuñoa', 'Santiago', 'Providencia', 'Las Condes',
  'Vitacura', 'San Bernardo', 'Puente Alto', 'Quilicura', 'Peñalolén',
  'La Pintana', 'El Bosque', 'Recoleta', 'Conchalí', 'Lo Barnechea',
  'Pudahuel', 'Macul', 'Cerro Navia', 'Renca', 'Estación Central',
  'Quinta Normal', 'San Miguel', 'La Cisterna', 'Huechuraba', 'San Joaquín',
  'Lo Espejo', 'Pedro Aguirre Cerda', 'Lo Prado', 'San Ramón', 'La Granja',
  'Independencia', 'Cerrillos', 'Lampa', 'Colina', 'Buin', 'Melipilla',
  'Pirque', 'Talagante', 'Calera de Tango', 'La Reina',
]

const BUDGET_PRESETS = [1500, 3000, 5000, 8000, 15000]

interface Props {
  initial?: OnboardingState | null
  onComplete: (state: OnboardingState) => void
  onSkip: () => void
}

export function OnboardingFlow({ initial, onComplete, onSkip }: Props) {
  const [step, setStep] = useState(0)
  const [objectiveCode, setObjectiveCode] = useState<OnboardingState['objectiveCode']>(initial?.objectiveCode ?? 'explore')
  const [maxBudget, setMaxBudget] = useState<number | null>(initial?.maxBudgetUF ?? null)
  const [communes, setCommunes] = useState<string[]>(initial?.communes ?? [])
  const [communeSearch, setCommuneSearch] = useState('')

  const currentObjective = OBJECTIVES.find(o => o.code === objectiveCode)!

  const handleFinish = () => {
    onComplete({
      objectiveCode,
      useCase: currentObjective.useCase,
      profile: currentObjective.profile,
      maxBudgetUF: maxBudget,
      communes,
    })
  }

  const filteredCommunes = ALL_COMMUNES.filter(c =>
    c.toLowerCase().includes(communeSearch.toLowerCase())
  )

  return (
    <div className="fixed inset-0 z-50 bg-gray-950 flex flex-col">
      {/* Top bar */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-gray-800">
        <div className="text-white font-bold text-xl">RE_CL</div>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          <span className={step === 0 ? 'text-white' : ''}>1</span>
          <span>·</span>
          <span className={step === 1 ? 'text-white' : ''}>2</span>
          <span>·</span>
          <span className={step === 2 ? 'text-white' : ''}>3</span>
        </div>
        <button
          onClick={onSkip}
          className="text-xs text-gray-500 hover:text-white px-3 py-1.5"
        >
          Saltar y explorar
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-6 py-12">
        <div className="max-w-3xl mx-auto">
          {/* STEP 1: Objective */}
          {step === 0 && (
            <div>
              <h1 className="text-3xl md:text-4xl font-bold text-white mb-3">¿Qué buscas?</h1>
              <p className="text-gray-400 text-base mb-8">Esto nos ayuda a mostrarte oportunidades alineadas a tu objetivo.</p>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {OBJECTIVES.map(({ code, label, desc, icon: Icon }) => (
                  <button
                    key={code}
                    onClick={() => setObjectiveCode(code as any)}
                    className={clsx(
                      'p-6 rounded-2xl border text-left transition-all',
                      objectiveCode === code
                        ? 'bg-blue-600/10 border-blue-500 text-white'
                        : 'bg-gray-900 border-gray-800 text-gray-300 hover:border-gray-600 hover:text-white'
                    )}
                  >
                    <Icon size={28} className={objectiveCode === code ? 'text-blue-400 mb-3' : 'text-gray-500 mb-3'} />
                    <div className="font-semibold text-lg mb-1">{label}</div>
                    <div className="text-sm text-gray-500">{desc}</div>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* STEP 2: Budget */}
          {step === 1 && (
            <div>
              <h1 className="text-3xl md:text-4xl font-bold text-white mb-3">¿Cuánto puedes invertir?</h1>
              <p className="text-gray-400 text-base mb-8">Te mostraremos solo oportunidades dentro de tu presupuesto.</p>

              <div className="bg-gray-900 rounded-2xl p-6 border border-gray-800">
                {maxBudget !== null ? (
                  <>
                    <div className="text-center mb-6">
                      <div className="text-5xl font-bold text-white mb-2">{fmtUF(maxBudget)}</div>
                      <div className="text-sm text-gray-500">presupuesto máximo</div>
                    </div>
                    <input
                      type="range"
                      min={500} max={50000} step={500}
                      value={maxBudget}
                      onChange={e => setMaxBudget(Number(e.target.value))}
                      className="w-full accent-blue-500 mb-3"
                    />
                    <div className="flex justify-between text-xs text-gray-600 mb-6">
                      <span>500 UF</span><span>10k UF</span><span>25k UF</span><span>50k UF+</span>
                    </div>
                    <div className="flex gap-2 flex-wrap">
                      {BUDGET_PRESETS.map(p => (
                        <button
                          key={p}
                          onClick={() => setMaxBudget(p)}
                          className={clsx(
                            'px-4 py-2 rounded-full text-sm border',
                            maxBudget === p
                              ? 'bg-blue-600 text-white border-blue-500'
                              : 'bg-gray-800 text-gray-400 border-gray-700 hover:text-white'
                          )}
                        >
                          {fmtUF(p)}
                        </button>
                      ))}
                      <button
                        onClick={() => setMaxBudget(null)}
                        className="px-4 py-2 rounded-full text-sm bg-gray-800 text-gray-500 border border-gray-700 hover:text-white"
                      >
                        Aún no lo sé
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="text-center py-8">
                    <p className="text-gray-400 mb-6">No hay problema, te mostraremos todo el rango.</p>
                    <button
                      onClick={() => setMaxBudget(3000)}
                      className="text-blue-400 hover:text-blue-300 text-sm underline"
                    >
                      Definir presupuesto
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* STEP 3: Zones */}
          {step === 2 && (
            <div>
              <h1 className="text-3xl md:text-4xl font-bold text-white mb-3">¿En qué zonas te interesa buscar?</h1>
              <p className="text-gray-400 text-base mb-8">
                Selecciona una o más comunas. {communes.length === 0 && '(o déjalo vacío para toda la RM)'}
              </p>

              <div className="bg-gray-900 rounded-2xl p-6 border border-gray-800">
                <input
                  type="text"
                  placeholder="Buscar comuna..."
                  value={communeSearch}
                  onChange={e => setCommuneSearch(e.target.value)}
                  className="w-full bg-gray-800 text-white text-sm px-4 py-3 rounded-xl border border-gray-700 mb-4 focus:border-blue-500 focus:outline-none"
                />

                {!communeSearch && (
                  <div className="mb-4">
                    <div className="text-xs text-gray-500 mb-2">Más populares</div>
                    <div className="flex gap-2 flex-wrap">
                      {POPULAR_COMMUNES.map(c => (
                        <button
                          key={c}
                          onClick={() => setCommunes(p => p.includes(c) ? p.filter(x => x !== c) : [...p, c])}
                          className={clsx(
                            'px-3 py-1.5 rounded-full text-sm border',
                            communes.includes(c)
                              ? 'bg-blue-600 text-white border-blue-500'
                              : 'bg-gray-800 text-gray-300 border-gray-700 hover:text-white'
                          )}
                        >
                          {c}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                {communeSearch && (
                  <div className="max-h-60 overflow-y-auto">
                    {filteredCommunes.map(c => (
                      <label
                        key={c}
                        className="flex items-center gap-2 px-3 py-2 hover:bg-gray-800 rounded-lg cursor-pointer"
                      >
                        <input
                          type="checkbox"
                          checked={communes.includes(c)}
                          onChange={() => setCommunes(p => p.includes(c) ? p.filter(x => x !== c) : [...p, c])}
                          className="accent-blue-500"
                        />
                        <span className="text-sm text-gray-300">{c}</span>
                      </label>
                    ))}
                  </div>
                )}

                {communes.length > 0 && (
                  <div className="mt-4 pt-4 border-t border-gray-800">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-gray-500">{communes.length} seleccionada(s)</span>
                      <button onClick={() => setCommunes([])} className="text-xs text-red-400 hover:text-red-300">Limpiar</button>
                    </div>
                    <div className="flex gap-1.5 flex-wrap">
                      {communes.map(c => (
                        <span key={c} className="text-xs px-2 py-1 rounded-full bg-blue-600/20 text-blue-300 border border-blue-600/30 flex items-center gap-1">
                          {c}
                          <button onClick={() => setCommunes(p => p.filter(x => x !== c))}><X size={10} /></button>
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Bottom nav */}
      <div className="border-t border-gray-800 px-6 py-4 flex items-center justify-between bg-gray-950">
        <button
          onClick={() => setStep(s => Math.max(0, s - 1))}
          disabled={step === 0}
          className={clsx(
            'flex items-center gap-2 text-sm px-4 py-2 rounded-full',
            step === 0 ? 'text-gray-700 cursor-not-allowed' : 'text-gray-400 hover:text-white'
          )}
        >
          <ArrowLeft size={14} /> Atrás
        </button>
        {step < 2 ? (
          <button
            onClick={() => setStep(s => Math.min(2, s + 1))}
            className="flex items-center gap-2 text-sm px-6 py-3 rounded-full bg-blue-600 hover:bg-blue-500 text-white font-medium"
          >
            Siguiente <ArrowRight size={14} />
          </button>
        ) : (
          <button
            onClick={handleFinish}
            className="flex items-center gap-2 text-sm px-6 py-3 rounded-full bg-green-600 hover:bg-green-500 text-white font-medium"
          >
            Mostrar oportunidades <ArrowRight size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
