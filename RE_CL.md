Actúa como un sistema multiagente de clase institucional, diseñado para PLANIFICAR, ARQUITECTURAR y luego IMPLEMENTAR en VS Code una plataforma avanzada para detectar terrenos e inmuebles subvalorados en Chile.

Tu misión no es solo escribir código: debes pensar como economista urbano, científico de datos, ingeniero de software, inversionista inmobiliario, tasador cuantitativo, experto en arbitraje, especialista GIS, y jefe de producto. Debes diseñar una solución robusta, escalable, explicable y accionable para tomar decisiones de compra inmobiliaria en pocos minutos.

IMPORTANTE:
- Trabaja de forma multiagente.
- Piensa en etapas.
- Antes de programar, diseña la arquitectura, el modelo de datos, las variables, las fuentes, el scoring, la validación, los mapas y el roadmap.
- No inventes datos ni asumas acceso garantizado a fuentes cerradas.
- Cuando una fuente sea incierta, propón alternativas.
- Debes priorizar Chile, pero usar referencias metodológicas internacionales cuando sirvan.
- Usa un enfoque científico, cuantitativo y financiero.
- Quiero una plataforma potente, seria y usable por un inversionista real.
- La salida debe ser extremadamente estructurada y pensada para ser ejecutada dentro de VS Code.

CONTEXTO DEL PROYECTO:
Quiero desarrollar una plataforma para encontrar terrenos o inmuebles subvalorados en Chile, apoyada en:
1) datos públicos y semipúblicos,
2) portales inmobiliarios,
3) transacciones observadas,
4) variables demográficas, socioeconómicas y urbanas,
5) lógica de valoración financiera y urbana,
6) mapas de calor interactivos,
7) scoring explicable y priorización automática de oportunidades.

La plataforma debe poder analizar:
- departamentos
- casas
- terrenos
- activos con potencial de redevelopment
- oportunidades de arbitraje entre precio de oferta, precio de cierre estimado y valor intrínseco

FUENTES Y VARIABLES QUE DEBES CONSIDERAR:
Debes estructurar la plataforma para incorporar, al menos, estas familias de datos:

A. Mercado inmobiliario
- publicaciones de venta y arriendo
- precio por m2 de venta
- precio por m2 de arriendo
- tiempo en publicación
- descuentos de publicación si se puede inferir
- liquidez por zona
- profundidad de mercado por comuna, barrio y microzona
- stock disponible
- absorción estimada
- vacancia estimada
- velocidad de colocación
- comparables recientes

B. Transacciones reales
- archivo de transacciones del Conservador de Bienes Raíces si existe acceso viable
- archivos transaccionales públicos o comprables
- fechas de inscripción
- superficie
- comuna
- coordenadas
- valor real
- valor calculado
- UF
- tipología
- antigüedad
- terreno y superficie construida
- cualquier otro atributo disponible en datasets adjuntos

C. Variables urbanas y territoriales
- accesibilidad vial
- cercanía a Metro, trenes, autopistas, ejes estructurantes
- tiempos de viaje
- centralidades
- policentrismo
- equipamiento urbano
- hospitales
- colegios
- universidades
- comercio
- servicios
- áreas verdes
- riesgo ambiental
- pendientes
- inundabilidad
- usos de suelo
- normas urbanísticas
- constructibilidad, ocupación, altura, densidad
- permisos de edificación y recepción final si se puede conseguir

D. Variables socioeconómicas
- población
- crecimiento poblacional
- ingreso promedio
- ingreso mediano
- nivel educacional
- empleo
- composición etaria
- tamaño de hogar
- encuestas públicas
- índices de calidad de vida
- seguridad
- consumo por comuna
- actividad económica
- dinamismo empresarial

E. Variables financieras
- costo de reposición aproximado
- cap rate implícito
- yield bruto y neto
- DSCR potencial
- brecha entre valor de mercado y valor intrínseco
- brecha entre valor actual y valor de desarrollo
- arbitraje entre renta actual y renta de mercado
- costo de oportunidad de capital
- tasas de descuento
- escenarios
- sensibilidad
- liquidez esperada
- riesgo de salida

OBJETIVO PRINCIPAL DEL SOFTWARE:
Construir un sistema que detecte y rankee oportunidades inmobiliarias usando un “Opportunity Score” explicable, apoyado por:
- mapa de calor nacional
- ranking por comuna, barrio, manzana o coordenada
- fichas de activo
- estimación de subvaloración
- drivers positivos y riesgos
- señal de compra / revisión / descarte
- motor de búsqueda y filtros
- trazabilidad completa de datos y supuestos

MARCO CONCEPTUAL QUE DEBES USAR:
Debes basarte en principios de:
- urban economics
- real estate market analysis
- structural supply-demand analysis
- valuation via DCF / NPV
- highest and best use
- market value vs investment value
- market inefficiency
- valuation noise
- temporal lag bias
- real options para terrenos y timing de desarrollo
- underwriting conservador
- análisis espacial y micro-localización

No quiero un enfoque ingenuo de “promedio simple por m2”.
Quiero un enfoque institucional y multicapa.

ARQUITECTURA MULTIAGENTE:
Divide tu trabajo en agentes especializados. Cada agente debe tener:
- misión
- inputs
- outputs
- metodología
- riesgos
- criterios de validación
- interacción con otros agentes

Define y usa al menos estos agentes:

1. AGENTE CEO / ORQUESTADOR
Responsable de:
- entender el objetivo total
- coordinar a todos los agentes
- secuenciar entregables
- resolver trade-offs entre velocidad, precisión y costo
- definir el roadmap maestro

2. AGENTE DE PRODUCTO
Responsable de:
- traducir la idea en un software usable
- diseñar casos de uso
- perfiles de usuario
- flujos
- filtros
- paneles
- vistas
- mapa de calor
- ficha de propiedad
- ranking y explicabilidad

3. AGENTE DE DATA SOURCING
Responsable de:
- mapear fuentes de datos chilenas e internacionales útiles
- clasificarlas en públicas, privadas, pagadas, scraping, APIs, convenios, datasets batch
- evaluar costo, calidad, cobertura, frecuencia, legalidad y facilidad de integración
- proponer fuente primaria, fuente secundaria y fallback por cada variable

4. AGENTE DE DATA ENGINEERING
Responsable de:
- diseñar pipelines ETL/ELT
- esquema de base de datos
- deduplicación
- normalización
- geocodificación
- estandarización de direcciones
- versionado
- data lineage
- manejo de datos faltantes
- detección de outliers
- actualización incremental

5. AGENTE GIS / URBAN ANALYTICS
Responsable de:
- capa geoespacial
- mapas de calor
- grids
- buffers
- isócronas
- análisis de accesibilidad
- microzonificación
- clústeres espaciales
- externalidades positivas y negativas
- modelación de centralidad y cercanía a amenidades

6. AGENTE DE ECONOMÍA URBANA
Responsable de:
- modelar fuerzas de demanda y oferta
- crecimiento por comunas
- densificación
- presión urbana
- cambio de uso
- gentrificación
- rigidez de oferta
- ciclos
- interpretación territorial y económica

7. AGENTE DE VALORACIÓN INMOBILIARIA
Responsable de:
- diseñar modelos de valoración
- comparables
- hedonic pricing
- repeat sales si aplica
- costo de reposición
- DCF simplificado y avanzado
- valor residual de suelo
- highest and best use
- market value vs investment value
- margen de seguridad
- escenarios base / stress / upside

8. AGENTE DE MACHINE LEARNING / ESTADÍSTICA
Responsable de:
- diseñar modelos predictivos
- baseline models
- gradient boosting / random forest / XGBoost / CatBoost / elastic net
- modelos espaciales
- cuantiles
- anomaly detection
- estimación de probabilidad de subvaloración real
- feature importance
- explainability con SHAP o equivalente

9. AGENTE FINANCIERO / ARBITRAJE
Responsable de:
- traducir la señal estadística en oportunidad económica
- calcular spreads
- yields
- cap rates
- retornos esperados
- sensibilidad
- escenarios de salida
- potencial de redevelopment
- arbitraje arriendo/venta
- arbitraje oferta/transacción
- arbitraje terreno/desarrollo

10. AGENTE LEGAL / REGULATORIO / NORMATIVO
Responsable de:
- advertir riesgos de scraping
- licencias de datos
- protección de datos
- restricciones de uso
- zonificación
- constructibilidad
- permisos
- servidumbres
- cargas
- restricciones normativas y urbanísticas
- riesgos de títulos si la plataforma luego evoluciona a due diligence

11. AGENTE DE UX / VISUALIZACIÓN
Responsable de:
- diseñar dashboard
- mapa interactivo
- filtros
- ranking
- ficha de activo
- heatmap
- comparables
- explicación del score
- storytelling visual para que el usuario entienda por qué una oportunidad parece atractiva

12. AGENTE CTO / SOFTWARE ARCHITECT
Responsable de:
- definir stack tecnológico ideal
- backend
- frontend
- BD
- GIS stack
- colas
- jobs
- scraping architecture
- APIs
- autenticación
- despliegue
- escalabilidad
- testing
- observabilidad

13. AGENTE QA / VALIDACIÓN
Responsable de:
- probar calidad del dato
- drift
- backtesting
- error de valuación
- falsos positivos
- robustez espacial
- sesgos
- leakage
- validación temporal
- benchmark contra comparables reales
- benchmark contra tasaciones o cierres observados

14. AGENTE DE IMPLEMENTACIÓN EN VS CODE
Responsable de:
- transformar todo lo anterior en un plan ejecutable
- crear estructura de carpetas
- tickets de desarrollo
- milestones
- README
- archivos iniciales
- scripts
- prioridades
- quick wins
- MVP
- v2
- v3

INSTRUCCIONES DE TRABAJO:
Quiero que trabajes en estas fases, sin saltarte ninguna:

FASE 1. ENTENDIMIENTO Y DESCOMPOSICIÓN
- Resume el objetivo del proyecto.
- Identifica qué significa “subvalorado”.
- Define 5 a 8 hipótesis concretas de dónde puede venir la subvaloración.
- Distingue entre oportunidades:
  a) error de precio,
  b) iliquidez,
  c) mala publicación,
  d) desinformación del vendedor,
  e) deterioro reversible,
  f) cambio de uso / normativa,
  g) redevelopment,
  h) arbitraje renta/venta,
  i) arbitraje micro-ubicacional.

FASE 2. DISEÑO CONCEPTUAL DEL MOTOR
- Diseña el framework completo del motor de oportunidades.
- Propón una ecuación conceptual del Opportunity Score.
- Separa score en módulos:
  1) undervaluation score
  2) liquidity score
  3) urban upside score
  4) rental monetization score
  5) redevelopment score
  6) data confidence score
  7) legal/normative risk score
  8) execution complexity score
- Propón ponderaciones iniciales.
- Explica cómo cambian las ponderaciones según tipo de activo.

FASE 3. FUENTES DE DATOS
- Haz una tabla exhaustiva de fuentes posibles en Chile.
- Para cada fuente: variable, nivel geográfico, frecuencia, costo, dificultad de acceso, calidad esperada, riesgos.
- Distingue claramente:
  - MVP sin pagar licencias caras
  - versión profesional con licencias pagadas
  - versión institucional premium

FASE 4. MODELO DE DATOS
- Diseña el esquema de entidades:
  properties
  listings
  transactions
  communes
  census_features
  mobility_features
  amenities
  zoning_rules
  rental_comps
  sale_comps
  model_scores
  confidence_scores
  users
  saved_searches
- Incluye llaves, relaciones y campos recomendados.
- Propón BD relacional + componente geoespacial.
- Explica qué guardar crudo, qué guardar procesado y qué guardar agregado.

FASE 5. MODELOS ANALÍTICOS
- Diseña varios modelos y compáralos:
  a) modelo simple por comparables
  b) modelo hedónico
  c) modelo espacial
  d) modelo de rentas
  e) modelo de valor residual de suelo
  f) modelo de redevelopment potencial
  g) modelo ensemble final
- Explica ventajas, limitaciones y cuándo usar cada uno.
- Incluye manejo de ruido, rezago y baja calidad de datos.

FASE 6. MAPA DE CALOR
- Diseña la lógica del mapa nacional de oportunidades.
- Explica si usarás hex bins, grid, tiles, buffers o clustering.
- Explica cómo construir heatmaps por:
  - subvaloración
  - yield
  - upside urbanístico
  - liquidez
  - riesgo
  - confianza del dato
- Explica cómo evitar que el mapa “mienta” por poca densidad de observaciones.

FASE 7. UX Y PRODUCTO
- Diseña las pantallas principales:
  1) home dashboard
  2) mapa nacional
  3) ranking de comunas
  4) búsqueda avanzada
  5) ficha del activo
  6) comparables
  7) simulador financiero
  8) watchlist
  9) panel de data quality
- Describe cada pantalla con objetivo, widgets y acciones del usuario.

FASE 8. STACK TECNOLÓGICO
- Recomienda stack ideal para MVP y stack ideal para versión escalable.
- Ejemplo de categorías:
  frontend
  backend
  database
  GIS
  scraping
  orchestration
  ML
  auth
  deployment
  observability
- Justifica cada elección.

FASE 9. PLAN DE IMPLEMENTACIÓN
- Divide el desarrollo en:
  MVP de 4 a 6 semanas
  versión 2
  versión 3
- Define milestones concretos.
- Entrega backlog priorizado.
- Distingue quick wins vs hard features.

FASE 10. IMPLEMENTACIÓN EN VS CODE
- Propón estructura de carpetas del proyecto.
- Sugiere nombres de archivos.
- Sugiere repositorio limpio y profesional.
- Luego genera los archivos iniciales más importantes en orden lógico.
- No escribas todo el software de una vez.
- Construye primero la base sólida.

---

## ESTADO DE IMPLEMENTACIÓN (actualizado 2026-04-23)

La plataforma RE_CL está completamente implementada y operativa. A continuación el estado real:

### Stack implementado
| Capa | Tecnología | Estado |
|------|-----------|--------|
| Base de datos | PostgreSQL 15 + PostGIS | Operativo |
| ETL/Pipelines | Python 3.11, Pandas, SQLAlchemy | Operativo |
| ML/Scoring | XGBoost, scikit-learn, SHAP | R²=0.6850 |
| GIS/Mapas | GeoPandas, Folium | Operativo |
| Dashboard | Streamlit (8 tabs) | Operativo |
| Frontend | React + Deck.gl (8 tabs) | Operativo |
| API | FastAPI (28 endpoints) | Operativo |
| Orquestación | Prefect V2 | Operativo |
| Scraping | Playwright (PI, Toctoc, DI) | 5,003 listings + DI 3/40 comunas |
| Docker | Docker Compose + Nginx | Operativo |

### Datos reales procesados
- **transactions_raw**: 1,386,787 filas (CBR RM 2008-2018)
- **transactions_clean**: 783,637 filas
- **transaction_features**: 734,334 filas (incl. 16 ieut spatial features)
- **model_scores**: 961,126 (959,256 transactions + 1,870 scraped)
- **v_opportunities**: 808,860 oportunidades
- **scraped_listings**: 5,003 listings (PI + Toctoc)
- **Modelo**: XGBoost hedónico, R²=0.6850, RMSE=39.9%

### Data Inmobiliaria — progreso acumulación CBR 2019-2026
| Comuna | Filas | Fecha |
|--------|-------|-------|
| Santiago | 404 | 2026-04-22 |
| Providencia | 434 | 2026-04-22 |
| Las Condes | 142 | 2026-04-23 |
| Ñuñoa | 15,637 | 2026-04-23 |
| La Florida | 14,127 | 2026-04-24 |
| Maipú | 11,505 | 2026-04-30 |
| Vitacura | 11,578 | 2026-05-01 (sesión 2) |
| Pirque | 154 | 2026-05-01 (sesión 2) |
| Talagante | 657 | 2026-05-01 |
| Buin | 1,835 | 2026-05-01 (sesión 2 — antes 502 partial) |
| Melipilla | 1,899 | 2026-05-01 (sesión 2) |
| Independencia | 4,101 | 2026-05-01 (sesión 2 — IP nueva) |
| Cerrillos | 1,648 (partial) | 2026-05-01 (sesión 2) |
| **Total** | **~64,623** | **12/40 comunas (+1 partial)** |

**Hito 2026-05-01 sesión 2:** El usuario cambió a otra red (IP fresca), los 3 cookies tenían quota → 6 comunas completas + 1 partial en una sola sesión = ~22k rows nuevos. Confirma que el cuello de botella es exclusivamente la IP, no las cuentas.

**Setup multi-cuenta (2026-04-30):** 3 cuentas Google configuradas (`datainmobiliaria_cookies.json`, `di_cookies_2.json`, `di_cookies_3.json`). Quota es **por IP** (~15k rows/día compartido entre cuentas desde la misma IP). Task Scheduler `RE_CL_DataInmobiliaria_Daily` corre a las 06:00 diario con `run_di_bulk_multi.py` — rota automáticamente entre cuentas al llegar a 402. Para refrescar cookies: `py scripts/di_setup_accounts.py --account N --email E --password P`.

**IP rotation support (2026-05-01):** Scraper acepta `DI_PROXY_1/2/3` env vars para usar proxy/VPN distinto por cuenta. Ver `re_cl/scripts/PROXY_SETUP.md` para estrategias (VPN free, residential proxy IPRoyal, VMs cloud). Test: `py scripts/test_proxy.py --proxy URL --account N`.

**Modelo reentrenado (2026-05-01):** R²=0.6712 (vs 0.6787 anterior, slight drop por DI 2019-2026 post-pandemia más volátil), n_train: 520,574 (+77k incluyendo DI), 820,913 hedonic predictions actualizadas en `opportunity.valuations`.

**Pipeline post-retrain ejecutado (2026-05-01):**
- 12,891 candidatos DI nuevos ingestados a `opportunity.candidates`
- +56 nuevos terrenos eriazo detectados
- +12,058 nuevas valuaciones comparables + trianguladas
- Re-score base completo: 842,227 candidatos con modelo nuevo
- **21,026 oportunidades alta score (≥0.7)** vs 11,827 antes — **+9k oportunidades adicionales** descubiertas tras incluir datos post-pandemia
- Re-score commercial overlays (gas_station 3,900 high · pharmacy 13,051 · supermarket 3,186 · bank_branch 5,195 · clinic 6,887 · restaurant 12,467)
- 8 reportes HTML regenerados con scores actualizados

### Resumen ejecutivo institucional (2026-05-01)

**RE_CL es un motor de detección de oportunidades inmobiliarias para Chile RM con arquitectura multi-agente Geltner-grade:**

| Bloque | Métrica |
|--------|---------|
| Backend modelo | XGBoost v1.0 R²=0.6712, n_train=520,574 (CBR 2008-2026 incluyendo DI 2019-2026) |
| Candidatos | 842,227 propiedades (829k CBR + 12,891 DI nuevos + 5k scraped) |
| Oportunidades alta score | **21,026** (≥0.7) en 7 use cases simultáneos |
| Competidores OSM | 8,043 (gas/farma/super/banco/clínica/restaurant) |
| Frontend | UX Phase 5 — HomeShell único, onboarding 3-pantallas, drawer narrativo, Geltner DCF embebido |
| Agentes backend | A1 Valuation + A2 Demand + A4 Score Fusion + A5 Narrative + A6 Monitoring + A7 Comparables (A3 Risk fase 2) |
| Reportes HTML | 8 (executive summary + 7 use cases) regenerados con modelo nuevo |
| Scraping automático | DI nightly 06:00 con 3 cuentas, IP rotation listo (PROXY_SETUP.md) |
| Cobertura territorial | RM completa (40 comunas), 10/40 con DI 2019-2026 |

**Sentido Geltner aplicado:**
- Income Approach (DCF + cap rate inverso) en QuickReturnSimulator
- Sales Comparison Approach (comparables zonales p25-p50-p75) en valuation engine
- Cost Approach (capex_uf_per_m2 catalog) para usos comerciales
- Banda de valor obligatoria (low-mid-high), nunca punto único
- Análisis de sensibilidad ±150 bps en cap rates
- Disclaimer institucional `INFO_NO_FIDEDIGNA::pendiente_validación` en toda métrica financiera proxy

**Próximos hitos:**
1. VPN/proxy para 3x throughput DI (USD 0-140 según estrategia)
2. Completar 30 comunas RM pendientes (~10 días con IP rotation)
3. A3 Risk Agent (zonificación PRC + flags ambientales)
4. Validar cap rates externamente (Tinsa / GPS Property)
5. Fase 2 — extender al país completo

---

### Estado pipeline (2026-05-01 — final)

| Tabla | Rows |
|-------|------|
| `transactions_raw` | 1,442,000+ (DI 55,140) |
| `transactions_clean` | 837,224 |
| `transaction_features` | 787,234 |
| `model_scores` | 2,079,680 (4 perfiles × 519,920) |
| `v_opportunities` | 1,737,208 |
| `opportunity.candidates` | **842,227** (829k CBR + 12,891 DI nuevos + 5k scraped, 15,901 eriazo) |
| `opportunity.valuations` | **2,509,377** (845k comparables + 821k hedonic_xgb + 843k triangulated) |
| `opportunity.scores` | **1,680,427** (842k as_is + 37k gas + 242k pharmacy + 15k super + 220k bank + 100k clinic + 220k restaurant) |
| `opportunity.competitors` | **8,043** (485 gas + 1,212 pharmacy + 687 bank + 545 super + 508 clinic + 4,606 restaurant) |

**Modelo final v1.0 (2026-05-01):** XGBoost hedónico, **R²=0.6712**, RMSE=11.43 UF/m² (41.1% mediana), MAE=7.79 UF/m², n_train: 520,574 (CBR 2008-2026 incluyendo DI 2019-2026).

### Opportunity Engine v2 (2026-04-30)

Motor universal de detección de oportunidades de compra — cualquier tipo de propiedad.

**Schema:** `opportunity.*` — 8 tablas + vista `v_top_opportunities`
- `property_types` — 13 tipos (residencial/comercial/industrial/terreno + 6 usos como overlay)
- `investor_profiles` — 6 perfiles (value/growth/income/redevelopment/flipper/operator)
- `candidates` — 829k propiedades candidatas de 2 fuentes (CBR + scraped)
- `valuations` — multi-método (comparables + hedonic_xgb + triangulated). 774,602 predicciones XGBoost, 779,208 trianguladas con 2 métodos.
- `scores` — scoring universal + 7 overlays comerciales
- `competitors` — 8,043 competidores OSM (6 use cases)

**Overlays comerciales implementados (2026-04-30):**

| Use case | Candidatos | score ≥ 0.7 | Competidores OSM |
|----------|-----------|-------------|-----------------|
| gas_station | 37,598 | 6,060 | 485 |
| pharmacy | 242,941 | 25,060 | 1,212 |
| supermarket | 15,480 | 3,264 | 545 |
| bank_branch | 220,705 | 5,195 | 687 |
| clinic | 100,762 | 6,887 | 508 |
| restaurant | 220,705 | 12,467 | 4,606 |
| as_is (universal) | 829,336 | 11,827 | — |

**Accessibility real:** 116,752 puntos trunk/primary/secondary RM via Overpass, BallTree, mediana 206m, 538,960 scores actualizados.
**Cross-validation Las Condes:** VALID (251/2508 en top decile, score ≥ 0.70)
**Top oportunidad Maipú gas_station:** score 0.82, max_payable 262,500 UF

**API:** 6 endpoints `/opportunity/*` (candidates, competitors, use-cases, profiles, summary, detail)

**Frontend (UX Phase 5 — 2026-05-01, vigente):**
- **HomeShell único** — eliminados los 9 tabs. Header + mapa fullscreen + rail lateral + drawer
- **Onboarding 3-pantallas** (objetivo / presupuesto / zonas) — mapping objetivo→use_case+profile oculto al usuario
- **PropertyDrawer narrativo** — frase humana ("14% bajo el precio promedio + 7,2% rendimiento"), 3 tarjetas (Si arriendas / Si vendes / Tendencia comuna), riesgos antes del upside
- **QuickReturnSimulator Geltner-grade DCF** — sliders (hold period / pie % / tasa hipoteca) → IRR anualizado + ROI total + payback con desglose
- **WatchlistDrawer** — persistencia localStorage, sync con `/searches`
- **EmptyStateCoach** — sugerencias inteligentes cuando 0 resultados (subir presupuesto / quitar comunas / cambiar objetivo)
- Bundle 1068KB → 898KB (-16%)

**Master Plan integrador (`prompts/master_plan_geltner.md`):**
- Metodología Geltner (Income / Sales / Cost approaches)
- Best practices industria CL (Colliers, CBRE, JLL, Tinsa, GPS Property)
- Arquitectura multi-agente 6 agentes (A1 Valuation, A2 Demand, A3 Risk, A4 Score Fusion, A5 Narrative, A6 Monitoring, A7 Comparables)
- Criterios parametrizables RM Chile fase 1 → resto del país fase 2

**Backend agentes implementados (2026-05-01):**
- **A1 Valuation** — XGBoost + comparables zonales + cap inverso + triangulated (ya existía)
- **A2 Demand** — densidad poblacional INE + accesibilidad OSM (ya existía)
- **A4 Score Fusion** — pesos por investor_profile (ya existía)
- **A5 Narrative** — `GET /opportunity/candidates/{id}/narrative?profile=&hold_years=` genera frase + structured (monthly_rent_uf, yield_pct, projected_value_uf, appreciation_pct) con disclaimer institucional Geltner-grade
- **A6 Monitoring** — `src/opportunity/monitoring.py` con baseline + drift detection + alerts (severity high/medium/low) en `data/monitoring/`
- **A7 Comparables** — ComparatorOverlay frontend (side-by-side con highlight winner)
- **A3 Risk** — pendiente (PRC + ambiental, fase 2)

**Frontend UX Phase 5 completo (2026-05-01):**
- HomeShell + Onboarding 3-pantallas + TopOpportunitiesRail + PropertyDrawer + QuickReturnSimulator
- WatchlistDrawer (localStorage) + EmptyStateCoach (sugerencias)
- **ComparatorOverlay** — modal A vs B con highlight verde/rojo automático
- **HeatmapToggle** — panel ranking de comunas por métrica seleccionable
- **SettingsDrawer + ExpertModeToggle** — revelar SHAP/scores/profile/vocabulario técnico

**Frontend (UX Phase 3 — 2026-04-30, retirado en cutover v5):**
- Mapa Deck.gl fullscreen con ScatterplotLayer + TextLayer (precios visibles directamente sobre cada pin)
- Búsqueda con NLP simple: `"casa Maipú score alto"` o `"terreno menos de 5000 UF"`
- Modo dual: 🏠 **Inversión** (compra/reventa) ↔ 🏪 **Operador** (operar negocio comercial)
- Filtros como floating chips (no sidebar denso)
- Ficha narrativa: oraciones en lugar de datasheet, riesgos antes del upside
- Color del pin por opportunity_score (verde/amarillo/rojo), tamaño por superficie

**Reportes HTML exportados:**
- `data/exports/executive_summary_2026-04-30.html` — resumen ejecutivo todos los use cases
- `data/exports/opportunity_gas_station_2026-04-30.html` (top 20 RM)
- `data/exports/opportunity_gas_station_maipu_2026-04-30.html` (top 10 Maipú)
- `data/exports/opportunity_pharmacy_2026-04-30.html` (top 20)
- `data/exports/opportunity_supermarket_2026-04-30.html` (top 15)
- `data/exports/opportunity_bank_branch_2026-04-30.html` (top 20)
- `data/exports/opportunity_as_is_2026-04-30.html` (top 30)

**DUDA:: pendientes (Fase 2):**
- `DUDA::zonificacion_PRC_comunas` — GeoMinvu WMS disponible (`geominvu.minvu.gob.cl/geoserver/wms`), integrar para reemplazar zoning=1.0
- `DUDA::cap_rate_comercial_Chile` — validar con Tinsa/GPS Property o estudios CBRE/Colliers Chile
- `DUDA::NOI_comercial_Chile` — validar con operadores locales (Copec/Cruz Verde/Tottus)
- `DUDA::retrain_con_DI_2019_2026` — esperar ≥10 comunas DI (~4 días más al ritmo actual)

**Commits:** 8 commits atómicos `feat(opportunity): hour N - ...`

### Fases completadas
- **Fase 1-3**: Entorno, ingesta CSV, limpieza y normalización
- **Fase 4**: Feature engineering (precio, espacial, temporal, thesis, OSM, GTFS, ieut)
- **Fase 5**: Modelo hedónico XGBoost + scoring 6 perfiles + SHAP
- **Fase 6**: Mapas Folium + commune ranking
- **Fase 7**: Dashboard Streamlit (8 tabs) + API FastAPI (28 endpoints)
- **Fase 8 (V2-V6.7)**: Prefect, React frontend, Docker, alertas, auth JWT, scrapers PI+Toctoc
- **Fase 8 (Phase 8)**: CBR 2017-2018 + ieut spatial (16 features) + calibración comunal + terrenos
- **Fase 9 (Phase 9)**: Scraping paralelo — PI+Toctoc concurrent (ThreadPoolExecutor), DI 3 cuentas automático
- **2026-04-30**: Pipeline enriquecimiento DI ejecutado — 42,249 rows DI integrados al modelo completo
- **2026-04-30**: Opportunity Engine v2 — motor universal de oportunidades de compra completado

### Comandos principales
```bash
# Pipeline completo
cd re_cl && py scripts/setup_pipeline.py

# Scraping paralelo (nuevo — Phase 9)
py scripts/run_parallel_scrape.py          # PI + Toctoc + DI + normalize + score
py scripts/validate_parallel_scrape.py     # verificar resultados

# Data Inmobiliaria (CBR 2019-2026, quota ~15k/IP/día — multi-cuenta automático)
py scripts/run_di_bulk_multi.py --min-year 2019        # corre todas las cuentas en rotación
py src/scraping/datainmobiliaria.py --check-quota      # verificar quota (200=ok, 402=agotado)
py src/scraping/datainmobiliaria.py --list-status      # progreso X/40 comunas
py scripts/di_setup_accounts.py --list                 # ver cuentas configuradas
py scripts/di_setup_accounts.py --account N --email E --password P  # agregar/refrescar cuenta N

# Post-procesamiento tras cada sesión DI
py src/ingestion/normalize_county.py
py src/scoring/scraped_to_scored.py

# Stack completo
cd re_cl && docker-compose up -d
```

### Próximos pasos prioritarios
1. **Data Inmobiliaria**: completar las 40 comunas RM — **4/40 done** (Santiago, Providencia, Las Condes, Maipú). Task Scheduler corre automático a las 06:00 con 3 cuentas en rotación (~15k rows/día por IP). Para acelerar: usar VPN con IP distinta.
2. **Reentrenar modelo** después de cargar datos DI 2019-2026 (esperar R² > 0.70)
3. **Yapo**: necesita rotación de proxies o cookie manual (bloqueado por reCAPTCHA v3)
4. **MercadoLibre**: necesita OAuth2 del portal de desarrolladores ML

FASE 11. VALIDACIÓN INSTITUCIONAL
- Diseña cómo probar si la plataforma realmente encuentra valor.
- Propón:
  - backtest temporal
  - backtest geográfico
  - error de valuación
  - tasa de falsos positivos
  - tiempo a venta
  - spread captura oferta vs cierre
  - retorno simulado de cartera
- Define métricas mínimas para decir que el sistema sirve.

FASE 12. RIESGOS Y FRACASOS POSIBLES
- Enumera las 20 principales formas en que este proyecto puede fallar.
- Propón mitigaciones concretas.
- Incluye:
  datos malos,
  sesgos,
  sobreajuste,
  scraping frágil,
  normativa,
  mapas engañosos,
  falta de liquidez,
  señales espurias,
  falsa precisión.

IMPORTANTE SOBRE TU FORMA DE RESPONDER:
1. No seas genérico.
2. No me des teoría vacía.
3. Quiero decisiones concretas.
4. Quiero tablas.
5. Quiero frameworks.
6. Quiero ecuaciones conceptuales.
7. Quiero arquitectura.
8. Quiero trade-offs.
9. Quiero un enfoque tipo institutional-grade.
10. Debes señalar incertidumbres y supuestos.
11. Debes priorizar primero planificación y diseño; después implementación.
12. Debes decirme explícitamente qué partes conviene hacer primero.

FORMATO DE SALIDA:
Entrega tu respuesta exactamente en este orden:

1. Resumen ejecutivo del sistema
2. Definición rigurosa de “activo subvalorado”
3. Hipótesis de arbitraje / subvaloración
4. Arquitectura multiagente completa
5. Variables y fuentes de datos
6. Modelo de datos propuesto
7. Modelos analíticos propuestos
8. Lógica del Opportunity Score
9. Diseño del mapa de calor
10. Diseño de producto y UX
11. Stack tecnológico recomendado
12. Roadmap MVP / V2 / V3
13. Estructura del proyecto en VS Code
14. Backlog priorizado de desarrollo
15. Riesgos críticos y mitigaciones
16. Próximo paso exacto que recomiendas ejecutar inmediatamente

REGLAS FINALES:
- Si detectas ambigüedades, explicítalas y resuélvelas con criterio.
- Si algo no se puede saber, dilo.
- Si una fuente no es confiable, rebájala en prioridad.
- Si una funcionalidad es demasiado ambiciosa para MVP, muévela a V2 o V3.
- Piensa como si estuvieras diseñando Bloomberg + GIS + tasación + underwriting + búsqueda de arbitraje inmobiliario para Chile.
- Quiero rigor, no humo.

Ahora toma tu diseño anterior y conviértelo en un plan ejecutable en VS Code.

Quiero que hagas solo estas 4 cosas, en este orden:

1. Definir la estructura exacta de carpetas y archivos del repositorio.
2. Proponer el stack final del MVP.
3. Crear un backlog técnico priorizado con tareas numeradas.
4. Indicar qué archivo debo crear primero y escribir su contenido inicial completo.

No avances a otros archivos hasta que termines el primero.
No improvises.
Quiero una secuencia profesional de construcción.

Usa también los archivos adjuntos del proyecto como insumo metodológico y de datos.

Tareas:
1. Extrae de los archivos adjuntos cualquier estructura, variable, campo, criterio de valuación o marco conceptual útil para este sistema.
2. Distingue claramente entre:
   - insumo conceptual/metodológico,
   - insumo transaccional,
   - insumo para features,
   - insumo para validación.
3. Si el dataset transaccional tiene campos útiles, propón cómo mapearlos al esquema de base de datos del producto.
4. No asumas que el dataset está limpio: diseña su proceso de limpieza y normalización.
5. Devuélveme al final una tabla llamada:
   “Cómo aprovechar los archivos adjuntos en el MVP”.


   PRINCIPIOS OPERATIVOS OBLIGATORIOS PARA EL DESARROLLO DEL SOFTWARE

A partir de ahora, debes comportarte no solo como arquitecto del sistema, sino también como un sistema de ejecución segura, robusta y eficiente dentro de VS Code / Claude Code.

Tu prioridad no es únicamente “hacer que funcione”, sino construir una base de software:
- rápida,
- segura,
- testeable,
- auditable,
- modular,
- aprobable,
- reversible,
- observable,
- y mantenible a largo plazo.

Debes aplicar estos principios de forma estricta:

1. PLAN ANTES DE EJECUTAR
Nunca empieces implementando de inmediato una solución grande sin antes:
- definir alcance,
- descomponer tareas,
- identificar riesgos,
- definir dependencias,
- proponer orden de ejecución,
- y establecer criterios de validación.

Para cada feature importante debes seguir esta secuencia:
1) discutir,
2) diseñar,
3) planificar,
4) implementar,
5) testear,
6) revisar,
7) cerrar.

2. SUBAGENTES Y PARALELIZACIÓN INTELIGENTE
Cuando una tarea pueda dividirse en partes independientes, debes proponer subagentes o workstreams paralelos.
Ejemplos:
- agente de backend,
- agente de frontend,
- agente de GIS,
- agente de modelamiento,
- agente de testing,
- agente de revisión.

Pero no debes paralelizar tareas que:
- compartan archivos críticos al mismo tiempo,
- puedan generar conflictos de arquitectura,
- dependan de decisiones aún no cerradas,
- o aumenten el riesgo de deuda técnica.

Siempre explicita:
- qué puede hacerse en paralelo,
- qué debe hacerse secuencialmente,
- y por qué.

3. DISEÑO MODULAR Y BAJO ACOPLAMIENTO
Toda propuesta de código debe priorizar:
- separación clara de responsabilidades,
- funciones pequeñas y composables,
- módulos independientes,
- configuración desacoplada del código,
- interfaces limpias entre capas,
- y mínima duplicación.

Favorece arquitectura por dominios o módulos, no archivos gigantes.
Evita soluciones “quick and dirty” que comprometan la mantenibilidad.

4. SEGURIDAD POR DEFECTO
Debes asumir que cualquier sistema que scrapea, transforma datos, usa APIs, corre jobs o toma decisiones automáticas tiene riesgos.

Por lo tanto:
- nunca propongas ejecutar comandos destructivos sin validación,
- nunca asumas permisos ilimitados,
- nunca propongas borrados masivos sin rollback,
- nunca expongas secretos,
- nunca hardcodees credenciales,
- nunca mezcles ambientes dev / test / prod,
- nunca dejes endpoints críticos sin autenticación,
- nunca des por válida una fuente sin evaluar legalidad, licencia y estabilidad.

Debes diseñar el sistema con:
- manejo de secretos por variables de entorno,
- roles y permisos,
- logs auditables,
- validación de input,
- sanitización,
- rate limits,
- timeouts,
- retries,
- circuit breakers cuando aplique,
- y mecanismos de rollback.

5. APROBACIONES Y GATES DE CONTROL
No todo debe ejecutarse en automático.
Debes distinguir claramente entre:

A. Acciones autoaprobables
- lectura de archivos,
- análisis,
- generación de propuestas,
- tests locales,
- creación de archivos no críticos,
- documentación,
- linting,
- validación estática.

B. Acciones que requieren aprobación explícita
- borrar o sobreescribir datos existentes,
- modificar esquemas de base de datos en producción,
- instalar dependencias nuevas,
- correr migraciones destructivas,
- lanzar scrapers masivos,
- consumir APIs pagadas,
- hacer deploy,
- alterar configuración sensible,
- tocar credenciales,
- modificar permisos,
- ejecutar comandos del sistema potencialmente irreversibles.

Cada vez que propongas una acción riesgosa, debes marcarla como:
- SAFE
- NEEDS APPROVAL
- BLOCKED

6. HOOKS DE PROTECCIÓN CONCEPTUALES
Cuando diseñes flujos para Claude Code, asume que deben existir reglas de protección previas a ejecutar herramientas o comandos.
Debes sugerir hooks o validaciones para bloquear:
- comandos destructivos,
- operaciones irreversibles,
- cambios fuera del directorio del proyecto,
- escrituras sobre archivos críticos sin backup,
- migraciones no revisadas,
- scrapers que violen límites o términos,
- y cualquier acción que pueda afectar datos sensibles.

No necesitas escribir siempre los hooks reales, pero sí debes:
- indicar dónde convienen,
- qué deben revisar,
- qué bloquean,
- y qué acciones dejan pasar.

7. EFICIENCIA Y PERFORMANCE DESDE EL DISEÑO
Para cada componente debes considerar:
- costo computacional,
- latencia,
- memoria,
- concurrencia,
- volumen esperado,
- escalabilidad,
- y frecuencia de actualización.

Debes preferir:
- cargas incrementales en vez de recomputar todo,
- caching donde agregue valor,
- preagregados geoespaciales cuando convenga,
- colas para jobs pesados,
- procesamiento batch para scraping o enrichment,
- índices adecuados,
- particionamiento si aplica,
- y separación entre serving layer y training / analytics layer.

Cada vez que propongas una feature intensiva, indica:
- cuello de botella probable,
- estrategia de optimización,
- y costo de complejidad añadido.

8. ROBUSTEZ DE DATOS
El sistema debe asumir que los datos inmobiliarios vienen con:
- duplicados,
- direcciones inconsistentes,
- outliers,
- campos vacíos,
- timestamps erróneos,
- precios mal cargados,
- sesgos por publicación,
- y cambios de formato entre fuentes.

Por tanto debes diseñar:
- pipelines reproducibles,
- validaciones por esquema,
- tests de calidad de datos,
- detección de outliers,
- scoring de confianza por registro,
- trazabilidad por fuente,
- y separación clara entre dato crudo, dato limpio y dato modelado.

Nunca debes tratar el dato como perfecto.

9. VALIDACIÓN OBLIGATORIA ANTES DE DAR UNA FEATURE POR TERMINADA
Ninguna feature estará “lista” si no pasa por estas capas:
- validación funcional,
- validación técnica,
- validación de seguridad,
- validación de datos,
- test unitario,
- test de integración si aplica,
- revisión de logs / observabilidad,
- y revisión de impacto en arquitectura.

Para cada feature implementada, debes devolver:
- qué se construyó,
- qué se testeó,
- qué falta,
- qué riesgos quedan abiertos,
- y qué criterio define que realmente funciona.

10. SALIDAS EXPLICABLES, NO CAJAS NEGRAS
Toda señal, score o recomendación del sistema debe poder explicarse.
Nunca debes conformarte con “el modelo dijo esto”.
Debes diseñar outputs que muestren:
- drivers del score,
- variables que más pesaron,
- nivel de confianza,
- comparables relevantes,
- sensibilidad,
- principales riesgos,
- y razón concreta de priorización.

11. ENTREGABLES PEQUEÑOS, REVISABLES Y ACUMULATIVOS
Nunca intentes construir todo de una vez.
Debes proponer entregables:
- pequeños,
- verificables,
- desacoplados,
- y acumulativos.

Cada fase debe dejar algo útil y usable.
Prioriza quick wins que generen capacidad estructural, no solo demos vistosas.

12. REGLA DE ORO DEL CÓDIGO
Cada archivo y módulo que propongas debe cumplir idealmente con:
- claridad,
- simplicidad,
- testabilidad,
- seguridad,
- observabilidad,
- y capacidad de refactor posterior.

13. FORMATO OBLIGATORIO EN TAREAS TÉCNICAS
Cada vez que propongas trabajo técnico, usa esta estructura:
- Objetivo
- Riesgo
- Dependencias
- Nivel de criticidad
- Puede paralelizarse: sí/no
- Requiere aprobación: sí/no
- Criterio de terminado
- Tests mínimos
- Riesgo de rollback
- Siguiente paso

---

## ESTADO DE IMPLEMENTACIÓN (actualizado: 2026-04-20)

La plataforma está completamente implementada y ejecutada con datos reales del CBR.

### Pipeline real ejecutado
| Etapa | Resultado |
|-------|-----------|
| CSV fuente | 1,048,557 transacciones RM 2013-2014 |
| Limpieza | 562,854 registros limpios (53.7% tasa de retención) |
| Modelo XGBoost | R² = 0.679 en test temporal |
| Propiedades scored | 455,945 con opportunity_score |
| Comunas rankeadas | 40 comunas RM con commune_stats |
| Heatmap | data/exports/heatmap_v1.0.html |
| Reporte HTML | data/exports/report_YYYY-MM-DD.html |

### Stack implementado (código en re_cl/)
| Componente | Estado |
|-----------|--------|
| PostgreSQL 15 + PostGIS, Docker Compose | Operativo |
| ETL: load_transactions.py + clean_transactions.py | Completado |
| Feature engineering (precio, espacial, temporal, thesis, OSM, GTFS) | Completado |
| Modelo hedónico XGBoost + SHAP top-3 | Completado (R²=0.679) |
| Scoring 6 perfiles (default/location/growth/liquidity/custom/safety) | Completado |
| Walk-forward backtesting + OLS benchmark | Completado |
| Folium heatmap + commune ranking | Completado |
| Streamlit dashboard — 8 tabs incl. Deal Flow, Financial, Quality | Completado |
| FastAPI — 28 endpoints + auth JWT + saved searches | Completado |
| React + Deck.gl frontend — 8 tabs + auth modal | Completado |
| Prefect orchestration (daily + weekly) | Completado |
| Alertas (console/JSON/email/desktop/webhook) | Completado |
| HTML report generator | Completado |
| Setup orchestrator (setup_pipeline.py + .sh) | Completado |
| Scrapers Portal Inmobiliario + Toctoc (Playwright, MeLi Polaris UI 2025) | Completado — validar en producción |
| INE Censo 2017 + CEAD crime static data (34 comunas RM) | Completado |
| 296 tests (pytest, 4 skipped statsmodels) | Completado |

### Dashboard Deal Flow (accionable para arbitraje)
El dashboard Streamlit expone por propiedad:
- **Dirección exacta** (de transactions_raw.address)
- **Rol SII** (id_role) para buscar en el registro del CBR
- **Nombre del vendedor CBR** (seller_name)
- **Link Google Maps** directo a coordenadas
- **Gap vs modelo** (cuánto está subvalorado en %)
- **UF/m² actual vs predicho** por el modelo hedónico
- **Score de oportunidad** (0–1) con SHAP drivers

### Próximos pasos prioritarios
1. Ejecutar scrapers en producción y validar selectores: `py src/scraping/portal_inmobiliario.py --dump-html`
2. Evaluar acceso a Data Inmobiliaria (datainmobiliaria.cl) para transacciones CBR 2015-2024
3. Geocodificar direcciones para propiedades sin coordenadas (~30% del dataset)

14. SI ESTÁS EN DUDA, ELIGE EL CAMINO MÁS SEGURO Y EXPLICABLE
Ante trade-offs entre velocidad y seguridad, o entre sofisticación y robustez:
- para MVP: prioriza robustez, simplicidad y validación;
- para V2/V3: recién ahí introduce complejidad adicional.

15. MODO DE RESPUESTA PARA IMPLEMENTACIÓN
Cuando pases de estrategia a código, debes trabajar en ciclos:
- diseña primero,
- luego crea 1 archivo o módulo importante,
- luego valida,
- luego continúa.

No avances de forma caótica.
No generes grandes bloques de código sin explicar:
- por qué existe el archivo,
- qué resuelve,
- cómo encaja en la arquitectura,
- y cómo se validará.

16. ALERTAS AUTOMÁTICAS QUE DEBES EMITIR
Debes advertirme explícitamente cuando detectes cualquiera de estas situaciones:
- posible sobreingeniería,
- señal de datos insuficientes,
- feature demasiado ambiciosa para MVP,
- dependencia frágil,
- scraper inestable,
- problema legal o de licencias,
- sesgo de muestra,
- falsa precisión del modelo,
- riesgo de costo computacional alto,
- o arquitectura difícil de mantener.

17. REGLA FINAL
Tu misión no es solo producir código.
Tu misión es producir una plataforma confiable, rápida, segura, defendible y útil para decisiones reales de inversión inmobiliaria.

---

# ESTADO DE IMPLEMENTACIÓN (2026-04-14)

## Resumen ejecutivo

La plataforma RE_CL está completa al nivel V5. Cubre ingesta de ~1M transacciones CBR, limpieza, feature engineering (precio + espacial + temporal + tesis MIT + OSM + INE/CEAD), modelo hedónico XGBoost con SHAP, scoring explicable con 6 perfiles, backtesting walk-forward, API FastAPI, dashboard Streamlit con simulador financiero, y frontend React 3D con Deck.gl. Todo corre en Docker Compose con Nginx como reverse proxy. El único paso pendiente para producción real es ejecutar el pipeline con el CSV CBR.

**Tests: 195 total (191 passing, 4 skipped por statsmodels no instalado)**

## Stack implementado

| Capa | Tecnología | Estado |
|------|-----------|--------|
| Base de datos | PostgreSQL 15 + PostGIS | ✓ Producción |
| ETL/Pipelines | Python 3.11, Pandas, SQLAlchemy | ✓ Producción |
| ML/Scoring | XGBoost, scikit-learn, SHAP | ✓ Producción |
| GIS/Mapas | GeoPandas, Folium, Deck.gl | ✓ Producción |
| Dashboard | Streamlit (port 8501/dashboard) | ✓ Producción |
| Frontend | React + Deck.gl (port 80 / nginx) | ✓ Producción |
| API | FastAPI (port 8000 / /api + /docs) | ✓ Producción |
| Orquestación | Prefect V2 (daily 06:00 + weekly dom 03:00) | ✓ Producción |
| Scraping | Playwright (Portal Inmobiliario, Toctoc) | ✓ (validación live pendiente) |
| Entorno | Docker Compose 5 servicios + Nginx | ✓ Producción |
| Alertas | Console/JSON/email/desktop (plyer) | ✓ Producción |

## Módulos de feature engineering

| Módulo | Archivo | Features |
|--------|---------|---------|
| Precio | `src/features/price_features.py` | gap_pct, percentiles p25/p50/p75, price_vs_median |
| Espacial | `src/features/spatial_features.py` | dist_km_centroid, cluster_id (DBSCAN 500m) |
| Temporal | `src/features/temporal_features.py` | quarter dummies, season_index |
| Tesis MIT (V4.1) | `src/features/price_features.py` | age, age_sq, construction_year_bucket (7 buckets), city_zone (4 zonas), log_surface |
| OSM/Metro (V4.2) | `src/features/osm_features.py` | dist_metro_km, dist_bus_stop_km, dist_school_km, dist_hospital_km, dist_park_km, dist_mall_km, amenities_500m, amenities_1km |
| Contexto comunal (V5) | `src/features/commune_context.py` | growth_index, metro_location_score, crime_index, educacion_score, hacinamiento_score, densidad_norm |

## Modelo hedónico XGBoost (V4.1 — post tesis)

**Target:** uf_m2_building (winsorized p1-p99)
**Split:** Train 2013 | Test 2014 Q4
**Features categóricas:** project_type, county_name, construction_year_bucket, city_zone
**Features numéricas:** year, quarter, season_index, surface_m2, surface_building_m2, surface_land_m2, log_surface, age, age_sq, dist_km_centroid, cluster_id, data_confidence, price_percentile_50, dist_metro_km, dist_school_km, amenities_500m

**Insights de la tesis integrados:**
- Depreciación 2.28%/año → `age` + `age_sq`
- Vintage effect (pre-1960 más valioso) → `construction_year_bucket`
- Rendimientos decrecientes de superficie (coeff ~0.928) → `log_surface`
- Estacionalidad Q4 (+1.2%) → `season_index` + quarter dummies
- Segmentación territorial 4 zonas RM → `city_zone`

## Scoring — 6 perfiles

| Perfil | Pesos | Caso de uso |
|--------|-------|-------------|
| `default` | underval 70% + confianza 30% | Baseline |
| `location` | underval 40% + location 40% + confianza 20% | Accesibilidad |
| `growth` | underval 35% + growth 35% + confianza 30% | Apreciación comunal |
| `liquidity` | underval 50% + volumen 30% + confianza 20% | Salida rápida |
| `custom` | user-defined, auto-normalizados | Inversión personalizada |
| `safety` | underval 45% + crime 25% + confianza 20% + growth 10% | Seguridad |

## Backtesting (V4.5)

**Archivo:** `src/backtesting/walk_forward.py`
1. Temporal split: train 2013 → test 2014 (RMSE/MAE/R² por quarter, commune, tipo)
2. Quarterly rolling: ventana deslizante para detectar drift
3. Señal undervaluation: bottom-20% gap_pct vs error de predicción
4. Calibración comunal: bias predicted vs actual por comuna
5. OLS benchmark: regresión log-lineal (fórmula tesis) vs XGBoost

**Outputs:** `data/exports/backtesting_report.json`, `data/exports/commune_calibration.csv`

## Frontend React V5 — 8 tabs

| Tab | Componente | Descripción |
|-----|-----------|-------------|
| Map | `DeckMap.tsx` | Scatter/Heatmap/Hexagon 3D + Metro overlay + geolocalización |
| Ranking | `RankingPanel.tsx` | Lista rankeada, watchlist, comparador A/B, CSV export |
| Comunas | `CommunesPanel.tsx` | Ranking comunas con crime_tier, educacion_score |
| Detail | `DetailPanel.tsx` | Ficha propiedad, radar chart SHAP, comparables |
| Comparar | `ComparatorPanel.tsx` | Side-by-side A vs B, 12 métricas, highlight mejor |
| Watchlist | `WatchlistPanel.tsx` | Propiedades guardadas, CSV export |
| Tendencias | `TrendPanel.tsx` | SVG line chart precio/m² con banda IQR, multi-comuna |
| Finanzas | Streamlit `/dashboard` | DCF, cap rate, yield, escenarios, breakeven |

## API FastAPI — endpoints completos

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/properties` | Lista con filtros (tipo, comuna, zona, score) |
| GET | `/properties/{id}` | Detalle + SHAP top-3 |
| GET | `/properties/{id}/comparables` | N comparables por Haversine + filtros |
| GET | `/properties/communes` | Stats por comuna |
| GET | `/properties/communes/enriched` | Stats + crime_index + INE |
| GET | `/scores/top` | Top-N oportunidades |
| GET | `/scores/summary` | Estadísticas agregadas |
| GET | `/profiles` | Lista perfiles disponibles |
| POST | `/profiles/score` | Re-score en memoria con perfil/pesos custom |
| GET | `/analytics/price-trend` | Tendencia trimestral precio/m² |
| GET | `/analytics/score-distribution` | Distribución por decil |
| GET | `/alerts/opportunities` | Alertas sobre umbral |
| GET | `/alerts/config` | Config umbrales |
| POST | `/alerts/test` | Dispara alerta de prueba |
| GET | `/health` | Healthcheck |

**Middleware:** CORS, rate limit (100 req/60s), X-Data-Age-Days / X-Data-Stale headers

## Dashboard Streamlit — 8 tabs

Map · Ranking · Finanzas · Comunas · Scraping · Calidad · Enriquecimiento · Alertas

## Scripts de operación (V5)

```bash
# Cold start completo (Docker + pipeline completo):
bash scripts/setup_pipeline.sh

# Reanudar desde un paso específico:
py scripts/setup_pipeline.py --from-step 5
py scripts/setup_pipeline.py --skip-osm --skip-backtest

# Validación de datos:
py scripts/validate_data.py --json --exit-code

# Reporte HTML auto-contenido:
py src/reports/generate_report.py --top-n 50
```

## Pipeline completo (datos reales)

```bash
cd re_cl/

# 1. Ingesta CSV → BD (~1M filas, ~10min)
py src/ingestion/load_transactions.py

# 2. Limpieza y normalización
py src/ingestion/clean_transactions.py

# 3. Feature engineering (OSM necesita internet)
py src/features/build_features.py
# o sin OSM:
py src/features/build_features.py --skip-osm

# 4. Modelo hedónico XGBoost
py src/models/hedonic_model.py --eval

# 5. Scoring (perfil default + otros)
py src/scoring/opportunity_score.py
py src/scoring/opportunity_score.py --profile safety

# 6. Backtesting walk-forward
py src/backtesting/walk_forward.py

# 7. Mapas + reporte
py src/maps/commune_ranking.py
py src/maps/heatmap.py
py src/reports/generate_report.py
```

## Estado por componente (V7 completo — actualizado 2026-04-21)

| Componente | Estado |
|-----------|--------|
| DB schema + Docker | ✓ |
| Ingesta + limpieza (1,048,557 raw → 562,854 clean) | ✓ |
| Feature engineering (precio + espacial + temporal) | ✓ |
| Features tesis MIT (age, city_zone, log_surface) | ✓ |
| Features OSM (metro, bus, escuelas, hospitales, parques) | ✓ |
| GTFS RED bus stop proximity (dist_gtfs_bus_km) | ✓ V6.3 |
| Modelo hedónico XGBoost R²=0.679, 455,945 scored | ✓ |
| Scoring 6 perfiles | ✓ |
| Commune calibration (128 rows, 40 comunas, migration 010) | ✓ V7 |
| Land scoring / v_land_opportunities (35k opps, migration 011) | ✓ V7 |
| Backtesting walk-forward + OLS benchmark | ✓ |
| Backtesting calibración comunal (MAE +1%, RMSE +0.8%) | ✓ V7 |
| Mapas Folium + commune ranking | ✓ |
| Dashboard Streamlit (8 tabs + tab Terrenos) | ✓ V7 |
| Dashboard calibrated columns (pred/gap calibrado) | ✓ V7 |
| Simulador financiero DCF en Streamlit | ✓ |
| Panel calidad de datos en Streamlit | ✓ |
| FastAPI (28 endpoints) | ✓ V6 |
| Middleware CORS + rate limit + stale-data + X-Total-Count | ✓ V6 |
| /predict stateless ML endpoint | ✓ V6 |
| /properties/search full-text endpoint | ✓ V6 |
| JWT auth (register/login/refresh/me) | ✓ V6.6 |
| Saved searches API + DB (users table) | ✓ V6.6 |
| Sistema alertas (console/JSON/email/desktop/webhook) | ✓ |
| INE Censo 2017 — 34 comunas RM | ✓ |
| CEAD crime index — 34 comunas RM | ✓ |
| commune_context.py enrichment | ✓ |
| React frontend 8 tabs + Deck.gl | ✓ |
| React: calibrated_predicted_uf_m2 + calibrated_gap_pct | ✓ V7 |
| Comparador A/B, Watchlist, Tendencias, FinanzasPanel | ✓ V6 |
| Geolocalización + filtro por distancia | ✓ |
| Overlay Metro/Comunas/Colegios/Parques/Bus en DeckMap | ✓ V6 |
| AuthModal + auth state Zustand (localStorage) | ✓ V6.7 |
| Sidebar guardar búsqueda + WatchlistPanel búsquedas guardadas | ✓ V6.7 |
| Prefect orchestration (daily + weekly + GTFS + backtest) | ✓ |
| Scraper PI — fix selectores MeLi Polaris 2025 (ext_id, county, surface) | ✓ V7 |
| Scraper PI — --by-commune (40 comunas × 4 tipos, bypasa login gate) | ✓ V7 |
| Scraper Toctoc — fix URL, parser propiedades.results, wait_for_function | ✓ V7 |
| base.scrape_async — domcontentloaded + context rotation anti-bot | ✓ V7 |
| scraped_listings live: 173+ listings (PI + Toctoc), 40 comunas | ✓ V7 |
| scraped_to_scored (listings → model_scores) | ✓ |
| Reporte HTML auto-contenido | ✓ |
| Scripts setup_pipeline.py/.sh | ✓ |
| validate_data.py (12 checks) | ✓ |
| Índices PostGIS GiST + B-tree (007_spatial_indexes.sql) | ✓ |
| Tests (296 passing, 4 skipped: statsmodels) | ✓ V6 |
| Docker Compose 5 servicios + Nginx | ✓ |
| **Pipeline CSV real ejecutado** (2008-2016, 40 comunas RM, heatmap + report) | ✓ **2026-04-20** |
| **Scrapers validados en producción** (PI + Toctoc live, datos 2026) | ✓ **2026-04-21** |

## Roadmap V7 (completado 2026-04-21)

| Fase | Descripción | Estado |
|------|-------------|--------|
| V6.1 | Pipeline completo con CSV CBR 2008-2016 | ✓ Completado 2026-04-20 |
| V6.2 | Validar scrapers live (Portal Inmobiliario + Toctoc) | ✓ Completado 2026-04-21 |
| V6.3 | GTFS Santiago: paraderos RED (dist_gtfs_bus_km) | ✓ Completado |
| V6.4 | INE Censo 2017 por manzana (actualmente por comuna) | Futura |
| V6.5 | Datos CBR recientes (2022-2025) vía Data Inmobiliaria | Futura |
| V6.6 | JWT auth + saved searches API + DB | ✓ Completado |
| V6.7 | AuthModal + auth state React + Sidebar guardar búsqueda | ✓ Completado |
| V7.1 | Commune calibration post-hoc (migration 010, 40 comunas) | ✓ Completado 2026-04-21 |
| V7.2 | Land scoring comparable-based (migration 011, v_land_opportunities) | ✓ Completado 2026-04-21 |
| V7.3 | PI scraper --by-commune (40 comunas × 4 tipos, bypasa login gate MeLi) | ✓ Completado 2026-04-21 |
| V7.4 | Dashboard tab Terrenos + calibrated columns en Streamlit | ✓ Completado 2026-04-21 |
| V7.5 | React calibrated_gap_pct en RankingPanel + DetailPanel | ✓ Completado 2026-04-21 |
| V6.7 | Deploy en VPS/cloud (Railway, Render, o VPS propio) | Futura |