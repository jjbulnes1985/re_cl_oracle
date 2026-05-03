import { HeatmapLayer } from '@deck.gl/aggregation-layers'
import { useEffect, useState } from 'react'

const API_BASE = import.meta.env.VITE_API_URL || 'http://127.0.0.1:8000'

export interface HeatmapPoint {
  lat: number
  lng: number
  score: number
  candidate_id: number
}

interface UseSubclassHeatmapResult {
  data: HeatmapPoint[]
  layer: HeatmapLayer | null
  loading: boolean
  error: string | null
}

/**
 * React hook that fetches heatmap data for a given subclass and returns
 * a Deck.gl HeatmapLayer ready to be passed to <DeckGL layers={[layer]}>.
 *
 * Usage:
 *   const { layer } = useSubclassHeatmap('apartment_income', { scoreMin: 0.6, limit: 10000 })
 *   <DeckGL layers={[layer].filter(Boolean)} ... />
 */
export function useSubclassHeatmap(
  subclass: string | null,
  options: { scoreMin?: number; limit?: number; bbox?: [number, number, number, number] } = {}
): UseSubclassHeatmapResult {
  const [data, setData] = useState<HeatmapPoint[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!subclass) {
      setData([])
      return
    }
    setLoading(true)
    setError(null)

    const params = new URLSearchParams()
    if (options.scoreMin !== undefined) params.set('score_min', String(options.scoreMin))
    if (options.limit !== undefined) params.set('limit', String(options.limit))
    if (options.bbox) params.set('bbox', options.bbox.join(','))

    fetch(`${API_BASE}/subclasses/${subclass}/heatmap?${params.toString()}`)
      .then((r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`)
        return r.json()
      })
      .then((points: HeatmapPoint[]) => {
        setData(points)
        setLoading(false)
      })
      .catch((e) => {
        setError(e.message)
        setLoading(false)
      })
  }, [subclass, options.scoreMin, options.limit, options.bbox?.join(',')])

  const layer = subclass && data.length > 0
    ? new HeatmapLayer({
        id: `subclass-heatmap-${subclass}`,
        data,
        getPosition: (d: HeatmapPoint) => [d.lng, d.lat],
        getWeight: (d: HeatmapPoint) => d.score,
        radiusPixels: 40,
        intensity: 1.5,
        threshold: 0.05,
        colorRange: [
          [33, 102, 172, 0],     // transparent
          [103, 169, 207, 100],  // light blue
          [209, 229, 240, 150],  // very light blue
          [253, 219, 199, 200],  // light orange
          [239, 138, 98, 230],   // orange
          [178, 24, 43, 255],    // red
        ],
        aggregation: 'SUM',
        weightsTextureSize: 512,
      })
    : null

  return { data, layer, loading, error }
}
