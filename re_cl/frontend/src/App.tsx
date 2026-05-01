import { useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Map, BarChart2, Building2, Info, GitCompareArrows, Bookmark, TrendingUp, DollarSign, User, LogOut } from 'lucide-react'
import { fetchHealth, fetchPropertyById } from './api'
import { useAppStore } from './store'
import { Sidebar } from './components/Sidebar'
import { AuthModal } from './components/AuthModal'
import { DeckMap } from './components/DeckMap'
import { RankingPanel } from './components/RankingPanel'
import { CommunesPanel } from './components/CommunesPanel'
import { DetailPanel } from './components/DetailPanel'
import { ComparatorPanel } from './components/ComparatorPanel'
import { WatchlistPanel } from './components/WatchlistPanel'
import { TrendPanel } from './components/TrendPanel'
import { FinanzasPanel } from './components/FinanzasPanel'
import { OpportunityPanel } from './components/OpportunityPanel'
import { clsx } from 'clsx'

type Tab = 'map' | 'ranking' | 'communes' | 'detail' | 'compare' | 'watchlist' | 'trends' | 'finance' | 'opportunity'

const TABS = [
  { id: 'map',         label: 'Mapa',          icon: Map },
  { id: 'ranking',     label: 'Ranking',       icon: BarChart2 },
  { id: 'communes',    label: 'Comunas',       icon: Building2 },
  { id: 'detail',      label: 'Ficha',         icon: Info },
  { id: 'compare',     label: 'Comparar',      icon: GitCompareArrows },
  { id: 'watchlist',   label: 'Watchlist',     icon: Bookmark },
  { id: 'trends',      label: 'Tendencias',    icon: TrendingUp },
  { id: 'finance',     label: 'Finanzas',      icon: DollarSign },
  { id: 'opportunity', label: 'Oportunidades', icon: TrendingUp },
]

/** Parse window.location.hash into { tab, id } */
function parseHash(): { tab: string; id: number | null } {
  const raw = window.location.hash.replace('#', '')
  const qIdx = raw.indexOf('?')
  if (qIdx === -1) return { tab: raw, id: null }
  const tab = raw.slice(0, qIdx)
  const params = new URLSearchParams(raw.slice(qIdx + 1))
  const idStr = params.get('id')
  return { tab, id: idStr ? parseInt(idStr, 10) : null }
}

export default function App() {
  const { activeTab, setActiveTab, setSelectedProperty, compareA, compareB, setCompareA, setCompareB,
          authUser, authToken, logout, setAuthModalOpen } = useAppStore()
  const { data: health } = useQuery({ queryKey: ['health'], queryFn: fetchHealth })

  // On mount: read hash and navigate accordingly (including deep links to detail)
  useEffect(() => {
    const applyHash = async () => {
      const { tab, id } = parseHash()
      if (tab === 'detail' && id !== null) {
        try {
          const prop = await fetchPropertyById(id)
          setSelectedProperty(prop)
          // setSelectedProperty already sets activeTab to 'detail'
        } catch {
          // property not found — just switch tab
          setActiveTab('detail')
        }
      } else if (tab && TABS.some((t) => t.id === tab)) {
        setActiveTab(tab as Tab)
      }
    }
    applyHash()

    const onHashChange = () => { applyHash() }
    window.addEventListener('hashchange', onHashChange)
    return () => window.removeEventListener('hashchange', onHashChange)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Keep URL in sync when active tab changes
  useEffect(() => {
    const { tab: hashTab, id } = parseHash()
    // Don't overwrite a detail deep-link if we're already on detail with an id
    if (activeTab === 'detail' && id !== null && hashTab === 'detail') return
    if (window.location.hash.replace('#', '').split('?')[0] !== activeTab) {
      window.location.hash = activeTab
    }
  }, [activeTab])

  // When a property is selected, push deep-link hash
  const { selectedProperty } = useAppStore()
  useEffect(() => {
    if (selectedProperty) {
      window.location.hash = `detail?id=${selectedProperty.score_id}`
    }
  }, [selectedProperty])

  const handleTabClick = (tabId: string) => {
    setActiveTab(tabId as Tab)
    window.location.hash = tabId
  }

  return (
    <>
    <AuthModal />
    <div className="flex h-screen w-screen overflow-hidden">
      {/* Left sidebar — filters + profile */}
      <Sidebar />

      {/* Main content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {/* Top nav — desktop only */}
        <nav className="hidden md:flex items-center justify-between bg-gray-900 border-b border-gray-800 px-4 h-10 shrink-0">
          <div className="flex gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => handleTabClick(tab.id)}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-1 rounded text-xs font-medium transition-colors',
                  activeTab === tab.id
                    ? 'bg-blue-600 text-white'
                    : 'text-gray-400 hover:text-white hover:bg-gray-800'
                )}
              >
                <tab.icon size={16} />
                {tab.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-3">
            {health && (
              <span className="text-xs text-gray-600">
                modelo&nbsp;<span className="text-gray-400">{health.model_version}</span>
              </span>
            )}
            {authUser && authToken ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-gray-400 flex items-center gap-1">
                  <User size={12} />{authUser.email}
                </span>
                <button
                  onClick={logout}
                  title="Cerrar sesión"
                  className="text-gray-500 hover:text-red-400 transition-colors"
                >
                  <LogOut size={14} />
                </button>
              </div>
            ) : (
              <button
                onClick={() => setAuthModalOpen(true)}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-800 transition-colors"
              >
                <User size={14} />Entrar
              </button>
            )}
          </div>
        </nav>

        {/* Panel content */}
        <div className="flex-1 overflow-hidden pb-16 md:pb-0">
          {activeTab === 'map' && (
            <div className="flex h-full">
              {/* Deck.gl map takes 2/3 width */}
              <div className="flex-1 relative">
                <DeckMap />
              </div>
              {/* Right sidebar: ranking */}
              <div className="w-72 border-l border-gray-800 overflow-hidden">
                <RankingPanel />
              </div>
            </div>
          )}

          {activeTab === 'ranking' && (
            <div className="h-full overflow-hidden">
              <RankingPanel />
            </div>
          )}

          {activeTab === 'communes' && (
            <div className="h-full overflow-hidden">
              <CommunesPanel />
            </div>
          )}

          {activeTab === 'detail' && (
            <div className="h-full overflow-hidden">
              <DetailPanel />
            </div>
          )}

          {activeTab === 'compare' && (
            <div className="h-full overflow-hidden">
              <ComparatorPanel
                propA={compareA}
                propB={compareB}
                onClearA={() => setCompareA(null)}
                onClearB={() => setCompareB(null)}
              />
            </div>
          )}

          {activeTab === 'watchlist' && (
            <div className="h-full overflow-hidden">
              <WatchlistPanel />
            </div>
          )}

          {activeTab === 'trends' && (
            <div className="h-full overflow-hidden">
              <TrendPanel />
            </div>
          )}

          {activeTab === 'finance' && (
            <div className="h-full overflow-auto">
              <FinanzasPanel />
            </div>
          )}

          {activeTab === 'opportunity' && (
            <div className="h-full overflow-hidden">
              <OpportunityPanel />
            </div>
          )}
        </div>
      </div>

      {/* Mobile bottom tab bar */}
      <div className="md:hidden fixed bottom-0 left-0 right-0 z-50 bg-gray-900 border-t border-gray-700 flex overflow-x-auto">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => handleTabClick(tab.id)}
            className={`flex-shrink-0 flex flex-col items-center px-4 py-2 text-xs ${
              activeTab === tab.id ? 'text-blue-400 border-t-2 border-blue-400' : 'text-gray-500'
            }`}
          >
            <tab.icon size={18} />
            <span className="mt-0.5">{tab.label}</span>
          </button>
        ))}
      </div>
    </div>
    </>
  )
}
