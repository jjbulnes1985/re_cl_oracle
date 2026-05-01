# RE_CL Opportunity Engine — Diseño Maestro v2

> **Cambio de scope vs. v1:** No es solo site selection comercial. Es un **motor universal de detección de oportunidades de compra** para cualquier tipo de propiedad (residencial, comercial, industrial, terreno). Los usos comerciales específicos (gas station, farmacia, supermercado, banco) son **overlays** sobre el motor base, no restricciones. Target principal: **identificar la oportunidad de compra**. Desarrollo/operación es decisión posterior del inversionista.

---

## Hallazgos críticos de la investigación previa (anclar al modelo)

1. **No existe distancia mínima nacional entre gas stations en Chile** (DS 160/2008 SEC regula seguridad técnica, no spacing comercial). Para canibalización usar **radio 1.5–3 km calibrado**, no buffer fijo de 500m.

2. **Cap rate gas station Chile**: banda **7.0% / 8.0% / 9.5%** (proxy USA + spread Chile). Etiqueta obligatoria `INFO_NO_FIDEDIGNA::pendiente_validación`. Banda ±150 bps. **Análisis de sensibilidad obligatorio.**

3. **NOI estación urbana RM**: banda **4,000 / 7,000 / 12,000 UF/año**. Capex llave en mano: **25,000–45,000 UF**.

4. **Cadenas dominantes RM**: Copec ~700, Shell/Enex ~470, Aramco (ex-Esmax) ~310. >90% del retail downstream. Aramco entró marzo 2024 — rotación de portfolio probable.

5. **Maipú confirma viabilidad MVP**: 27,203 transacciones limpias, 437 con terreno ≥500m², 96 eriazo-like. UF/m² terreno promedio: 11.3.

---

## 1. Schema PostgreSQL — extensible y desde el día 1

```sql
-- migration 014_opportunity_engine.sql

CREATE SCHEMA IF NOT EXISTS opportunity;

-- ── Catálogos ────────────────────────────────────────────────────────
CREATE TABLE opportunity.property_types (
    code            VARCHAR(50) PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    category        VARCHAR(20)  NOT NULL,  -- residential|commercial|industrial|land|mixed
    is_use_case     BOOLEAN DEFAULT FALSE,  -- TRUE para usos específicos (gas_station, pharmacy)
    requires_zoning JSONB,                  -- {permitted_uses: [...]}
    min_surface_land_m2 INT,
    typical_capex_uf_per_m2 NUMERIC(10,2),
    typical_cap_rate_low  NUMERIC(5,4),
    typical_cap_rate_mid  NUMERIC(5,4),
    typical_cap_rate_high NUMERIC(5,4),
    notes TEXT
);

INSERT INTO opportunity.property_types VALUES
  ('apartment',    'Departamento',           'residential', FALSE, NULL,         NULL, NULL,    NULL,    NULL,    NULL,   NULL),
  ('house',        'Casa',                   'residential', FALSE, NULL,         NULL, NULL,    NULL,    NULL,    NULL,   NULL),
  ('land',         'Terreno (genérico)',     'land',        FALSE, NULL,         NULL, NULL,    NULL,    NULL,    NULL,   NULL),
  ('retail',       'Local comercial',        'commercial',  FALSE, NULL,         NULL, NULL,    0.060,   0.075,   0.090, NULL),
  ('office',       'Oficina',                'commercial',  FALSE, NULL,         NULL, NULL,    0.054,   0.058,   0.065, 'Colliers LATAM Q2-2019'),
  ('warehouse',    'Bodega',                 'industrial',  FALSE, NULL,         NULL, NULL,    0.058,   0.062,   0.070, 'Colliers LATAM Q2-2019'),
  ('industrial',   'Industrial pesado',      'industrial',  FALSE, NULL,         NULL, NULL,    0.075,   0.085,   0.100, NULL),
  -- Casos de uso (overlays):
  ('gas_station',  'Estación de servicio',   'commercial',  TRUE,  '{"permitted_uses":["comercial","equipamiento"]}', 500,  35000, 0.070, 0.080, 0.095, 'Proxy USA + spread Chile. INFO_NO_FIDEDIGNA'),
  ('pharmacy',     'Farmacia',               'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                 80,   12000, 0.065, 0.075, 0.090, NULL),
  ('supermarket',  'Supermercado',           'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                1500,  18000, 0.060, 0.072, 0.085, NULL),
  ('bank_branch',  'Sucursal bancaria',      'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                 100,  10000, 0.055, 0.065, 0.080, NULL),
  ('clinic',       'Clínica/centro médico',  'commercial',  TRUE,  '{"permitted_uses":["equipamiento"]}',              200,  20000, 0.065, 0.075, 0.090, NULL),
  ('restaurant',   'Restaurante',            'commercial',  TRUE,  '{"permitted_uses":["comercial"]}',                 100,  15000, 0.070, 0.085, 0.100, NULL);

CREATE TABLE opportunity.investor_profiles (
    code        VARCHAR(50) PRIMARY KEY,
    name        VARCHAR(100),
    description TEXT,
    weights     JSONB
);

INSERT INTO opportunity.investor_profiles VALUES
  ('value',         'Valor (descuento puro)',           'Descuento vs valor justo',
   '{"undervaluation":0.65,"confidence":0.20,"location":0.15}'),
  ('growth',        'Crecimiento comunal',              'Plusvalía por dinámica zonal',
   '{"undervaluation":0.40,"growth":0.40,"confidence":0.20}'),
  ('income',        'Renta (yield)',                    'NOI proyectado',
   '{"undervaluation":0.30,"yield":0.50,"confidence":0.20}'),
  ('redevelopment', 'Redesarrollo (cambio de uso)',     'Subutilización + zonificación favorable',
   '{"undervaluation":0.30,"redevelopment_potential":0.50,"confidence":0.20}'),
  ('flipper',       'Reventa rápida (12-24 meses)',     'Liquidez + descuento',
   '{"undervaluation":0.50,"liquidity":0.30,"confidence":0.20}'),
  ('operator',      'Operador comercial (uso final)',   'Score específico por uso',
   '{"use_specific":0.60,"undervaluation":0.25,"confidence":0.15}');

-- ── Candidatos ──────────────────────────────────────────────────────
-- Cualquier propiedad detectada como oportunidad potencial
-- Fuentes: CBR transactions, scraped listings, catastro SII, detección satelital
CREATE TABLE opportunity.candidates (
    id                  BIGSERIAL PRIMARY KEY,
    source              VARCHAR(30) NOT NULL,  -- cbr_transaction|scraped_listing|catastro_sii|satellite
    source_id           VARCHAR(100),
    detected_at         TIMESTAMPTZ DEFAULT NOW(),

    -- Identificación
    rol_sii             VARCHAR(50),
    address             TEXT,
    county_name         VARCHAR(100),
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    geom                geometry(Point, 4326),

    -- Físico
    property_type_code  VARCHAR(50) REFERENCES opportunity.property_types(code),
    surface_land_m2     NUMERIC(12,2),
    surface_building_m2 NUMERIC(12,2),
    construction_year   INT,

    -- Estado de mercado
    last_transaction_uf NUMERIC(15,2),
    last_transaction_date DATE,
    listed_price_uf     NUMERIC(15,2),
    listed_at           TIMESTAMPTZ,
    avaluo_fiscal_uf    NUMERIC(15,2),
    avaluo_to_market_ratio NUMERIC(5,4),  -- avaluo/precio_mercado (proxy de subvaloración SII)

    -- Subutilización (señales de redesarrollo)
    construction_ratio          NUMERIC(5,4),  -- surface_building / surface_land
    is_eriazo                   BOOLEAN,
    is_below_zoning_density     BOOLEAN,
    zoning_max_far              NUMERIC(5,2),  -- coeficiente constructibilidad permitido
    zoning_realized_far         NUMERIC(5,2),  -- el actual

    UNIQUE(source, source_id)
);
CREATE INDEX idx_candidates_geom    ON opportunity.candidates USING GIST(geom);
CREATE INDEX idx_candidates_county  ON opportunity.candidates(county_name);
CREATE INDEX idx_candidates_type    ON opportunity.candidates(property_type_code);
CREATE INDEX idx_candidates_eriazo  ON opportunity.candidates(is_eriazo) WHERE is_eriazo=TRUE;

-- ── Valoraciones (multi-método) ─────────────────────────────────────
CREATE TABLE opportunity.valuations (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    method          VARCHAR(30) NOT NULL,  -- hedonic_xgb|comparables|dcf|cap_inverse|triangulated
    model_version   VARCHAR(20) NOT NULL,
    valued_at       TIMESTAMPTZ DEFAULT NOW(),

    estimated_uf       NUMERIC(15,2),
    estimated_uf_m2    NUMERIC(12,4),
    p25_uf             NUMERIC(15,2),
    p50_uf             NUMERIC(15,2),
    p75_uf             NUMERIC(15,2),
    confidence         NUMERIC(3,2),

    -- Inputs trazables
    inputs JSONB,
    notes  TEXT
);
CREATE INDEX idx_valuations_candidate ON opportunity.valuations(candidate_id);

-- ── Scores ──────────────────────────────────────────────────────────
CREATE TABLE opportunity.scores (
    id                BIGSERIAL PRIMARY KEY,
    candidate_id      BIGINT REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    use_case          VARCHAR(50) DEFAULT 'as_is',  -- as_is | gas_station | pharmacy | redevelopment_residential | ...
    investor_profile  VARCHAR(50) REFERENCES opportunity.investor_profiles(code),
    model_version     VARCHAR(20),
    scored_at         TIMESTAMPTZ DEFAULT NOW(),

    -- Componentes (todas 0-1)
    undervaluation_score    NUMERIC(5,4),
    location_score          NUMERIC(5,4),
    growth_score            NUMERIC(5,4),
    yield_score             NUMERIC(5,4),
    redevelopment_score     NUMERIC(5,4),
    liquidity_score         NUMERIC(5,4),
    use_specific_score      NUMERIC(5,4),  -- only when use_case != 'as_is'
    confidence              NUMERIC(5,4),

    -- Output
    opportunity_score   NUMERIC(5,4),  -- compuesto 0-1
    max_payable_uf      NUMERIC(15,2), -- precio máximo según uso (cap inverso)

    -- Top drivers
    drivers JSONB,
    risk_summary JSONB,

    UNIQUE(candidate_id, use_case, investor_profile, model_version)
);
CREATE INDEX idx_scores_candidate ON opportunity.scores(candidate_id);
CREATE INDEX idx_scores_score ON opportunity.scores(opportunity_score DESC);
CREATE INDEX idx_scores_use ON opportunity.scores(use_case);

-- ── Riesgos (matriz por candidato) ──────────────────────────────────
CREATE TABLE opportunity.risks (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    BIGINT REFERENCES opportunity.candidates(id) ON DELETE CASCADE,
    category        VARCHAR(30),  -- regulatory|demand|competition|liquidity|model|environmental|legal
    severity        VARCHAR(20),  -- low|medium|high|critical
    description     TEXT,
    flagged_at      TIMESTAMPTZ DEFAULT NOW(),
    source_agent    VARCHAR(50)
);
CREATE INDEX idx_risks_candidate ON opportunity.risks(candidate_id);

-- ── Competidores (activos comerciales existentes) ──────────────────
CREATE TABLE opportunity.competitors (
    id              BIGSERIAL PRIMARY KEY,
    use_case        VARCHAR(50),
    operator        VARCHAR(100),  -- Copec|Shell|Aramco|Cruz Verde|Salcobrand|Banco Estado|...
    name            VARCHAR(200),
    address         TEXT,
    county_name     VARCHAR(100),
    latitude        DOUBLE PRECISION,
    longitude       DOUBLE PRECISION,
    geom            geometry(Point, 4326),
    operational_status VARCHAR(20) DEFAULT 'active',  -- active|closed|under_construction
    source          VARCHAR(50),  -- osm|sec_gov|isp|minsal|cmf|manual
    source_id       VARCHAR(100),
    fetched_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_competitors_geom ON opportunity.competitors USING GIST(geom);
CREATE INDEX idx_competitors_use  ON opportunity.competitors(use_case);

-- ── Versiones de modelo (bitácora) ──────────────────────────────────
CREATE TABLE opportunity.model_versions (
    version         VARCHAR(20) PRIMARY KEY,
    model_type      VARCHAR(50),  -- valuation_hedonic|demand_gas_station|demand_pharmacy|...
    trained_at      TIMESTAMPTZ,
    n_train         INT,
    n_test          INT,
    metrics         JSONB,
    feature_importance JSONB,
    notes           TEXT
);

-- ── Vista unificada para frontend ───────────────────────────────────
CREATE OR REPLACE VIEW opportunity.v_top_opportunities AS
SELECT
    c.id, c.address, c.county_name, c.latitude, c.longitude,
    c.property_type_code, c.surface_land_m2, c.surface_building_m2,
    c.is_eriazo,
    s.use_case, s.investor_profile,
    s.opportunity_score, s.max_payable_uf,
    v.estimated_uf, v.p25_uf, v.p75_uf, v.confidence AS valuation_confidence,
    s.drivers, s.risk_summary,
    s.scored_at
FROM opportunity.candidates c
JOIN opportunity.scores s ON s.candidate_id = c.id
LEFT JOIN opportunity.valuations v ON v.candidate_id = c.id AND v.method = 'triangulated'
WHERE s.opportunity_score >= 0.5
ORDER BY s.opportunity_score DESC;
```

---

## 2. Pipeline de candidatos — 4 fuentes (extensible)

```
opportunity.candidates ← múltiples fuentes:

A. cbr_transaction (HOY: 824k limpios)
   └─ Cualquier transacción CBR es candidato — podría re-listarse, hay info de precio histórico

B. scraped_listing (HOY: 5,003 listings activos)
   └─ Propiedades en venta en PI/Toctoc/MercadoLibre
   └─ Precio listado vs valor justo del modelo

C. satellite_detection (HEURÍSTICA — ejecutable HOY)
   └─ surface_building_m2 / surface_land_m2 < 0.10 + surface_land_m2 ≥ 500m²
   └─ Propiedades CBR transadas pero subutilizadas
   └─ Marcadas con is_eriazo=TRUE

D. catastro_sii (FUTURO — requiere data abierta SII completa)
   └─ Roles SII de TODA la comuna (no solo los transados)
   └─ Permite descubrir terrenos nunca transados
```

**Heurísticas de subutilización (ejecutables hoy):**
```sql
-- Marcar candidatos eriazo-like
UPDATE opportunity.candidates SET is_eriazo = TRUE
WHERE surface_land_m2 >= 500
  AND COALESCE(surface_building_m2, 0) / NULLIF(surface_land_m2, 0) < 0.10;

-- Marcar subutilización vs zonificación (cuando tengamos PRC)
UPDATE opportunity.candidates SET is_below_zoning_density = TRUE
WHERE zoning_max_far IS NOT NULL
  AND zoning_realized_far / zoning_max_far < 0.5;
```

---

## 3. Modelo de valoración — multi-método con triangulación

```python
# Pseudo-código del Valuation Engine
def value_candidate(candidate, use_case='as_is'):
    valuations = {}

    # Método 1: Hedónico XGBoost (universal, ya implementado)
    valuations['hedonic'] = predict_hedonic(candidate)  # uses transaction_features

    # Método 2: Comparables zonales (universal)
    valuations['comparables'] = comparables_median(
        commune=candidate.county_name,
        property_type=candidate.property_type_code,
        surface_decile=decile(candidate.surface_land_m2),
        months=24
    )

    # Método 3: DCF (solo si hay NOI proyectable)
    if use_case in COMMERCIAL_USE_CASES:
        valuations['dcf'] = dcf_valuation(candidate, use_case)

    # Método 4: Cap inverso (solo para uso comercial)
    if use_case in COMMERCIAL_USE_CASES:
        cap_rate = property_types[use_case].typical_cap_rate_mid
        noi = estimate_noi(candidate, use_case)
        valuations['cap_inverse'] = noi / cap_rate

        # Análisis de sensibilidad obligatorio
        valuations['cap_inverse_low']  = noi / property_types[use_case].typical_cap_rate_high
        valuations['cap_inverse_high'] = noi / property_types[use_case].typical_cap_rate_low

    # Triangulación
    triangulated = {
        'estimated_uf': median(valuations.values()),
        'p25_uf': percentile(valuations.values(), 25),
        'p75_uf': percentile(valuations.values(), 75),
        'confidence': 1.0 - normalized_range(valuations.values())
    }

    return triangulated, valuations  # ambos guardados en opportunity.valuations
```

**Disclaimer obligatorio en outputs comerciales:**
```
⚠ Cap rate referencial — pendiente de validación con asesor de mercado.
Banda de sensibilidad: ±150 bps.
Fuente: proxy USA net lease + spread Chile (B+E Q4-2024, RPC).
```

---

## 4. Score de oportunidad — universal + uso específico

### 4.1 Score base (cualquier candidato, sin uso específico)

```python
opportunity_score = (
    undervaluation_score * w_underv +
    location_score       * w_loc +
    growth_score         * w_growth +
    yield_score          * w_yield +
    redevelopment_score  * w_redev +
    confidence           * w_conf
)
# Pesos vienen del investor_profile
```

### 4.2 Score de uso comercial (overlay)

```python
gas_station_score = (
    undervaluation_score * 0.25 +    # bajo precio
    accessibility_score  * 0.25 +    # vía estructurante OSM
    demand_score         * 0.20 +    # densidad pob 1km + flujo vehicular
    competition_score    * 0.20 +    # NO sobre-saturado (radio 2km)
    zoning_score         * 0.10      # uso permitido en PRC
)
```

**competition_score (sin buffer fijo, calibrado por radio):**
```python
def competition_score(candidate, use_case, radius_km=2.0):
    n_competitors = count_competitors_within(candidate.geom, radius_km, use_case)
    zonal_p25, zonal_p75 = zonal_competitor_density_percentiles(
        candidate.county_name, use_case, radius_km
    )
    if n_competitors < zonal_p25:
        return 1.0  # under-served
    elif n_competitors > zonal_p75:
        return 0.0  # over-saturated
    else:
        return 1.0 - (n_competitors - zonal_p25) / (zonal_p75 - zonal_p25)
```

### 4.3 Validación cruzada (test crítico antes de release)

Correr el modelo de gas station sobre **Las Condes** y verificar que las estaciones existentes (Copec en Apoquindo, Shell en Manquehue) caigan en el top quartile de score. Si correlación entre score modelado y existencia real >= 0.6, el modelo se valida.

---

## 5. UX minimalista — una pantalla, decisiones obvias

```
┌────────────────────────────────────────────────────────────┐
│  RE_CL Opportunity Engine                       [Login]    │
│ ┌────────────────────────────────────────────────────────┐ │
│ │ 🔍 Buscar: dirección, comuna o "casa Maipú"            │ │
│ └────────────────────────────────────────────────────────┘ │
│                                                             │
│ ┌──────────────┐ ┌────────────────────────────────────────┐│
│ │ Tipo  ▾      │ │                                        ││
│ │ Comuna ▾     │ │           MAPA RM Santiago            ││
│ │ Uso ▾        │ │           (Deck.gl 3D)                 ││
│ │ Score ≥ ▢    │ │                                        ││
│ │              │ │       🟢 Alta · 🟡 Media · 🔴 Riesgo  ││
│ │ Top 10:      │ │                                        ││
│ │ 1. Av...     │ │                                        ││
│ │    87 · 14k UF│ │                                        ││
│ │ 2. Cl...     │ │                                        ││
│ │    81 · 9k UF│ │                                        ││
│ │ ...          │ │                                        ││
│ └──────────────┘ └────────────────────────────────────────┘│
│                                                             │
│  data v3.2 · model v1.4 · actualizado 30-Abr-2026          │
└────────────────────────────────────────────────────────────┘

Click en candidato → ficha lateral:

┌──────────────────────────────────────────┐
│ Av. Pajaritos 5432, Maipú · Score 87     │
├──────────────────────────────────────────┤
│ Precio estimado:                         │
│   12,500 ─────●────── 16,800 UF          │
│              14,200                      │
│                                          │
│ ⚠ Riesgos                                │
│  🟡 Plan regulador en revisión           │
│  🟡 Sin venta comparable < 6 meses       │
│  🟢 Sin flag ambiental                   │
│                                          │
│ ✓ Tesis                                  │
│  • 28% bajo valor justo                  │
│  • Vía estructurante a 200m              │
│  • Densidad pob 1km: 8.2k                │
│  • Sin competencia gas station 1.5km     │
│                                          │
│ Próximos pasos due diligence             │
│  • Cert. informaciones DOM Maipú         │
│  • Tasación independiente                │
│  • Verificar uso permitido PRC           │
│                                          │
│ [Google Maps] [Ficha SII] [PDF] [Watch]  │
└──────────────────────────────────────────┘
```

**Test de simplicidad:** Usuario nuevo encuentra "casa para invertir en Maipú con score >80" en <60 segundos sin leer instrucciones.

---

## 6. Plan ejecutable para Sonnet — 8 horas

```
HORA 1 — Schema + setup
  ├─ migration 014_opportunity_engine.sql (catálogos + tablas + vista)
  ├─ semilla property_types con cap rates
  └─ semilla investor_profiles

HORA 2 — Ingesta candidatos desde fuentes existentes
  ├─ ETL: transactions_clean → candidates (source='cbr_transaction'), 824k rows
  ├─ ETL: scraped_listings → candidates (source='scraped_listing'), 5,003 rows
  ├─ Marcar is_eriazo (heurística construction_ratio < 0.10)
  └─ Cómputo construction_ratio para todos

HORA 3 — Ingesta competidores existentes
  ├─ OSM Overpass: amenity=fuel|pharmacy|bank|supermarket en RM
  ├─ SEC datos abiertos: estaciones autorizadas (CSV/scraping)
  ├─ ISP: farmacias autorizadas (scraping)
  └─ Inserts en opportunity.competitors

HORA 4 — Modelo de valoración multi-método
  ├─ Wrapper sobre XGBoost actual (hedonic_xgb)
  ├─ SQL view comparables_zonal (mediana por commune, type, surface_decile, 24m)
  ├─ Cap inverso por uso comercial (con sensibilidad)
  └─ Función triangulate() → opportunity.valuations

HORA 5 — Scoring base (todos los tipos, profile=value)
  ├─ Cómputo undervaluation_score, location_score, confidence para 824k
  ├─ Reusar features de transaction_features
  └─ Insert en opportunity.scores con use_case='as_is'

HORA 6 — Scoring uso comercial: gas_station
  ├─ Cómputo accessibility_score (distancia OSM trunk/primary)
  ├─ Cómputo demand_score (densidad pob INE 1km)
  ├─ Cómputo competition_score (radio 2km calibrado)
  ├─ Use specific score combinado
  └─ Validación cruzada Las Condes (test correlación con existentes)

HORA 7 — API endpoints
  ├─ /opportunity/candidates?use=&commune=&type=&score_min=
  ├─ /opportunity/candidates/{id} (ficha completa)
  ├─ /opportunity/competitors?use=&commune=
  ├─ /opportunity/use-cases (catálogo property_types)
  └─ /opportunity/profiles (catálogo investor_profiles)

HORA 8 — Frontend mínimo
  ├─ Reutilizar Deck.gl + Sidebar del frontend existente
  ├─ Página /opportunity con mapa + filtros + ranking
  ├─ Ficha lateral al click
  └─ Test 60 segundos
```

---

## 7. Criterios de validación pre-release

- [ ] Schema creado + 824k candidatos ingestados
- [ ] Cada candidato tiene al menos 2 valoraciones (hedonic + comparables)
- [ ] Banda p25-p75 calculada para todos los candidatos
- [ ] gas_station scoring corre sobre Maipú + validación Las Condes con correlación >= 0.6
- [ ] API responde en < 500ms para query típica
- [ ] Frontend pasa test 60s sobre "casa para invertir en Maipú con score >80"
- [ ] Disclaimer cap rate visible en toda valoración comercial
- [ ] Listado de DUDA:: en respuesta API y en UI

---

## 8. Estructura del prompt de ejecución para Sonnet

El prompt para la sesión de Sonnet va en `prompts/opportunity_engine_execute.md`. Está estructurado para:

1. Cargar contexto mínimo (este diseño)
2. Ejecutar las 8 horas en orden
3. Reportar al final de cada hora con métricas
4. NO inventar datos — marcar `DUDA::` cuando falten
5. Generar commits atómicos por cada paso (compatible con `/gsd-execute-phase`)

---

*Diseño generado con Opus 4.7 · 2026-04-30 · Versión 2.0 (universal, post feedback usuario)*
