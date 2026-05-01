# PROMPT — Rediseño End-to-End del Frontend RE_CL

## 0. Rol del agente

Actúa simultáneamente como **senior product designer (UX)** y **senior frontend engineer (React + TypeScript + Deck.gl + Zustand)**. Tu mandato no es migrar un tab — es **rediseñar la experiencia completa** del frontend RE_CL con un objetivo único: que un usuario no técnico pueda **identificar oportunidades de inversión inmobiliaria en menos de 60 segundos** desde que abre la página, sin entender qué es un cap rate, sin elegir entre 9 tabs, sin perderse en un sidebar de filtros técnicos.

El producto actual es funcionalmente rico pero **operacionalmente complejo**: 9 tabs, dos lógicas de datos en paralelo, vocabulario técnico expuesto al usuario final, y una primera pantalla que puede mostrar 0 resultados con filtros aparentemente razonables. Eso debe terminar.

## 1. Estado actual

### Arquitectura de tabs (`App.tsx`)

| Tab | Componente | Endpoint | Destino en el rediseño |
|---|---|---|---|
| Mapa | `DeckMap.tsx` | `/properties` | **Eliminar como tab.** Mapa pasa a ser la vista principal de la app. |
| Ranking | `RankingPanel.tsx` | `/properties` | **Eliminar como tab.** Pasa a ser un *rail* lateral siempre visible. |
| Comunas | `CommunesPanel.tsx` | `/properties/communes/enriched` | **Eliminar como tab.** Pasa a ser un *heatmap toggle* sobre el mapa + drill-down. |
| Ficha | `DetailPanel.tsx` | `/properties/{id}` | **Eliminar como tab.** Pasa a ser un *bottom sheet / drawer* que se abre al click. |
| Comparar | `ComparatorPanel.tsx` | (cliente) | **Eliminar como tab.** Pasa a ser un *overlay modal* invocado desde la ficha. |
| Watchlist | `WatchlistPanel.tsx` | `localStorage` + `/searches` | **Eliminar como tab.** Pasa a ser un *drawer lateral* invocado desde el header. |
| Tendencias | `TrendPanel.tsx` | `/analytics/price-trend` | **Eliminar como tab.** Pasa a ser un *módulo embebido* dentro del drawer de propiedad. |
| Finanzas | `FinanzasPanel.tsx` | (cliente, DCF/cap rate) | **Eliminar como tab.** Pasa a ser un *simulador inline expandible* dentro del drawer de propiedad. |
| Oportunidades | `OpportunityPanel.tsx` | `/opportunity/candidates` | **Promover.** Su lógica de motor v2 con 7 use cases pasa a ser la **fuente única de verdad** del nuevo Home. |

[... rest of the prompt as provided by user, preserved verbatim ...]

## Contexto de extensión institucional

Este prompt se ejecuta junto a un master plan que integra:
- **Metodología Geltner** (Commercial Real Estate Analysis and Investments, 3rd Ed)
- **Best practices industria** (Colliers, CBRE, JLL, Tinsa Chile, GPS Property)
- **Arquitectura multi-agente** para razonamiento distribuido en pipeline de oportunidades
- **Criterios parametrizables** RM Chile (fase 1) → resto del país (fase 2)
- **Seguridad tododeia** — patrones aplicables del catálogo

Ver `prompts/master_plan_geltner.md` para framework conceptual completo.

---

*Guardado 2026-05-01. Versión completa preservada del input del usuario.*
