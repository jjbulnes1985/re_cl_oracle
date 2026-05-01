# Master Plan — RE_CL como motor institucional de oportunidades

> **Diseño Opus, ejecución Sonnet.** Documento maestro que integra el rediseño del frontend con metodología Geltner, prácticas de la industria y arquitectura multi-agente para razonamiento distribuido.

---

## 1. Tres marcos integrados

### 1.1 Geltner — fundamentos institucionales

David Geltner, *Commercial Real Estate Analysis and Investments* (3rd Ed). El libro establece que **toda valoración de activo inmobiliario** descansa en tres pilares:

1. **Income Approach** — DCF: NOI proyectado descontado a tasa de descuento adecuada al riesgo. Cap rate inverso (NOI ÷ cap rate) como atajo.
2. **Sales Comparison Approach** — comparables ajustados por superficie, antigüedad, ubicación y tiempo desde venta.
3. **Cost Approach** — costo de reposición ajustado por depreciación + valor del terreno.

**Para el motor de oportunidades**, Geltner exige:
- Banda de valor (low-mid-high), nunca punto único.
- Distinción clara entre **return going-in** (cap rate al momento de compra) y **total return** (incluye apreciación).
- Análisis de sensibilidad obligatorio cuando el cap rate es proxy/no validado.
- Riesgo expresado en **bps de spread** sobre tasa libre de riesgo, no como "alto/medio/bajo".

### 1.2 Industria — qué usan Colliers, CBRE, JLL, Tinsa

Los reportes trimestrales de los grandes:
- **Cap rates por uso y zona** (oficina A+, retail strip, gas station, industrial)
- **Vacancia** y absorción
- **Yield spread** vs bono soberano 10y (Chile: BTU 10y como benchmark)
- **Rent growth** trailing 12m
- **Construction pipeline** (proyectos en obra que afectarán oferta)

**Para RE_CL**: el frontend debe mostrar al menos **cap rate referencial + rent growth comuna + yield spread vs BTU 10y**. Estos tres datos son el lenguaje de cualquier inversionista institucional.

### 1.3 Operadores chilenos — qué priorizan

Inversionistas residenciales chilenos:
- **UF/m²** como métrica universal (no CLP)
- **Comparable a 1 año** en la misma comuna y tipología
- **Plusvalía proyectada** (ya sea histórica anualizada o pipeline-driven)
- **Liquidez** — días promedio en mercado para esa comuna+tipo
- **Rendimiento bruto** de arriendo (12 × renta mensual ÷ precio venta)
- **Rol SII** y datos catastrales (verificación legal)

---

## 2. Arquitectura multi-agente

El motor RE_CL se piensa como **6 agentes especializados** que convergen a una única decisión:

```
                      ┌─────────────────────┐
                      │ ORCHESTRATOR (UI)   │
                      │ "una pregunta"      │
                      └──────────┬──────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ A1: VALUATION   │  │ A2: DEMAND      │  │ A3: RISK        │
│ Geltner triangle│  │ Demographic +   │  │ Regulatory +    │
│ DCF + comps +   │  │ commune dynamics│  │ liquidity +     │
│ cost            │  │                 │  │ environmental   │
└─────────────────┘  └─────────────────┘  └─────────────────┘
          │                      │                      │
          └──────────────────────┼──────────────────────┘
                                 ▼
                      ┌─────────────────────┐
                      │ A4: SCORE FUSION    │
                      │ Weighted by profile │
                      │ (rent/flip/develop) │
                      └──────────┬──────────┘
                                 │
          ┌──────────────────────┼──────────────────────┐
          ▼                      ▼                      ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│ A5: NARRATIVE   │  │ A6: MONITORING  │  │ A7: COMPARABLES │
│ Frase humana    │  │ Drift detection │  │ Side-by-side    │
│ por candidato   │  │ + alertas       │  │ ranking         │
└─────────────────┘  └─────────────────┘  └─────────────────┘
                                 │
                                 ▼
                      ┌─────────────────────┐
                      │ USER VIEWPORT       │
                      │ "una decisión"      │
                      └─────────────────────┘
```

**Hoy cubrimos:** A1 (valuation engine), A2 (demand vía OSM), A3 (placeholder), A4 (score fusion via investor_profile), A7 (ComparatorOverlay).

**Pendientes:** A5 (narrativa enriquecida desde backend), A6 (monitoring + alertas), A3 expandido (PRC + ambiental).

---

## 3. Criterios parametrizables

### 3.1 Escala fase 1: RM Chile

| Dimensión | Variables | Source |
|-----------|-----------|--------|
| Geográfico | comuna (40), zona (4: norte/sur/este/oeste), bbox | INE + scraper RM |
| Tipológico | apartment, house, land, retail, office, warehouse, industrial | property_types catalog |
| Comercial overlay | gas_station, pharmacy, supermarket, bank_branch, clinic, restaurant | competitors OSM |
| Financiero | precio UF (rango), m² (rango), cap rate target, hold period | inputs UI |
| Score | undervaluation, location, growth, yield, redevelopment, liquidity | scoring_profiles |
| Tiempo | trailing 12m / 24m / all-time | inscription_date |

### 3.2 Escala fase 2: Chile entero

Para extender el motor al país:
- Cambiar bbox de RM a bbox de Chile completo
- Agregar tabla `region_polygons` (16 regiones)
- Agregar dimensión `region_code` a `opportunity.candidates`
- Re-train del modelo XGBoost con datos nacionales
- Adaptar comparables zonales (radio amplio en zonas rurales)

**Datos requeridos:** CBR nacional (no solo RM), DI fuera de RM (verificar disponibilidad), OSM Chile completo.

---

## 4. Frontend — wireframe institucional

```
┌─────────────────────────────────────────────────────────────┐
│ RE_CL · Buscando: arrendar · 3.000 UF · Ñuñoa, Providencia │
│                                          ♥ 3   ⚙           │
├──────────────────────┬──────────────────────────────────────┤
│                      │  Top 10 oportunidades                  │
│                      │  ──────────────────────                │
│                      │  #1  Depto Ñuñoa · 2.450 UF           │
│                      │      ★★★★★ Excelente                  │
│                      │      ~7,2% rendimiento anual           │
│                      │                                        │
│      MAPA            │  #2  Depto Providencia · 3.120 UF     │
│      Pins por score  │      ★★★★☆ Muy bueno                  │
│      Toggle layers:  │      ~6,8% rendimiento anual           │
│      [Heatmap        │                                        │
│       Comunas]       │  ... lazy load                         │
│      [Metro]         │                                        │
│      [Colegios]      │  ──────────────────────                │
│      [Parques]       │  Filtros activos                       │
│      [Buses]         │  · arrendar  · 2k–4k UF                │
│                      │  · Ñuñoa, Providencia                  │
│                      │  [Editar]  [Borrar]                    │
└──────────────────────┴──────────────────────────────────────┘

Click pin → Bottom sheet drawer:

┌──────────────────────────────────────────────────────────────┐
│ Av. Pajaritos 5432, Maipú · 65 m² · 2D+1B · 2.450 UF        │
│ ★★★★★  Excelente oportunidad                                  │
│                                                                │
│ "14% bajo el precio promedio de la comuna y rendimiento        │
│  estimado de 7,2% anual. Plusvalía proyectada 18% en 5 años." │
│                                                                │
│ ┌───────────────┬────────────────┬──────────────────────────┐ │
│ │ Si la arriendas│ Si la vendes  │ Tendencia precio comuna  │ │
│ │ ~$580k/mes     │ +18% en 5 a.  │ [chart]                  │ │
│ │ 7,2% anual     │ Total: 13.5%/a│                          │ │
│ └───────────────┴────────────────┴──────────────────────────┘ │
│                                                                │
│ ⚠ Antes de comprar:                                            │
│   ☐ Verificar uso permitido (DOM Maipú)                        │
│   ☐ Solicitar cert. hipotecas (CBR)                            │
│   ☐ Tasación independiente                                     │
│                                                                │
│ [♥ Guardar]  [⇄ Comparar]  [Ver más detalles ▼]               │
│                                                                │
│ ▼ Más detalles (expandido):                                    │
│   - Simulador retornos (3 inputs: hold period, pie %, tasa)   │
│   - Tabla 5 comparables últimas ventas                         │
│   - Modo experto: score detallado, SHAP top-3, profile        │
└──────────────────────────────────────────────────────────────┘
```

---

## 5. Plan de ejecución consolidado

### Fase 0 — Discovery ✓ (2026-05-01)
- API `/opportunity/candidates` valida campos: id, lat/lng, opportunity_score, estimated_uf, p25/p75, drivers, max_payable_uf, valuation_confidence, is_eriazo
- 276,622 candidatos con score≥0.5 disponibles
- Mapping objetivo → use_case + investor_profile definido

### Fase 1 — Cimientos del nuevo Home
- HomeShell (layout único)
- OnboardingFlow (3 pantallas)
- ObjectiveSelector + BudgetSlider + ZoneChips
- DeckMap migrado a `/opportunity/candidates`

### Fase 2 — Funcionalidad central
- TopOpportunitiesRail (sticky lateral)
- PropertyDrawer (bottom sheet)
- Tres tarjetas: Arrendar / Vender / Tendencia
- Watchlist persist localStorage + /searches

### Fase 3 — Funcionalidad ampliada
- QuickReturnSimulator (Geltner-grade DCF embebido)
- ComparatorOverlay
- HeatmapToggle + CommuneInsight
- WatchlistDrawer

### Fase 4 — Pulido
- EmptyStateCoach (sugerencias inteligentes)
- ExpertModeToggle (SHAP, scores, profiles)
- i18n setup (default es-CL)
- Mobile responsive

### Fase 5 — Cutover
- Eliminar tabs viejos
- Eliminar paneles obsoletos
- Reducir bundle

---

## 6. Mapping objetivo del usuario → schema técnico

| UI label | use_case | investor_profile | filtros default |
|----------|----------|------------------|-----------------|
| Arrendar | as_is | income | residencial, todas comunas |
| Revender 3-5 años | as_is | growth | residencial, plusvalía alta |
| Desarrollar terreno | as_is | redevelopment | land, eriazo=TRUE |
| Solo explorando | as_is | value | sin filtros |
| Operar negocio | varies | operator | comerciales (gas/farma/super/etc) |

---

## 7. Información de Geltner aplicada al simulador

El **QuickReturnSimulator** embebido en el drawer recibe 3 inputs del usuario:
1. **Hold period** (años) — horizonte de inversión
2. **Pie %** — fracción del precio en cash (default 20%)
3. **Tasa hipoteca** (anual %) — costo de financiamiento (default tasa promedio CMF)

Y calcula con la fórmula Geltner-DCF:

```
Año 0: Cash flow = -(precio × pie%)  ← inversión inicial
Año 1..N-1: Cash flow = NOI - service_deuda
Año N: Cash flow = NOI - service_deuda + (precio_proyectado - saldo_deuda)

NOI = renta_estimada × 12 × (1 - vacancia) - gastos_admin - contribuciones
renta_estimada = AVG(comparables_arriendo_zona) × m²
gastos_admin = 0.10 × NOI_bruto  (default Geltner 10%)
contribuciones = 0.012 × avaluo_fiscal × 4  (4 cuotas anuales)

precio_proyectado = precio_actual × (1 + growth_anual)^N
growth_anual = AVG(rent_growth_comuna_5y)

IRR = solve(NPV = 0)
ROI total = (CF_total - inversion_inicial) / inversion_inicial
```

**Output al usuario:** IRR anualizado + ROI total + payback period. Banda con sensibilidad al ±100 bps de growth.

---

## 8. Seguridad e instituciones

Aplicando patrones del catálogo tododeia:
- **Row-Level Security en PostgreSQL** para datos por usuario (saved_searches ya existe).
- **JWT short-lived** + refresh token pattern (ya implementado en /auth/refresh).
- **Rate limit per-user** (ya implementado en stale_data middleware).
- **Sin logs de PII**: emails y RUTs nunca en logs.
- **Auditoría de queries**: log de búsquedas guardadas con timestamp.

---

## 9. Riesgos institucionales

| Riesgo | Mitigación |
|--------|-----------|
| Frase narrativa generada en frontend pierde fidelidad técnica | Mover generación al backend (A5 agent) en próxima iteración |
| Cap rate del simulador contradice valor mostrado en card | Una sola fuente de verdad por tarjeta. Card usa cap_rate central, simulador permite ajustar |
| Onboarding > 30s | Botón "Saltar" desde pantalla 1, defaults inteligentes |
| Pérdida de IDs en watchlist legacy | Migrar `model_scores.clean_id` ↔ `opportunity.candidates.id` antes del cutover |

---

*Master plan generado con Opus 4.7 · 2026-05-01 · v1.0 · Geltner + Multi-agente + Parametrizable RM→Chile*
