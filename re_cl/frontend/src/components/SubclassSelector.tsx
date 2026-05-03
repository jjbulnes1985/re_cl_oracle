import { useEffect, useState } from 'react'
import { useAppStore } from '../store'

interface Subclass {
  subclass: string
  description: string
  parent_class: 'residential' | 'commercial' | 'land'
  active: boolean
}

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

const PARENT_LABELS: Record<string, string> = {
  residential: 'Residencial',
  commercial: 'Comercial / Operacional',
  land: 'Terreno',
}

const PARENT_ICONS: Record<string, string> = {
  residential: '🏠',
  commercial: '🏪',
  land: '🌾',
}

export function SubclassSelector() {
  const [subclasses, setSubclasses] = useState<Subclass[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const activeSubclass = useAppStore((s) => s.activeSubclass)
  const setActiveSubclass = useAppStore((s) => s.setActiveSubclass)
  const subclassHeatmapEnabled = useAppStore((s) => s.subclassHeatmapEnabled)
  const setSubclassHeatmapEnabled = useAppStore((s) => s.setSubclassHeatmapEnabled)

  useEffect(() => {
    fetch(`${API_BASE}/subclasses`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((data: Subclass[]) => {
        setSubclasses(data)
        setLoading(false)
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })
  }, [])

  if (loading) return <div className="p-4 text-sm text-gray-500">Cargando subclases…</div>
  if (error) return <div className="p-4 text-sm text-red-600">Error: {error}</div>

  // Group by parent class
  const grouped: Record<string, Subclass[]> = {}
  subclasses.forEach((s) => {
    if (!grouped[s.parent_class]) grouped[s.parent_class] = []
    grouped[s.parent_class].push(s)
  })

  return (
    <div className="bg-white rounded-lg shadow-lg p-4 max-w-md">
      <div className="flex items-center justify-between mb-3">
        <h3 className="font-semibold text-gray-800">Mapa de calor por subclase</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={subclassHeatmapEnabled}
            onChange={(e) => setSubclassHeatmapEnabled(e.target.checked)}
          />
          Activado
        </label>
      </div>

      {subclassHeatmapEnabled && (
        <>
          <p className="text-xs text-gray-500 mb-3">
            Selecciona una subclase para ver oportunidades específicas según pesos institucionales.
          </p>

          <div className="space-y-3">
            {Object.entries(grouped).map(([parent, items]) => (
              <div key={parent}>
                <div className="text-xs font-semibold text-gray-600 mb-1">
                  {PARENT_ICONS[parent]} {PARENT_LABELS[parent]}
                </div>
                <div className="grid grid-cols-2 gap-1">
                  {items.map((sc) => (
                    <button
                      key={sc.subclass}
                      onClick={() => setActiveSubclass(sc.subclass)}
                      className={`text-left px-3 py-2 rounded text-xs transition ${
                        activeSubclass === sc.subclass
                          ? 'bg-blue-600 text-white'
                          : 'bg-gray-100 text-gray-700 hover:bg-gray-200'
                      }`}
                      title={sc.description}
                    >
                      {sc.subclass.replace(/_/g, ' ')}
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>

          {activeSubclass && (
            <div className="mt-4 pt-3 border-t border-gray-200 text-xs text-gray-600">
              <strong>Activo:</strong>{' '}
              {subclasses.find((s) => s.subclass === activeSubclass)?.description ?? activeSubclass}
            </div>
          )}
        </>
      )}
    </div>
  )
}
