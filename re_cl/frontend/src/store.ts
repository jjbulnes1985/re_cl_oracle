import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { Property, ProfileName, CustomWeights, AuthUser, SavedSearch } from './types'

interface Filters {
  projectTypes: string[]
  counties: string[]
  minScore: number
  profileName: ProfileName
  customWeights: CustomWeights
  cityZone: string[]
  maxDistMetro: number
  searchText: string
}

interface MapLayers {
  showMetro: boolean
  showCommunes: boolean
  showSchools: boolean
  showParks: boolean
  showBusStops: boolean
}

interface AppState {
  filters: Filters
  selectedProperty: Property | null
  sidebarOpen: boolean
  activeTab: 'map' | 'ranking' | 'communes' | 'detail' | 'compare' | 'watchlist' | 'trends' | 'finance'
  mapLayers: MapLayers

  // Asset subclass heatmap
  activeSubclass: string | null  // null = use opportunity_score, otherwise use subclass_scores[name]
  subclassHeatmapEnabled: boolean

  // Comparator state
  compareA: Property | null
  compareB: Property | null

  // Watchlist state
  watchlist: Property[]

  // Geolocation state
  userLocation: { lat: number; lon: number } | null
  maxDistFromUser: number  // km, 0 = no filter

  // Auth state
  authToken: string | null
  authUser: AuthUser | null
  savedSearches: SavedSearch[]
  authModalOpen: boolean

  setFilters: (partial: Partial<Filters>) => void
  setSelectedProperty: (p: Property | null) => void
  setSidebarOpen: (open: boolean) => void
  setActiveTab: (tab: AppState['activeTab']) => void
  setCompareA: (p: Property | null) => void
  setCompareB: (p: Property | null) => void
  setCityZone: (z: string[]) => void
  setMaxDistMetro: (d: number) => void
  setSearchText: (t: string) => void
  addToWatchlist: (p: Property) => void
  removeFromWatchlist: (id: number) => void
  isInWatchlist: (id: number) => boolean
  setUserLocation: (loc: { lat: number; lon: number } | null) => void
  setMaxDistFromUser: (d: number) => void

  // Auth actions
  setAuth: (token: string, user: AuthUser) => void
  logout: () => void
  setSavedSearches: (searches: SavedSearch[]) => void
  setAuthModalOpen: (open: boolean) => void

  // Map layer toggles
  setMapLayer: (layer: keyof MapLayers, value: boolean) => void

  // Asset subclass actions
  setActiveSubclass: (s: string | null) => void
  setSubclassHeatmapEnabled: (e: boolean) => void
}

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      filters: {
        projectTypes: ['apartments', 'residential', 'land', 'retail'],
        counties: [],
        minScore: 0.5,
        profileName: 'default',
        customWeights: {
          undervaluation: 0.70,
          confidence:     0.30,
          location:       0.00,
          growth:         0.00,
          volume:         0.00,
        },
        cityZone: [],
        maxDistMetro: 0,
        searchText: '',
      },
      selectedProperty: null,
      sidebarOpen: true,
      activeTab: 'map',

      compareA: null,
      compareB: null,

      watchlist: [],

      userLocation: null,
      maxDistFromUser: 0,

      authToken: null,
      authUser: null,
      savedSearches: [],
      authModalOpen: false,

      mapLayers: {
        showMetro: false,
        showCommunes: false,
        showSchools: false,
        showParks: false,
        showBusStops: false,
      },

      activeSubclass: null,
      subclassHeatmapEnabled: false,

      setFilters:          (partial) => set((s) => ({ filters: { ...s.filters, ...partial } })),
      setSelectedProperty: (p)       => set({ selectedProperty: p, activeTab: p ? 'detail' : 'map' }),
      setSidebarOpen:      (open)    => set({ sidebarOpen: open }),
      setActiveTab:        (tab)     => set({ activeTab: tab }),
      setCompareA:         (p)       => set({ compareA: p }),
      setCompareB:         (p)       => set({ compareB: p }),
      setCityZone:         (z)       => set((s) => ({ filters: { ...s.filters, cityZone: z } })),
      setMaxDistMetro:     (d)       => set((s) => ({ filters: { ...s.filters, maxDistMetro: d } })),
      setSearchText:       (t)       => set((s) => ({ filters: { ...s.filters, searchText: t } })),
      setUserLocation:     (loc)     => set({ userLocation: loc }),
      setMaxDistFromUser:  (d)       => set({ maxDistFromUser: d }),

      setAuth:            (token, user) => set({ authToken: token, authUser: user, authModalOpen: false }),
      logout:             ()            => set({ authToken: null, authUser: null, savedSearches: [] }),
      setSavedSearches:   (searches)    => set({ savedSearches: searches }),
      setAuthModalOpen:   (open)        => set({ authModalOpen: open }),
      setMapLayer:        (layer, value) => set((s) => ({ mapLayers: { ...s.mapLayers, [layer]: value } })),

      setActiveSubclass:          (sc) => set({ activeSubclass: sc }),
      setSubclassHeatmapEnabled:  (e)  => set({ subclassHeatmapEnabled: e }),

      addToWatchlist: (p) => set((s) => ({
        watchlist: s.watchlist.some((w) => w.score_id === p.score_id)
          ? s.watchlist
          : [...s.watchlist, p],
      })),
      removeFromWatchlist: (id) => set((s) => ({
        watchlist: s.watchlist.filter((w) => w.score_id !== id),
      })),
      isInWatchlist: (id) => get().watchlist.some((w) => w.score_id === id),
    }),
    {
      name: 're_cl_storage',
      partialize: (state) => ({
        watchlist: state.watchlist,
        authToken: state.authToken,
        authUser: state.authUser,
        mapLayers: state.mapLayers,
      }),
    }
  )
)
