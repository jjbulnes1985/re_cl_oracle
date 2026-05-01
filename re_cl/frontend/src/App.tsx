/**
 * App.tsx — punto de entrada simplificado.
 * El sistema de 9 tabs fue retirado en favor de HomeShell (vista única).
 *
 * Los componentes legacy se preservan pero no están activos:
 *   DeckMap.tsx, RankingPanel.tsx, CommunesPanel.tsx, DetailPanel.tsx,
 *   ComparatorPanel.tsx, WatchlistPanel.tsx, TrendPanel.tsx, FinanzasPanel.tsx,
 *   OpportunityPanel.tsx, Sidebar.tsx
 */

import { HomeShell } from './components/HomeShell'

export default function App() {
  return <HomeShell />
}
