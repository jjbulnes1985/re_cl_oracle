# Master Plan — Asset Subclass Weights Engine
## RE_CL: heatmap multi-dimensional con pesos por subclase de activo

> **Diseño Opus, ejecución Sonnet, multi-agente, security-first.**
> Extiende [master_plan_geltner.md](master_plan_geltner.md) agregando pesos específicos por subclase de activo
> y un mapa de calor que rota dinámicamente la dimensión visualizada.

---

## 1. Problema que resuelve

Hoy RE_CL aplica **pesos por perfil de inversionista** (default/location/growth/liquidity/safety):

```
opportunity_score = w_uv·undervaluation + w_loc·location + w_growth·growth + w_conf·confidence
```

Pero **no diferencia por tipo de activo**. Un departamento se score igual que un terreno o una gasolinera, cuando en realidad las variables que importan son distintas:

| Subclase | Variables que importan más |
|----------|----------------------------|
| **Apartment income** (residencial arriendo) | cap rate, transit proximity, school score, vacancy |
| **House flip** (casa para revender) | renovation potential, lot size ratio, neighborhood appreciation |
| **Land development** (terreno) | zoning, slope, utilities access, road width |
| **Gas station** | traffic count, highway proximity, competitor density |
| **Pharmacy / supermarket** | foot traffic, age demographics, competitor density |
| **Bank branch** | demographic income, competitor density, ATM coverage |
| **Restaurant** | foot traffic, parking, demographics, competitor density |
| **Office A+** | metro proximity, parking ratio, building class, vacancy zone |
| **Industrial / warehouse** | highway access, ceiling height, loading docks, utility capacity |

**El score actual mezcla todo en un solo número.** Necesitamos:

1. Un **vector de scores por subclase** (no un solo score) por candidato.
2. **Heatmap que rota** la dimensión visualizada (subclase activa).
3. **Frontend que el usuario configura**: "muéstrame oportunidades como gas station" → solo ese score.

---

## 2. Arquitectura multi-agente

Aprovechando lo ya construido en [master_plan_geltner.md](master_plan_geltner.md) (A1-A6 implementados):

```
┌────────────────────────────────────────────────────────────────────┐
│  USUARIO selecciona subclase de interés                            │
│  ↓                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  A8: SUBCLASS WEIGHTS DISPATCHER (nuevo)                     │ │
│  │  → resuelve weights desde tabla asset_subclass_weights       │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ↓                                                                 │
│  ┌─────────────────────────────────────────┐                       │
│  │  A1: Valuation     (DCF + comps + cost) │                       │
│  │  A2: Demand        (OSM + demographics) │                       │
│  │  A3: Risk          (regulatory + env)   │ ← producen métricas   │
│  │  A4: Score Fusion  (weighted blend)     │   por dimensión       │
│  └─────────────────────────────────────────┘                       │
│  ↓                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  A4_v2: SCORE FUSION SUBCLASS-AWARE                          │ │
│  │  Aplica weights[subclass] a las métricas de A1-A3            │ │
│  │  Output: opportunity_score_<subclass> ∈ [0,1]                │ │
│  └──────────────────────────────────────────────────────────────┘ │
│  ↓                                                                 │
│  ┌──────────────────────────────────────────────────────────────┐ │
│  │  HEATMAP RENDERER (frontend, Deck.gl)                        │ │
│  │  → HeatmapLayer con weight = score_<subclass_seleccionada>   │ │
│  │  → ColorRange dinámico (verde-amarillo-rojo)                 │ │
│  │  → Toggle subclase rerenderiza sin requerir backend          │ │
│  └──────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────┘
```

**Ventaja:** los scores se computan **una vez** por candidato (todos los subclass scores), y el frontend **selecciona qué dimensión mostrar** sin nuevas llamadas API.

---

## 3. Pesos por subclase (tabla canónica)

### 3.1 Dimensiones disponibles

Cada candidato tiene métricas computadas por agentes A1-A3:

| Métrica | Source agent | Rango | Significado |
|---------|--------------|-------|-------------|
| `underval_score` | A1 | 0-1 | % bajo predicción modelo (winsorized) |
| `cap_rate_score` | A1 | 0-1 | NOI / precio (mayor = mejor para income) |
| `appreciation_score` | A1 | 0-1 | Crecimiento histórico 5y comuna |
| `transit_score` | A2 | 0-1 | Inverso distancia metro/bus |
| `school_score` | A2 | 0-1 | Inverso distancia colegios + calidad |
| `traffic_score` | A2 | 0-1 | Conteo OSM ways primary/secondary cercanos |
| `competitor_density` | A2 | 0-1 | OSM categoría correspondiente (gas/farma/etc) |
| `demographic_match` | A2 | 0-1 | Match perfil INE comuna vs target subclase |
| `liquidity_score` | A2 | 0-1 | Volumen transacciones comuna+tipo trailing 12m |
| `regulatory_risk` | A3 | 0-1 | Inverso restricciones zoning |
| `environmental_risk` | A3 | 0-1 | Inverso flags sísmicos/inundación |
| `data_confidence` | — | 0-1 | Calidad/completitud datos |

### 3.2 Tabla `asset_subclass_weights`

```sql
CREATE TABLE asset_subclass_weights (
  subclass             VARCHAR(50)    PRIMARY KEY,
  description          TEXT           NOT NULL,
  parent_class         VARCHAR(20)    NOT NULL,  -- 'residential', 'commercial', 'land'

  -- Pesos (deben sumar 1.0, validado por trigger)
  w_underval           NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_cap_rate           NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_appreciation       NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_transit            NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_school             NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_traffic            NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_competitor_density NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_demographic_match  NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_liquidity          NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_regulatory_risk    NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_environmental_risk NUMERIC(4,3)   NOT NULL DEFAULT 0.0,
  w_data_confidence    NUMERIC(4,3)   NOT NULL DEFAULT 0.0,

  active               BOOLEAN        NOT NULL DEFAULT TRUE,
  created_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ    NOT NULL DEFAULT NOW(),

  CONSTRAINT weights_sum_one CHECK (
    ABS(w_underval + w_cap_rate + w_appreciation + w_transit + w_school +
        w_traffic + w_competitor_density + w_demographic_match + w_liquidity +
        w_regulatory_risk + w_environmental_risk + w_data_confidence - 1.0) < 0.001
  )
);
```

### 3.3 Pesos iniciales (seed data, basado en Geltner + práctica industria)

```sql
INSERT INTO asset_subclass_weights VALUES

-- ═══ RESIDENTIAL ═══
('apartment_income', 'Departamento para arriendo (cap rate enfoque)', 'residential',
  0.20, 0.30, 0.05, 0.20, 0.10, 0.0, 0.0, 0.05, 0.05, 0.0, 0.0, 0.05, true, NOW(), NOW()),

('apartment_flip', 'Departamento para revender 3-5 años', 'residential',
  0.30, 0.0, 0.30, 0.10, 0.05, 0.0, 0.0, 0.05, 0.10, 0.0, 0.0, 0.10, true, NOW(), NOW()),

('house_income', 'Casa para arriendo familiar', 'residential',
  0.20, 0.25, 0.10, 0.10, 0.20, 0.0, 0.0, 0.05, 0.05, 0.0, 0.0, 0.05, true, NOW(), NOW()),

('house_flip', 'Casa para refacción + revender', 'residential',
  0.35, 0.0, 0.30, 0.05, 0.10, 0.0, 0.0, 0.05, 0.10, 0.0, 0.0, 0.05, true, NOW(), NOW()),

-- ═══ LAND ═══
('land_residential_dev', 'Terreno para desarrollo residencial', 'land',
  0.30, 0.0, 0.20, 0.10, 0.10, 0.0, 0.0, 0.05, 0.0, 0.15, 0.05, 0.05, true, NOW(), NOW()),

('land_commercial_dev', 'Terreno para desarrollo comercial', 'land',
  0.25, 0.0, 0.15, 0.0, 0.0, 0.20, 0.10, 0.10, 0.0, 0.10, 0.05, 0.05, true, NOW(), NOW()),

-- ═══ COMMERCIAL OPERATIONAL ═══
('gas_station', 'Estación de servicio (operación)', 'commercial',
  0.10, 0.20, 0.05, 0.0, 0.0, 0.30, 0.20, 0.05, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('pharmacy', 'Farmacia (operación)', 'commercial',
  0.10, 0.20, 0.05, 0.10, 0.0, 0.10, 0.20, 0.15, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('supermarket', 'Supermercado (operación)', 'commercial',
  0.10, 0.20, 0.05, 0.10, 0.0, 0.15, 0.15, 0.15, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('bank_branch', 'Sucursal bancaria', 'commercial',
  0.10, 0.20, 0.05, 0.15, 0.0, 0.05, 0.20, 0.15, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('clinic', 'Clínica / centro médico', 'commercial',
  0.10, 0.20, 0.05, 0.15, 0.05, 0.05, 0.15, 0.15, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('restaurant', 'Local restaurant / café', 'commercial',
  0.10, 0.15, 0.05, 0.10, 0.0, 0.20, 0.20, 0.10, 0.0, 0.05, 0.0, 0.05, true, NOW(), NOW()),

('office_class_a', 'Oficina clase A+ (zona prime)', 'commercial',
  0.20, 0.25, 0.05, 0.20, 0.0, 0.05, 0.05, 0.05, 0.10, 0.0, 0.0, 0.05, true, NOW(), NOW()),

('warehouse', 'Bodega / industrial logístico', 'commercial',
  0.20, 0.20, 0.10, 0.0, 0.0, 0.25, 0.05, 0.0, 0.10, 0.05, 0.0, 0.05, true, NOW(), NOW())
;
```

---

## 4. Implementación — fases

### FASE 1: Backend foundation (1-2 días, Sonnet)

**1.1 Migration 014_asset_subclass_weights.sql**
- Crear tabla `asset_subclass_weights`
- Seed con 14 subclases iniciales
- Trigger `BEFORE INSERT/UPDATE` que valida `SUM(weights) = 1.0`
- View `v_subclass_weights_active` (solo `active = TRUE`)

**1.2 Migration 015_subclass_scores.sql**
- Agregar columna `subclass_scores JSONB` a `model_scores`
  - Schema: `{"apartment_income": 0.78, "gas_station": 0.45, ...}`
- Index GIN sobre `subclass_scores` para queries `WHERE subclass_scores->>'gas_station'::numeric > 0.7`

**1.3 src/scoring/asset_subclass.py**
- `class SubclassScorer`:
  - `__init__(engine)` — carga weights desde DB
  - `score_candidates(df: pd.DataFrame) -> pd.DataFrame`
    - Para cada subclase activa, computa `score_<subclass>` aplicando weights
    - Retorna df con N nuevas columnas
  - `to_jsonb_dict(row) -> dict` — convierte fila a dict para JSONB
- CLI: `py src/scoring/asset_subclass.py [--subclass apartment_income] [--limit 1000]`

**1.4 src/api/routes/subclass.py** (nuevo router FastAPI)
- `GET /subclasses` → lista todas con descripciones
- `GET /subclasses/{name}/weights` → weights detallados
- `GET /subclasses/{name}/heatmap?bbox=...&limit=10000`
  - Retorna `[{lat, lng, score, candidate_id}]` para HeatmapLayer
- `POST /subclasses/{name}/weights` (admin only, JWT) → actualizar pesos
- `POST /subclasses/score-candidate?id=...&subclass=...` → re-score on demand

**1.5 Tests (pytest)**
- `test_subclass_weights_sum.py` — verifica trigger sum=1.0
- `test_subclass_scorer.py` — score determinista para fixture conocido
- `test_subclass_api.py` — happy path + auth + 404

### FASE 2: Frontend heatmap (1-2 días, Sonnet)

**2.1 SubclassSelector.tsx** (nuevo)
- Dropdown agrupado por `parent_class` (residential / land / commercial)
- Cada opción muestra descripción + ícono
- Estado en Zustand: `state.activeSubclass`

**2.2 SubclassHeatmap.tsx** (nuevo)
- `import { HeatmapLayer } from '@deck.gl/aggregation-layers'`
- Props: `data`, `getWeight: d => d.subclass_scores[activeSubclass]`
- `colorRange`: gradient verde→amarillo→rojo
- `radiusPixels`: 30 default, prop overridable
- Re-renderiza al cambiar `activeSubclass` sin nueva llamada API

**2.3 HomeShell.tsx** integración
- Layer toggle entre `ScatterplotLayer` (pins por score) y `HeatmapLayer` (densidad)
- Botón flotante "Cambiar subclase" → SubclassSelector overlay
- Sidebar muestra "Mostrando: <subclass>" como badge

**2.4 api.ts** wrapper
- `fetchSubclasses(): Promise<Subclass[]>`
- `fetchSubclassHeatmap(name, bbox): Promise<HeatmapPoint[]>`

### FASE 3: Auto-tuning (opcional, Opus design)

**3.1 src/scoring/subclass_optimizer.py**
- Para cada subclase, ML pequeño que ajusta pesos para maximizar correlación con `success_label` (manual feedback usuario)
- Solver: `scipy.optimize.minimize` con constraint `sum=1`
- Persistir history: tabla `subclass_weights_history` para rollback

**3.2 Dashboard admin**
- Streamlit panel `subclass_admin.py`
- Sliders por dimension, preview live del heatmap
- Botón "Reset to Geltner defaults"

---

## 5. Aplicación de virtudes tododeia

Según [master_plan_geltner.md sección 8](master_plan_geltner.md#8-seguridad-e-instituciones) + concepts del catálogo tododeia:

| Virtud | Cómo se aplica |
|--------|----------------|
| **Multi-agente paralelo** | A1+A2+A3 corren paralelo via `asyncio.gather`; A4_v2 espera todos y fusiona |
| **Memoria compartida** | Weights tabla central, todos agentes consultan misma fuente |
| **Plan mode crítico** | Antes de UPDATE en `asset_subclass_weights` (admin), preview impacto: muestra delta scores top-100 candidatos |
| **MCP connectors** | Si en futuro queremos ingresar datos externos (foot-traffic Placer.ai, traffic Google), via MCP en lugar de scrapers ad-hoc |
| **Security-first** | UPDATE weights requiere JWT con role=admin; cambios auditados; trigger DB previene weights sum != 1 |
| **Eficiencia (Opus → Sonnet)** | Opus diseñó este plan + revisará PRs críticas; Sonnet ejecuta tareas atómicas |
| **Parallelism** | 3 procesos: scoring residential, scoring commercial, scoring land — todos contra el mismo `model_scores` table |

---

## 6. Margenes de seguridad

### 6.1 Backwards compatibility

- `model_scores.opportunity_score` (la columna actual) **NO se modifica**.
- `subclass_scores` JSONB es **aditivo**.
- Frontend antiguo (sin SubclassSelector) sigue funcionando con `opportunity_score` legacy.

### 6.2 Rollback plan

```bash
# Rollback completo (si algo va mal)
psql -d re_cl -c "ALTER TABLE model_scores DROP COLUMN subclass_scores;"
psql -d re_cl -c "DROP TABLE asset_subclass_weights CASCADE;"
psql -d re_cl -c "DROP INDEX IF EXISTS idx_subclass_scores_gin;"
```

### 6.3 Performance budget

- Score subclass para 600k candidatos × 14 subclases = 8.4M cells.
- Computación bulk con NumPy vectorizado: < 30 segundos esperado.
- Si demora > 60s, optimizar con `numba.njit`.
- Frontend HeatmapLayer con 600k puntos: WebGL natively handles. Si lag, agregar viewport-based filter.

### 6.4 Validación pre-deploy

```bash
# 1. Tests pasan
py -m pytest tests/test_subclass*.py -v

# 2. Trigger DB previene weights inválidos
psql -c "INSERT INTO asset_subclass_weights ... w_underval=2.0 ..."  # debe fallar

# 3. Smoke test API
curl http://localhost:8000/subclasses | jq '.[0]'
curl http://localhost:8000/subclasses/apartment_income/heatmap?limit=10 | jq

# 4. Verificar score consistency
# El score subclass="default-equivalent" debe ≈ opportunity_score legacy ± 0.05
```

---

## 7. Plan de ejecución autónoma

Si Sonnet ejecuta este plan **sin supervisión**, el orden es:

```
[1] Migration 014 (CREATE TABLE + seed) ────────┐
[2] Migration 015 (ALTER model_scores)          │ Paralelo (independientes)
[3] src/scoring/asset_subclass.py module ───────┘
                ↓
[4] Run subclass_scorer.py contra DB (poblar JSONB)
                ↓
[5] Tests pytest (validación atómica)
                ↓
[6] FastAPI /subclasses routes (3 endpoints + auth admin)
                ↓
[7] Frontend SubclassSelector + SubclassHeatmap
                ↓
[8] HomeShell integration + Zustand state
                ↓
[9] STATE.md / CLAUDE.md update + memory persist
```

**Tiempo total estimado:** 4-6 horas de Sonnet sin interrupciones.

---

## 8. Métricas de éxito

| Métrica | Target |
|---------|--------|
| Subclases con weights válidos | 14/14 |
| Candidatos scoreados (≥1 subclass score) | ≥ 95% |
| Tiempo computación bulk | < 60s |
| Tiempo respuesta API /heatmap | < 500ms (p95) |
| Tests passing | 100% |
| Build size frontend | < +50KB vs baseline |
| User can switch subclass in UI in | < 200ms |

---

## 9. Riesgos identificados

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|-----------|
| Métricas A1-A3 incompletas para subclase nueva | Media | Alto | Default 0.0 + fallback a `opportunity_score` legacy |
| Weights mal balanceados (overfitting comercial vs residencial) | Alta | Medio | Validación A/B con dataset histórico (3.1 auto-tuning) |
| Frontend HeatmapLayer lento con 600k puntos | Baja | Medio | Viewport-based query + clustering en backend |
| Confusion usuario "subclase vs perfil inversionista" | Alta | Bajo | Onboarding: 1 frase explicativa; tooltip con ejemplo |

---

## 10. Próximos pasos inmediatos

1. ✅ Crear este documento (DONE)
2. ⏭ Sonnet ejecuta FASE 1 atómica:
   - `db/migrations/014_asset_subclass_weights.sql`
   - `db/migrations/015_subclass_scores_jsonb.sql`
   - `src/scoring/asset_subclass.py`
3. ⏭ Sonnet ejecuta FASE 2 frontend
4. ⏭ Tests + smoke validation
5. ⏭ STATE.md update

---

*Plan generado con Opus 4.7 · 2026-05-02 · v1.0 · Subclass-Aware Scoring + Heatmap Multi-Dimensional + Multi-Agent + Security-First*
