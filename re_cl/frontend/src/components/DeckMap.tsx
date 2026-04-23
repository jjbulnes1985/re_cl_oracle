import { useMemo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import DeckGL from '@deck.gl/react'
import { HeatmapLayer, HexagonLayer } from '@deck.gl/aggregation-layers'
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers'
import { Map } from 'react-map-gl/maplibre'
import { fetchProperties, scoreWithProfile, fetchCommunes, fetchBusStops } from '../api'
import { useAppStore } from '../store'
import type { Property, ScoredProperty } from '../types'
import 'maplibre-gl/dist/maplibre-gl.css'

const COMMUNE_CENTROIDS: Record<string, [number, number]> = {
  'Las Condes':          [-70.596, -33.415],
  'Vitacura':            [-70.584, -33.397],
  'Lo Barnechea':        [-70.527, -33.349],
  'La Reina':            [-70.548, -33.453],
  'Providencia':         [-70.621, -33.432],
  'Ñuñoa':               [-70.596, -33.456],
  'Santiago':            [-70.650, -33.454],
  'La Florida':          [-70.594, -33.515],
  'Peñalolén':           [-70.548, -33.490],
  'Maipú':               [-70.757, -33.514],
  'Pudahuel':            [-70.757, -33.439],
  'La Pintana':          [-70.635, -33.570],
  'Puente Alto':         [-70.576, -33.601],
  'Quilicura':           [-70.735, -33.356],
  'San Bernardo':        [-70.699, -33.596],
  'El Bosque':           [-70.673, -33.572],
  'La Cisterna':         [-70.651, -33.527],
  'San Miguel':          [-70.647, -33.496],
  'Macul':               [-70.575, -33.490],
  'Recoleta':            [-70.641, -33.414],
  'Independencia':       [-70.652, -33.414],
  'Conchalí':            [-70.669, -33.388],
  'Huechuraba':          [-70.637, -33.362],
  'Renca':               [-70.715, -33.399],
  'Cerro Navia':         [-70.732, -33.427],
  'Lo Prado':            [-70.728, -33.445],
  'Quinta Normal':       [-70.697, -33.444],
  'Estación Central':    [-70.675, -33.454],
  'San Ramón':           [-70.643, -33.540],
  'La Granja':           [-70.621, -33.535],
  'Lo Espejo':           [-70.667, -33.548],
  'Pedro Aguirre Cerda': [-70.655, -33.496],
  'Colina':              [-70.680, -33.205],
  'Lampa':               [-70.877, -33.284],
}

// Santiago RM
const INITIAL_VIEW = {
  longitude: -70.67,
  latitude:  -33.45,
  zoom:       11,
  pitch:      40,
  bearing:     0,
}

const METRO_STATIONS = [
  // Línea 1
  { name: "San Pablo", lat: -33.4503, lon: -70.7185, linea: 1 },
  { name: "Las Rejas", lat: -33.4497, lon: -70.6980, linea: 1 },
  { name: "Ecuador", lat: -33.4497, lon: -70.6880, linea: 1 },
  { name: "San Alberto Hurtado", lat: -33.4503, lon: -70.6780, linea: 1 },
  { name: "Universidad de Santiago", lat: -33.4508, lon: -70.6680, linea: 1 },
  { name: "Estación Central", lat: -33.4508, lon: -70.6580, linea: 1 },
  { name: "Alameda", lat: -33.4508, lon: -70.6507, linea: 1 },
  { name: "Universidad de Chile", lat: -33.4412, lon: -70.6497, linea: 1 },
  { name: "Baquedano", lat: -33.4380, lon: -70.6390, linea: 1 },
  { name: "Salvador", lat: -33.4380, lon: -70.6290, linea: 1 },
  { name: "Manuel Montt", lat: -33.4269, lon: -70.6200, linea: 1 },
  { name: "Pedro de Valdivia", lat: -33.4269, lon: -70.6100, linea: 1 },
  { name: "Los Leones", lat: -33.4269, lon: -70.6000, linea: 1 },
  { name: "Tobalaba", lat: -33.4180, lon: -70.5975, linea: 1 },
  { name: "El Golf", lat: -33.4130, lon: -70.5920, linea: 1 },
  { name: "Alcántara", lat: -33.4080, lon: -70.5868, linea: 1 },
  { name: "Escuela Militar", lat: -33.4030, lon: -70.5815, linea: 1 },
  { name: "Manquehue", lat: -33.3980, lon: -70.5770, linea: 1 },
  { name: "Los Dominicos", lat: -33.3890, lon: -70.5670, linea: 1 },
  // Línea 2
  { name: "Vespucio Norte", lat: -33.3760, lon: -70.6430, linea: 2 },
  { name: "Zapadores", lat: -33.3900, lon: -70.6350, linea: 2 },
  { name: "Dorsal", lat: -33.4020, lon: -70.6280, linea: 2 },
  { name: "Cerro Blanco", lat: -33.4090, lon: -70.6440, linea: 2 },
  { name: "Patronato", lat: -33.4190, lon: -70.6440, linea: 2 },
  { name: "Cal y Canto", lat: -33.4340, lon: -70.6510, linea: 2 },
  { name: "La Moneda", lat: -33.4440, lon: -70.6550, linea: 2 },
  { name: "Los Héroes", lat: -33.4490, lon: -70.6560, linea: 2 },
  { name: "Franklin", lat: -33.4580, lon: -70.6570, linea: 2 },
  { name: "El Llano", lat: -33.4650, lon: -70.6590, linea: 2 },
  { name: "San Miguel", lat: -33.4760, lon: -70.6590, linea: 2 },
  { name: "Lo Vial", lat: -33.4830, lon: -70.6610, linea: 2 },
  { name: "Departamental", lat: -33.4900, lon: -70.6620, linea: 2 },
  { name: "Ciudad del Niño", lat: -33.4970, lon: -70.6620, linea: 2 },
  { name: "Lo Ovalle", lat: -33.5060, lon: -70.6620, linea: 2 },
  { name: "El Parrón", lat: -33.5130, lon: -70.6630, linea: 2 },
  { name: "La Cisterna", lat: -33.5180, lon: -70.6650, linea: 2 },
  // Línea 4
  { name: "Tobalaba", lat: -33.4180, lon: -70.5975, linea: 4 },
  { name: "Cristóbal Colón", lat: -33.4130, lon: -70.5850, linea: 4 },
  { name: "Francisco Bilbao", lat: -33.4180, lon: -70.5720, linea: 4 },
  { name: "Príncipe de Gales", lat: -33.4260, lon: -70.5710, linea: 4 },
  { name: "Simon Bolívar", lat: -33.4340, lon: -70.5720, linea: 4 },
  { name: "Grecia", lat: -33.4430, lon: -70.5720, linea: 4 },
  { name: "Los Orientales", lat: -33.4530, lon: -70.5720, linea: 4 },
  { name: "Ñuñoa", lat: -33.4590, lon: -70.5910, linea: 4 },
  { name: "Irarrázabal", lat: -33.4590, lon: -70.6030, linea: 4 },
  { name: "Macul", lat: -33.4720, lon: -70.5780, linea: 4 },
  { name: "Vicuña Mackenna", lat: -33.4820, lon: -70.5770, linea: 4 },
  { name: "Vicente Valdés", lat: -33.4900, lon: -70.5870, linea: 4 },
  { name: "Rojas Magallanes", lat: -33.4980, lon: -70.5880, linea: 4 },
  { name: "Trinidad", lat: -33.5070, lon: -70.5870, linea: 4 },
  { name: "San José de la Estrella", lat: -33.5160, lon: -70.5880, linea: 4 },
  { name: "Los Quillayes", lat: -33.5230, lon: -70.5880, linea: 4 },
  { name: "Elisa Correa", lat: -33.5320, lon: -70.5880, linea: 4 },
  { name: "Hospital Sótero del Río", lat: -33.5400, lon: -70.5900, linea: 4 },
  { name: "Protectora de la Infancia", lat: -33.5460, lon: -70.5910, linea: 4 },
  { name: "Las Mercedes", lat: -33.5520, lon: -70.5920, linea: 4 },
  { name: "Puente Alto", lat: -33.5630, lon: -70.5870, linea: 4 },
]

const SCHOOLS_RM = [
  { name: "U. de Chile", lat: -33.4574, lon: -70.6636 },
  { name: "PUC Campus Casa Central", lat: -33.4402, lon: -70.6403 },
  { name: "U. de Santiago", lat: -33.4503, lon: -70.6680 },
  { name: "U. Adolfo Ibáñez", lat: -33.3985, lon: -70.5770 },
  { name: "U. Andrés Bello", lat: -33.4256, lon: -70.6103 },
  { name: "Colegio San Ignacio", lat: -33.4357, lon: -70.6349 },
  { name: "The Grange School", lat: -33.4001, lon: -70.5660 },
  { name: "Nido de Aguilas", lat: -33.4005, lon: -70.5440 },
  { name: "Redland School", lat: -33.3860, lon: -70.5780 },
  { name: "Colegio Altamira", lat: -33.3895, lon: -70.5820 },
  { name: "Liceo Aplicación", lat: -33.4454, lon: -70.6529 },
  { name: "Colegio San Pedro Nolasco", lat: -33.4578, lon: -70.6610 },
  { name: "U. Diego Portales", lat: -33.4496, lon: -70.6600 },
  { name: "U. Finis Terrae", lat: -33.4170, lon: -70.6060 },
  { name: "U. Mayor", lat: -33.4165, lon: -70.5943 },
  { name: "Instituto Nacional", lat: -33.4494, lon: -70.6574 },
  { name: "Colegio Verbo Divino", lat: -33.3940, lon: -70.5720 },
  { name: "PUC Campus San Joaquín", lat: -33.4990, lon: -70.6130 },
  { name: "U. Técnica Federico Santa María", lat: -33.4979, lon: -70.6158 },
  { name: "Colegio Craighouse", lat: -33.3835, lon: -70.5595 },
]

const PARKS_RM = [
  { name: "Parque Bicentenario", lat: -33.3930, lon: -70.5773 },
  { name: "Parque Araucano", lat: -33.4137, lon: -70.5945 },
  { name: "Parque Padre Hurtado", lat: -33.4090, lon: -70.5700 },
  { name: "Parque O'Higgins", lat: -33.4632, lon: -70.6596 },
  { name: "Parque Forestal", lat: -33.4347, lon: -70.6421 },
  { name: "Cerro San Cristóbal", lat: -33.4245, lon: -70.6340 },
  { name: "Parque Metropolitano", lat: -33.4178, lon: -70.6308 },
  { name: "Parque Balmaceda", lat: -33.4428, lon: -70.6260 },
  { name: "Parque Bustamante", lat: -33.4454, lon: -70.6265 },
  { name: "Plaza de Armas", lat: -33.4373, lon: -70.6504 },
  { name: "Parque Las Américas", lat: -33.4834, lon: -70.7053 },
  { name: "Parque Peñalolén", lat: -33.4960, lon: -70.5545 },
  { name: "Parque de La Florida", lat: -33.5255, lon: -70.5927 },
  { name: "Parque Maipú", lat: -33.5145, lon: -70.7593 },
  { name: "Parque Colina", lat: -33.1990, lon: -70.6760 },
]

// ── Haversine distance helper ─────────────────────────────────────────────────

function haversineKm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371
  const dLat = (lat2 - lat1) * Math.PI / 180
  const dLon = (lon2 - lon1) * Math.PI / 180
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.asin(Math.sqrt(a))
}

type ViewMode = 'scatter' | 'heatmap' | 'hexagon'

function scoreColor(score: number): [number, number, number, number] {
  if (score >= 0.8) return [239, 68, 68, 200]
  if (score >= 0.6) return [249, 115, 22, 200]
  if (score >= 0.4) return [234, 179, 8, 200]
  return [59, 130, 246, 180]
}

function metroColor(linea: number): [number, number, number, number] {
  const colors: Record<number, [number, number, number, number]> = {
    1: [255, 50, 50, 220],   // Línea 1: red
    2: [255, 170, 0, 220],   // Línea 2: orange/yellow
    4: [0, 150, 255, 220],   // Línea 4: blue
    5: [0, 200, 100, 220],   // Línea 5: green
  }
  return colors[linea] ?? [200, 200, 200, 180]
}

export function DeckMap() {
  const { filters, setSelectedProperty, userLocation, maxDistFromUser, mapLayers, setMapLayer } = useAppStore()
  const { showMetro, showCommunes, showSchools, showParks, showBusStops } = mapLayers
  const [viewMode, setViewMode] = useState<ViewMode>('scatter')
  const [tooltip, setTooltip] = useState<{ x: number; y: number; object: Property | ScoredProperty } | null>(null)
  const [metroTooltip, setMetroTooltip] = useState<{ x: number; y: number; name: string; linea: number } | null>(null)
  const [poiTooltip, setPoiTooltip] = useState<{ x: number; y: number; name: string; type: 'school' | 'park' } | null>(null)
  const [viewState, setViewState] = useState(INITIAL_VIEW)
  const [searchAddress, setSearchAddress] = useState('')
  const [searchLoading, setSearchLoading] = useState(false)
  const [geocodeError, setGeocodeError] = useState<string | null>(null)

  // NOTE: Nominatim requires a unique User-Agent and enforces 1 req/sec.
  // For production, proxy requests through the backend to handle rate limiting.
  const handleGeocode = async () => {
    const q = searchAddress.trim()
    if (!q) return
    setSearchLoading(true)
    setGeocodeError(null)
    try {
      const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(q)}&format=json&countrycodes=cl&limit=1`
      const res = await fetch(url, { headers: { 'User-Agent': 'RE_CL-Platform/1.0' } })
      const data = await res.json()
      if (data && data.length > 0) {
        setViewState(v => ({
          ...v,
          latitude: parseFloat(data[0].lat),
          longitude: parseFloat(data[0].lon),
          zoom: 15,
          transitionDuration: 1000,
        }))
      } else {
        setGeocodeError('Dirección no encontrada')
      }
    } catch {
      setGeocodeError('Error al buscar')
    } finally {
      setSearchLoading(false)
    }
  }

  // Fly to user location when it is set
  useEffect(() => {
    if (userLocation) {
      setViewState(v => ({
        ...v,
        latitude: userLocation.lat,
        longitude: userLocation.lon,
        zoom: 13,
        transitionDuration: 1000,
      }))
    }
  }, [userLocation])

  const { data: communeStats = [] } = useQuery({
    queryKey: ['communes'],
    queryFn: fetchCommunes,
    staleTime: 60000,
  })

  const { data: busStops = [] } = useQuery({
    queryKey: ['bus-stops'],
    queryFn: fetchBusStops,
    staleTime: 3600000, // 1h — GTFS data changes infrequently
    enabled: showBusStops,
  })

  const communeData = useMemo(() =>
    communeStats
      .filter(c => COMMUNE_CENTROIDS[c.county_name])
      .map(c => ({
        position: COMMUNE_CENTROIDS[c.county_name] as [number, number],
        name: c.county_name,
        score: c.median_score ?? 0,
        n: c.n_transactions,
      })),
    [communeStats]
  )

  const isCustomProfile = filters.profileName === 'custom' || filters.profileName !== 'default'

  // Fetch base properties
  const { data: baseProps = [], isLoading: loadingBase } = useQuery({
    queryKey: ['properties', filters.projectTypes, filters.counties, filters.minScore],
    queryFn: () =>
      fetchProperties({
        min_score: Math.max(0, filters.minScore - 0.1),
        limit: 8000,
        ...(filters.counties.length === 1 ? { county_name: filters.counties[0] } : {}),
        ...(filters.projectTypes.length === 1 ? { project_type: filters.projectTypes[0] } : {}),
      }),
    enabled: !isCustomProfile,
  })

  // Fetch re-scored properties when custom profile active
  const profileWeights = filters.profileName === 'custom'
    ? { weights: filters.customWeights }
    : { profile: filters.profileName }

  const { data: scoredProps = [], isLoading: loadingScored } = useQuery({
    queryKey: ['scored', filters.profileName, filters.customWeights, filters.counties, filters.projectTypes],
    queryFn: () =>
      scoreWithProfile({
        ...profileWeights,
        limit: 8000,
        ...(filters.counties.length === 1 ? { county_name: filters.counties[0] } : {}),
        ...(filters.projectTypes.length === 1 ? { project_type: filters.projectTypes[0] } : {}),
      }),
    enabled: isCustomProfile,
  })

  const applyNewFilters = (p: Property | ScoredProperty) => {
    const { searchText, cityZone, maxDistMetro } = filters
    if (searchText) {
      const q = searchText.toLowerCase()
      if (!(p.county_name ?? '').toLowerCase().includes(q)) return false
    }
    if (cityZone.length > 0) {
      if (!cityZone.includes((p as Property).city_zone ?? '')) return false
    }
    if (maxDistMetro > 0) {
      const dist = (p as Property).dist_metro_km
      if (dist == null || dist > maxDistMetro) return false
    }
    return true
  }

  const displayData = isCustomProfile
    ? (scoredProps as ScoredProperty[]).filter(
        (p) => (p.opportunity_score ?? 0) >= filters.minScore && applyNewFilters(p)
      )
    : (baseProps as Property[]).filter((p) => {
        const score = p.opportunity_score ?? 0
        const inType = filters.projectTypes.length === 0 || filters.projectTypes.includes(p.project_type ?? '')
        const inCounty = filters.counties.length === 0 || filters.counties.includes(p.county_name ?? '')
        return score >= filters.minScore && inType && inCounty && applyNewFilters(p)
      })

  // Filter to only geolocated points for map layers, applying user-location radius filter
  const geoData = useMemo(
    () =>
      (displayData as (Property | ScoredProperty)[])
        .filter((p) => 'latitude' in p && (p as Property).latitude && (p as Property).longitude)
        .filter((p) => {
          if (!userLocation || maxDistFromUser === 0) return true
          const prop = p as Property
          if (!prop.latitude || !prop.longitude) return false
          return haversineKm(userLocation.lat, userLocation.lon, prop.latitude, prop.longitude) <= maxDistFromUser
        }) as Property[],
    [displayData, userLocation, maxDistFromUser]
  )

  // Breakdown counts
  const altaCount     = geoData.filter((p) => (p.opportunity_score ?? 0) >= 0.8).length
  const mediaAltaCount = geoData.filter((p) => { const s = p.opportunity_score ?? 0; return s >= 0.6 && s < 0.8 }).length
  const mediaCount    = geoData.filter((p) => { const s = p.opportunity_score ?? 0; return s >= 0.4 && s < 0.6 }).length
  const bajaCount     = geoData.filter((p) => (p.opportunity_score ?? 0) < 0.4).length

  const layers = useMemo(() => {
    const result = []

    if (viewMode === 'heatmap') {
      result.push(
        new HeatmapLayer({
          id: 'heatmap',
          data: geoData,
          getPosition: (d) => [d.longitude!, d.latitude!],
          getWeight: (d) => d.opportunity_score ?? 0,
          aggregation: 'SUM',
          intensity: 1,
          threshold: 0.05,
          radiusPixels: 30,
        })
      )
    } else if (viewMode === 'hexagon') {
      result.push(
        new HexagonLayer({
          id: 'hexagon',
          data: geoData,
          getPosition: (d) => [d.longitude!, d.latitude!],
          getElevationWeight: (d) => d.opportunity_score ?? 0,
          getColorWeight: (d) => d.opportunity_score ?? 0,
          elevationScale: 200,
          radius: 500,
          extruded: true,
          pickable: true,
          colorRange: [
            [59, 130, 246, 200],
            [234, 179, 8, 200],
            [249, 115, 22, 200],
            [239, 68, 68, 200],
          ],
        })
      )
    } else {
      // Scatter (default)
      result.push(
        new ScatterplotLayer<Property>({
          id: 'scatter',
          data: geoData,
          getPosition: (d) => [d.longitude!, d.latitude!],
          getRadius: (d) => 30 + (d.opportunity_score ?? 0) * 60,
          getFillColor: (d) => scoreColor(d.opportunity_score ?? 0),
          getLineColor: [255, 255, 255, 60],
          lineWidthMinPixels: 1,
          pickable: true,
          radiusMinPixels: 3,
          radiusMaxPixels: 18,
          onHover: ({ object, x, y }) =>
            setTooltip(object ? { x, y, object } : null),
          onClick: ({ object }) => {
            if (object) setSelectedProperty(object)
          },
        })
      )
    }

    if (showCommunes) {
      result.push(
        new ScatterplotLayer({
          id: 'communes-bg',
          data: communeData,
          getPosition: d => d.position,
          getRadius: d => 800 + d.n * 0.5,
          getFillColor: d => {
            const s = d.score
            if (s >= 0.8) return [239, 68, 68, 40]
            if (s >= 0.6) return [249, 115, 22, 40]
            if (s >= 0.4) return [234, 179, 8, 40]
            return [59, 130, 246, 40]
          },
          radiusMinPixels: 20,
          radiusMaxPixels: 80,
          pickable: false,
        }),
        new TextLayer({
          id: 'commune-labels',
          data: communeData,
          getPosition: d => d.position,
          getText: d => `${d.name}\n${d.score.toFixed(2)}`,
          getSize: 11,
          getColor: [255, 255, 255, 180],
          getTextAnchor: 'middle',
          getAlignmentBaseline: 'center',
          fontFamily: 'monospace',
        })
      )
    }

    if (showMetro) {
      result.push(
        new ScatterplotLayer({
          id: 'metro-stations',
          data: METRO_STATIONS,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 120,
          getFillColor: (d) => metroColor(d.linea),
          getLineColor: [255, 255, 255, 200],
          lineWidthMinPixels: 1,
          radiusMinPixels: 5,
          radiusMaxPixels: 12,
          pickable: true,
          onHover: ({ object, x, y }) => {
            if (object && 'name' in object) {
              setMetroTooltip({ x, y, name: (object as typeof METRO_STATIONS[0]).name, linea: (object as typeof METRO_STATIONS[0]).linea })
            } else {
              setMetroTooltip(null)
            }
          },
        })
      )
    }

    if (showSchools) {
      result.push(
        new ScatterplotLayer({
          id: 'schools',
          data: SCHOOLS_RM,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 180,
          getFillColor: [34, 197, 94, 200],
          getLineColor: [255, 255, 255, 150],
          lineWidthMinPixels: 1,
          radiusMinPixels: 5,
          radiusMaxPixels: 14,
          pickable: true,
          onHover: ({ object, x, y }) => {
            if (object && 'name' in object) {
              setPoiTooltip({ x, y, name: (object as typeof SCHOOLS_RM[0]).name, type: 'school' })
            } else {
              setPoiTooltip(null)
            }
          },
        })
      )
    }

    if (showParks) {
      result.push(
        new ScatterplotLayer({
          id: 'parks',
          data: PARKS_RM,
          getPosition: (d) => [d.lon, d.lat],
          getRadius: 300,
          getFillColor: [16, 185, 129, 160],
          getLineColor: [255, 255, 255, 100],
          lineWidthMinPixels: 1,
          radiusMinPixels: 6,
          radiusMaxPixels: 18,
          pickable: true,
          onHover: ({ object, x, y }) => {
            if (object && 'name' in object) {
              setPoiTooltip({ x, y, name: (object as typeof PARKS_RM[0]).name, type: 'park' })
            } else {
              setPoiTooltip(null)
            }
          },
        })
      )
    }

    // Bus stops layer (GTFS RED)
    if (showBusStops && busStops.length > 0) {
      result.push(
        new ScatterplotLayer({
          id: 'bus-stops',
          data: busStops,
          getPosition: (d: { lon: number; lat: number }) => [d.lon, d.lat],
          getRadius: 60,
          getFillColor: [251, 191, 36, 200],  // amber
          getLineColor: [255, 255, 255, 120],
          lineWidthMinPixels: 1,
          radiusMinPixels: 2,
          radiusMaxPixels: 7,
          pickable: true,
          onHover: (info: any) => {
            if (info.object) {
              setPoiTooltip({ x: info.x, y: info.y, name: info.object.name, type: 'school' })
            } else {
              setPoiTooltip(null)
            }
          },
        })
      )
    }

    // User location marker (rendered on top of everything)
    if (userLocation) {
      result.push(
        new ScatterplotLayer({
          id: 'user-location',
          data: [userLocation],
          getPosition: (d: { lat: number; lon: number }) => [d.lon, d.lat],
          getRadius: 150,
          getFillColor: [0, 120, 255, 200],
          getLineColor: [255, 255, 255, 255],
          lineWidthMinPixels: 2,
          radiusMinPixels: 8,
          radiusMaxPixels: 20,
          pickable: false,
        })
      )
    }

    return result
  }, [geoData, viewMode, showMetro, showCommunes, showSchools, showParks, showBusStops, busStops, communeData, setSelectedProperty, userLocation])

  const loading = loadingBase || loadingScored

  return (
    <div className="relative w-full h-full">
      {/* View mode controls */}
      <div className="absolute top-3 right-3 z-10 flex gap-2">
        {(['scatter', 'heatmap', 'hexagon'] as ViewMode[]).map((m) => (
          <button
            key={m}
            onClick={() => setViewMode(m)}
            className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
              viewMode === m
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
            }`}
          >
            {m === 'scatter' ? 'Puntos' : m === 'heatmap' ? 'Calor' : 'Hexágonos'}
          </button>
        ))}
        <button
          onClick={() => setMapLayer('showMetro', !showMetro)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showMetro ? 'bg-red-700 text-white' : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
          }`}
        >
          Metro
        </button>
        <button
          onClick={() => setMapLayer('showCommunes', !showCommunes)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showCommunes ? 'bg-purple-700 text-white' : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
          }`}
        >
          Comunas
        </button>
        <button
          onClick={() => setMapLayer('showSchools', !showSchools)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showSchools ? 'bg-green-700 text-white' : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
          }`}
        >
          Colegios
        </button>
        <button
          onClick={() => setMapLayer('showParks', !showParks)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showParks ? 'bg-emerald-700 text-white' : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
          }`}
        >
          Parques
        </button>
        <button
          onClick={() => setMapLayer('showBusStops', !showBusStops)}
          className={`px-3 py-1.5 rounded text-xs font-medium transition-colors ${
            showBusStops ? 'bg-amber-600 text-white' : 'bg-gray-800/90 text-gray-300 hover:bg-gray-700'
          }`}
        >
          Bus
        </button>
      </div>

      {/* Address geocoding search */}
      <div className="absolute top-3 left-3 z-10 flex gap-2">
        <input
          type="text"
          value={searchAddress}
          onChange={e => { setSearchAddress(e.target.value); setGeocodeError(null) }}
          onKeyDown={e => e.key === 'Enter' && handleGeocode()}
          placeholder="Buscar dirección..."
          className="w-56 px-3 py-1.5 rounded bg-gray-900/90 border border-gray-700 text-xs text-gray-200 placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={handleGeocode}
          disabled={searchLoading || !searchAddress.trim()}
          className="px-3 py-1.5 rounded bg-gray-800/90 text-gray-300 text-xs hover:bg-gray-700 disabled:opacity-40"
        >
          {searchLoading ? '…' : 'Ir'}
        </button>
        {geocodeError && <span className="text-xs text-red-400 self-center">{geocodeError}</span>}
      </div>

      {/* Loading indicator */}
      {loading && (
        <div className="absolute top-3 left-1/2 -translate-x-1/2 z-10 bg-gray-900/90 text-blue-400 text-xs px-3 py-1.5 rounded">
          Cargando datos…
        </div>
      )}

      {/* Enhanced property count indicator */}
      <div className="absolute bottom-8 left-3 z-10">
        <div className="bg-gray-900/90 border border-gray-700 rounded-lg px-3 py-2 shadow-lg">
          <p className="text-white text-xs font-semibold mb-1">
            {geoData.length.toLocaleString()} propiedades
            {isCustomProfile && <span className="text-gray-400 font-normal"> · perfil: {filters.profileName}</span>}
          </p>
          {geoData.length > 0 && (
            <div className="flex gap-2 text-[11px]">
              {altaCount > 0 && (
                <span className="flex items-center gap-1 text-red-400">
                  <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
                  {altaCount} alta
                </span>
              )}
              {mediaAltaCount > 0 && (
                <span className="flex items-center gap-1 text-orange-400">
                  <span className="w-2 h-2 rounded-full bg-orange-500 inline-block" />
                  {mediaAltaCount} m-alta
                </span>
              )}
              {mediaCount > 0 && (
                <span className="flex items-center gap-1 text-yellow-400">
                  <span className="w-2 h-2 rounded-full bg-yellow-500 inline-block" />
                  {mediaCount} media
                </span>
              )}
              {bajaCount > 0 && (
                <span className="flex items-center gap-1 text-blue-400">
                  <span className="w-2 h-2 rounded-full bg-blue-500 inline-block" />
                  {bajaCount} baja
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: v }) => setViewState(v as typeof INITIAL_VIEW)}
        controller={true}
        layers={layers}
        style={{ width: '100%', height: '100%' }}
      >
        <Map
          mapStyle="https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json"
          attributionControl={false}
        />
      </DeckGL>

      {/* Property tooltip */}
      {tooltip && (
        <div
          className="absolute z-20 pointer-events-none bg-gray-900/95 border border-gray-700 rounded p-2 text-xs text-gray-200 shadow-xl max-w-[200px]"
          style={{ left: tooltip.x + 12, top: tooltip.y - 20 }}
        >
          <p className="font-semibold text-white">
            {(tooltip.object as Property).project_type} · {(tooltip.object as Property).county_name}
          </p>
          <p>Score: <span className="text-blue-400 font-bold">{((tooltip.object as Property).opportunity_score ?? 0).toFixed(3)}</span></p>
          {(tooltip.object as Property).uf_m2_building && (
            <p>UF/m²: {(tooltip.object as Property).uf_m2_building?.toFixed(1)}</p>
          )}
          {(tooltip.object as Property).gap_pct != null && (
            <p>Gap: {(((tooltip.object as Property).gap_pct ?? 0) * 100).toFixed(1)}%</p>
          )}
          <p className="text-gray-500 mt-1">Click para detalle</p>
        </div>
      )}

      {/* Metro station tooltip */}
      {metroTooltip && (
        <div
          className="absolute z-20 pointer-events-none bg-gray-900/95 border border-gray-700 rounded p-2 text-xs text-gray-200 shadow-xl max-w-[180px]"
          style={{ left: metroTooltip.x + 12, top: metroTooltip.y - 20 }}
        >
          <p className="font-semibold text-white">{metroTooltip.name}</p>
          <p>
            Línea{' '}
            <span
              className="font-bold"
              style={{ color: metroTooltip.linea === 1 ? '#ff3232' : metroTooltip.linea === 2 ? '#ffaa00' : metroTooltip.linea === 4 ? '#0096ff' : '#00c864' }}
            >
              L{metroTooltip.linea}
            </span>
          </p>
        </div>
      )}

      {/* POI tooltip */}
      {poiTooltip && (
        <div className="absolute z-20 pointer-events-none bg-gray-900/95 border border-gray-700 rounded p-2 text-xs text-gray-200 shadow-xl" style={{ left: poiTooltip.x + 12, top: poiTooltip.y - 20 }}>
          <p className="font-semibold" style={{ color: poiTooltip.type === 'school' ? '#22c55e' : '#10b981' }}>
            {poiTooltip.type === 'school' ? '🎓' : '🌳'} {poiTooltip.name}
          </p>
        </div>
      )}

      {/* Legend */}
      {viewMode === 'scatter' && (
        <div className="absolute bottom-8 right-3 z-10 bg-gray-900/90 border border-gray-800 rounded p-2 text-xs text-gray-300">
          <p className="font-semibold text-gray-200 mb-1">Opportunity Score</p>
          {[
            { label: '0.8–1.0 Alta',       color: 'bg-red-500' },
            { label: '0.6–0.8 Media-Alta',  color: 'bg-orange-500' },
            { label: '0.4–0.6 Media',       color: 'bg-yellow-500' },
            { label: '0.0–0.4 Baja',        color: 'bg-blue-500' },
          ].map(({ label, color }) => (
            <div key={label} className="flex items-center gap-2 mt-0.5">
              <div className={`w-3 h-3 rounded-full ${color}`} />
              <span>{label}</span>
            </div>
          ))}
          {showMetro && (
            <>
              <p className="font-semibold text-gray-200 mt-2 mb-1">Metro</p>
              {[
                { label: 'Línea 1', color: 'bg-red-500' },
                { label: 'Línea 2', color: 'bg-yellow-500' },
                { label: 'Línea 4', color: 'bg-blue-400' },
              ].map(({ label, color }) => (
                <div key={label} className="flex items-center gap-2 mt-0.5">
                  <div className={`w-3 h-3 rounded-full ${color}`} />
                  <span>{label}</span>
                </div>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  )
}
