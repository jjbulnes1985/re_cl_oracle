# PROMPT DE EJECUCIÓN — RE_CL Opportunity Engine v2

> **Para usar en una sesión Claude Sonnet 4.6 (modo cost-efficient).** Pegar este prompt completo. NO requiere intervención humana en cada paso — el flujo es autónomo, salvo errores críticos.

---

## CONTEXTO MÍNIMO

Eres el ingeniero de implementación de **RE_CL Opportunity Engine v2**, un motor de detección de oportunidades de compra inmobiliaria para Chile RM. Lee primero el diseño maestro:

📄 [`prompts/opportunity_engine_design.md`](opportunity_engine_design.md) — **Lee este archivo antes de empezar. Contiene schema, fórmulas de scoring, hallazgos de investigación (cap rates, regulación SEC, competidores Chile), y plan de 8 horas.**

Stack confirmado:
- PostgreSQL 15 + PostGIS (ya levantado)
- Python 3.13, SQLAlchemy, XGBoost, GeoPandas
- FastAPI (extender la app existente en `re_cl/src/api/`)
- React + Deck.gl (extender frontend en `re_cl/frontend/`)
- DB tiene 1,429,036 transactions_raw, 824,333 transactions_clean, 5,003 scraped_listings

---

## REGLAS OPERATIVAS

1. **Modo SAFE = ejecutar sin pedir confirmación.** Estas acciones se hacen directo:
   - Crear archivos nuevos (`/migrations/014_*.sql`, `/src/opportunity/*.py`, etc.)
   - Crear schemas / tablas / vistas / índices
   - Insertar datos derivados (ingesta de competidores OSM, ETL desde tablas existentes)
   - ETL desde tablas existentes (transactions_clean → candidates)
   - Tests locales, dry runs
   - Commits atómicos por paso (`feat(opportunity): step N - description`)

2. **Modo NEEDS APPROVAL = pedir confirmación SOLO si:**
   - Truncar / drop tablas existentes (transactions_*, model_scores, etc.)
   - Modificar schema de tablas de producción ya en uso
   - Lanzar scrapers que consuman quota externa
   - Llamar APIs pagadas
   - Push a remote (se queda local hasta confirmar)

3. **No inventes datos.** Si falta una variable, marca `DUDA::descripción` en código y output.

4. **Trazabilidad obligatoria:** cada número en outputs lleva fuente. Cap rates llevan disclaimer `INFO_NO_FIDEDIGNA::pendiente_validación` con banda ±150 bps.

5. **Test 60 segundos:** la UI debe permitir a un usuario nuevo encontrar "casa para invertir en Maipú con score >80" en menos de 60 segundos sin leer instrucciones.

---

## EJECUCIÓN — 8 HORAS

### HORA 1 — Schema + setup

```
1.1 Crear archivo: re_cl/db/migrations/014_opportunity_engine.sql
    Contenido: SQL completo del diseño v2 (sección 1 del design doc).
    Incluye: schema opportunity, 7 tablas (property_types, investor_profiles,
    candidates, valuations, scores, risks, competitors, model_versions),
    índices GIST/B-tree, vista v_top_opportunities.

1.2 Aplicar migración:
    psql $DATABASE_URL -f re_cl/db/migrations/014_opportunity_engine.sql

1.3 Verificar:
    py -c "
    from sqlalchemy import create_engine, text; import os
    e = create_engine(os.getenv('DATABASE_URL'))
    with e.connect() as c:
        r = c.execute(text(\"SELECT COUNT(*) FROM opportunity.property_types\"))
        assert r.scalar() == 13, f'expected 13 property types, got {r.scalar()}'
        r = c.execute(text(\"SELECT COUNT(*) FROM opportunity.investor_profiles\"))
        assert r.scalar() == 6, f'expected 6 profiles'
    print('Hora 1 OK')
    "

1.4 Commit: feat(opportunity): hour 1 - schema + catalogs (13 types, 6 profiles)
```

**Métrica de éxito:** schema `opportunity` creado, 7 tablas + vista, 13 property_types + 6 investor_profiles seeded.

---

### HORA 2 — Ingesta candidatos desde fuentes existentes

```
2.1 Crear: re_cl/src/opportunity/__init__.py (vacío)
2.2 Crear: re_cl/src/opportunity/ingest_candidates.py

   Lógica:
   - Source A (cbr_transaction): SELECT * FROM transactions_clean
     INSERT INTO opportunity.candidates con:
       source='cbr_transaction', source_id=str(tc.id),
       property_type_code = map_to_opportunity_type(tc.project_type),
       last_transaction_uf = tc.uf_value,
       last_transaction_date = tc.inscription_date,
       construction_ratio = surface_building / NULLIF(surface_land, 0)

   - Source B (scraped_listing): SELECT * FROM scraped_listings
     INSERT INTO opportunity.candidates con:
       source='scraped_listing', source_id=str(sl.id),
       listed_price_uf = sl.price_uf,
       listed_at = sl.scraped_at,
       property_type_code = map_to_opportunity_type(sl.property_type)

   - Marcar is_eriazo:
     UPDATE opportunity.candidates
     SET is_eriazo = TRUE
     WHERE surface_land_m2 >= 500
       AND COALESCE(construction_ratio, 0) < 0.10;

2.3 Mapeo de project_type → opportunity.property_types.code:
   - 'apartments' → 'apartment'
   - 'residential' → 'house'
   - 'retail' → 'retail'
   - 'unknown' → 'land' (heurística: si surface_land > surface_building*5, es land)
   - default: pasar tal cual si existe en property_types, sino 'land'

2.4 Verificar:
    SELECT source, COUNT(*) FROM opportunity.candidates GROUP BY source;
    -- Expected: cbr_transaction ~824k, scraped_listing ~5k

    SELECT COUNT(*) FROM opportunity.candidates WHERE is_eriazo = TRUE;
    -- Expected: ~5,000-15,000 (terrenos eriazos detectados)

2.5 Commit: feat(opportunity): hour 2 - ingest 829k candidates from CBR + listings
```

**Métrica de éxito:** ~829k candidatos en `opportunity.candidates`, ≥5k marcados como eriazo.

---

### HORA 3 — Ingesta competidores existentes

```
3.1 Crear: re_cl/src/opportunity/ingest_competitors.py

3.2 OSM Overpass query para 4 use cases:
    use_cases = {
        'gas_station': '["amenity"="fuel"]',
        'pharmacy':    '["amenity"="pharmacy"]',
        'bank_branch': '["amenity"="bank"]',
        'supermarket': '["shop"="supermarket"]'
    }

    Query Overpass por cada uno (RM bbox: -33.7,-71.0 a -33.3,-70.4):
    [out:json];
    (
      node["amenity"="fuel"](-33.7,-71.0,-33.3,-70.4);
      way["amenity"="fuel"](-33.7,-71.0,-33.3,-70.4);
    );
    out center;

3.3 Para cada feature OSM:
    - Extraer brand/operator → mapear a operator canonical
      (Copec, Shell, Aramco/Esmax/Petrobras, Cruz Verde, Salcobrand,
       Banco Estado, BCI, Santander, Tottus, Lider, Jumbo, Unimarc)
    - Insertar en opportunity.competitors con geom

3.4 Datos abiertos SEC para gas stations (opcional, mejor cobertura):
    URL: https://datosabiertos.sec.cl/dataset/instalaciones-de-combustibles-liquidos
    DUDA::URL_exacta_dataset_SEC — verificar y descargar CSV.

    Si no disponible programáticamente: usar solo OSM y marcar
    DUDA::cobertura_SEC_pendiente

3.5 Verificar:
    SELECT use_case, COUNT(*) FROM opportunity.competitors GROUP BY use_case;
    -- Expected approximate (RM Santiago):
    --   gas_station ~250-400
    --   pharmacy ~600-1000
    --   bank_branch ~400-700
    --   supermarket ~150-300

3.6 Commit: feat(opportunity): hour 3 - ingest 1500+ competitors from OSM
```

**Métrica de éxito:** ≥1,000 competidores en RM con geom + operator canonical.

---

### HORA 4 — Motor de valoración multi-método

```
4.1 Crear: re_cl/src/opportunity/valuation_engine.py

    Funciones:
    - hedonic_value(candidate) → usa modelo XGBoost actual (models/hedonic_model_v1.pkl).
      Retorna estimated_uf_m2 + confidence.

    - comparables_value(candidate) → SQL:
      SELECT percentile_cont(ARRAY[0.25, 0.5, 0.75]) WITHIN GROUP (ORDER BY uf_m2_building)
      FROM transactions_clean
      WHERE county_name = :commune
        AND project_type = :type
        AND ABS(surface_m2 - :surface) / :surface < 0.30
        AND inscription_date >= NOW() - INTERVAL '24 months'
      LIMIT 1;

    - dcf_value(candidate, use_case) → solo si use_case en COMMERCIAL_USE_CASES.
      Renta proyectada 10 años (renta inicial → growth 3% anual) + valor terminal
      / WACC (8% default). DUDA::renta_directa_<use_case> si no hay comparable.

    - cap_inverse_value(candidate, use_case) → solo si comercial.
      noi = estimate_noi(candidate, use_case)  # banda baja-central-alta
      cap_low, cap_mid, cap_high = property_types[use_case].cap_rates
      Retorna 3 valores: low/mid/high para sensibilidad.

    - triangulate(candidate, use_case) → mediana de los métodos disponibles.
      p25/p75 de la distribución de los métodos.
      confidence = 1 - normalized_range.

4.2 Crear función estimate_noi simple por use_case:
    def estimate_noi(candidate, use_case):
        # Banda en UF/año (de la investigación previa)
        bands = {
            'gas_station':  (4000, 7000, 12000),
            'pharmacy':     (800, 1500, 3000),
            'supermarket':  (5000, 12000, 25000),
            'bank_branch':  (1500, 3000, 6000),
            'retail':       (500, 1200, 3000),
        }
        # Ajuste por superficie y comuna (heurística simple v1)
        ...

4.3 Ejecutar valoración para subset (solo candidatos con score>0.4 o is_eriazo):
    Para candidatos restantes, valoración hedónica básica.

4.4 INSERT en opportunity.valuations:
    - method='hedonic_xgb'
    - method='comparables'
    - method='triangulated' (siempre)

4.5 Verificar:
    SELECT method, COUNT(*) FROM opportunity.valuations GROUP BY method;

4.6 Commit: feat(opportunity): hour 4 - multi-method valuation engine
```

**Métrica de éxito:** ≥100k valoraciones triangulated escritas, banda p25-p75 calculada.

---

### HORA 5 — Scoring base (todos los candidatos, profile=value)

```
5.1 Crear: re_cl/src/opportunity/scoring_base.py

    Reusar mucha lógica de re_cl/src/scoring/opportunity_score.py existente.

    Para cada candidato:
    - undervaluation_score: percentile rank de gap_pct vs valoración triangulada
    - location_score: 1 - normalize(dist_km_centroid)
    - growth_score: percentile rank de commune.growth_index
    - confidence: data_confidence de transactions_clean
    - opportunity_score: weighted sum según investor_profile='value'

5.2 Insertar en opportunity.scores con use_case='as_is', investor_profile='value'

5.3 Verificar:
    SELECT
      COUNT(*) FILTER (WHERE opportunity_score >= 0.8) AS high_op,
      COUNT(*) FILTER (WHERE opportunity_score >= 0.6) AS medium_op,
      COUNT(*) AS total
    FROM opportunity.scores WHERE use_case='as_is' AND investor_profile='value';

5.4 Commit: feat(opportunity): hour 5 - base scoring (value profile, 824k candidates)
```

**Métrica de éxito:** ≥800k scored, ≥50k con opportunity_score ≥ 0.8.

---

### HORA 6 — Scoring uso comercial: gas_station (con validación cruzada)

```
6.1 Crear: re_cl/src/opportunity/scoring_gas_station.py

    Para cada candidato con surface_land_m2 ≥ 500 en RM:

    a. accessibility_score:
       Distancia OSM trunk/primary roads.
       0 dist=0m → 1.0; dist=2km → 0.0; lineal entre.

    b. demand_score:
       Densidad poblacional INE 1km radio (commune_ine_census ya en DB).
       Normalizado por p10-p90 de la RM.

    c. competition_score (clave):
       n_competitors_2km = ST_DWithin(candidate.geom, competitor.geom, 2000)
       zonal_p25, zonal_p75 = percentiles de density por commune
       Si n < p25 → 1.0 (under-served)
       Si n > p75 → 0.0 (over-saturated)
       Sino: lineal

    d. zoning_score:
       Por ahora 1.0 default. DUDA::zonificación_PRC_Maipú.
       Marcar para fase 2 con scraping de PRC comunal.

    e. use_specific_score = combine(a, b, c, d)
       weights: accessibility 0.30, demand 0.25, competition 0.30, zoning 0.15

    f. opportunity_score (operator profile):
       weights: use_specific 0.60, undervaluation 0.25, confidence 0.15

    g. max_payable_uf:
       cap inverso con cap_rate central, ajustado por confidence.

6.2 Insertar en opportunity.scores con use_case='gas_station',
    investor_profile='operator'

6.3 VALIDACIÓN CRUZADA (test crítico):
    a. Para cada gas_station existente en opportunity.competitors (Las Condes):
       - Encontrar el candidato más cercano (geom)
       - Verificar que gas_station_score >= 0.6 (alta)
    b. Calcular:
       correlation = corr(
         existence_density_500m,  # competidores en 500m
         use_specific_score
       )
    c. Reportar: si correlation >= 0.6 → modelo válido.
       Si < 0.6 → flag para revisar pesos. NO bloquear ejecución, pero documentar.

6.4 Output a stdout:
    "VALIDATION GAS STATION:"
    "  n_existing_in_top_decile: X / Y"
    "  correlation_score_vs_density: 0.XX"
    "  STATUS: VALID | NEEDS_REVIEW"

6.5 Commit: feat(opportunity): hour 6 - gas_station scoring + cross-validation
```

**Métrica de éxito:** ≥1,000 candidatos scored para gas_station, validación cruzada con corr ≥ 0.5.

---

### HORA 7 — API endpoints

```
7.1 Crear: re_cl/src/api/routes/opportunity.py

    @router.get("/opportunity/candidates")
    def list_candidates(
        use_case: str = "as_is",
        profile: str = "value",
        commune: Optional[str] = None,
        property_type: Optional[str] = None,
        score_min: float = 0.5,
        limit: int = 100,
        offset: int = 0,
    ):
        # SELECT desde opportunity.v_top_opportunities con filtros
        ...

    @router.get("/opportunity/candidates/{id}")
    def get_candidate(id: int):
        # Ficha completa: candidate + valuations + scores + risks
        ...

    @router.get("/opportunity/competitors")
    def list_competitors(use_case: str, commune: Optional[str] = None):
        ...

    @router.get("/opportunity/use-cases")
    def list_use_cases():
        # Catálogo property_types
        ...

    @router.get("/opportunity/profiles")
    def list_profiles():
        # Catálogo investor_profiles
        ...

7.2 Registrar router en re_cl/src/api/main.py:
    from src.api.routes.opportunity import router as opp_router
    app.include_router(opp_router, prefix="/opportunity", tags=["opportunity"])

7.3 Test rápido (con uvicorn corriendo en background):
    curl "http://localhost:8000/opportunity/candidates?use_case=as_is&commune=Maipú&score_min=0.7&limit=5"

7.4 Commit: feat(opportunity): hour 7 - API endpoints (5 endpoints)
```

**Métrica de éxito:** API responde en <500ms para queries típicas.

---

### HORA 8 — Frontend mínimo

```
8.1 Crear: re_cl/frontend/src/components/OpportunityPanel.tsx

    Reutilizar:
    - DeckMap.tsx (mapa base)
    - Sidebar pattern del Sidebar.tsx existente

    Layout:
    - Sidebar izquierda (250px):
        Search box (single)
        Type ▾ | Commune ▾ | Use case ▾
        Score min slider
        Top 10 list (renderizado desde API)
    - Main: DeckMap con ScatterplotLayer
        color por opportunity_score (verde→rojo)
        size por surface_land_m2
    - Click en pin → DetailPanel lateral derecho con ficha

8.2 Crear: re_cl/frontend/src/components/OpportunityDetailPanel.tsx
    Renderizado de ficha (ver design doc sección 5):
    - Banda de precio visual
    - Riesgos (semáforo)
    - Tesis (top 3 drivers)
    - Próximos pasos DD
    - Botones [Google Maps] [Ficha SII] [PDF]

8.3 Agregar tab "Oportunidades" en App.tsx (ya tiene 8 tabs, será la 9na).

8.4 npm run build (validar que no haya errores)

8.5 Test 60 segundos manual (documentar):
    Usuario abre /oportunidades →
    Selecciona "Maipú" en filtro comuna →
    Mueve slider score >= 0.8 →
    Ve top 10 → Click en primero → Ve ficha.
    DEBE TARDAR < 60 SEGUNDOS.

8.6 Commit: feat(opportunity): hour 8 - frontend OpportunityPanel + DetailPanel
```

**Métrica de éxito:** test 60 segundos pasa.

---

## CIERRE (después de hora 8)

```
1. Actualizar CLAUDE.md y RE_CL.md:
   Sección "Estado pipeline (2026-04-30)":
     + Tabla opportunity.candidates (~829k)
     + Tabla opportunity.scores (~830k base + ~1k gas_station)
     + 5 endpoints /opportunity/*
     + Tab "Oportunidades" en frontend

2. Generar reporte ejecutivo:
   py re_cl/src/reports/generate_opportunity_report.py --use=gas_station --commune=Maipú --top=20

   Output: data/exports/opportunity_gas_station_maipu_YYYY-MM-DD.html
   Estructura: Resumen → Riesgos → Tesis demanda → Valoración con bandas
              → Próximos pasos DD → DUDA:: pendientes.

3. Resumen final al usuario:
   - Schema creado: ✓
   - Candidatos ingestados: NN,NNN
   - Competidores cargados: NN
   - Valoraciones: NN,NNN
   - Scores base: NN,NNN
   - Scores gas_station: NN
   - Validación cruzada Las Condes: corr=0.XX
   - API endpoints: 5
   - Frontend tab: ✓
   - DUDA:: pendientes: lista
   - Commits creados: 8

4. NO hacer push remoto sin confirmación del usuario.
```

---

## DUDA:: que requieren confirmación humana o sesión Opus posterior

- `DUDA::URL_dataset_SEC_estaciones_combustibles` — verificar URL exacta y formato.
- `DUDA::zonificación_PRC_Maipú` — scraping plan regulador comunal pendiente para Fase 2.
- `DUDA::data_SII_geolocalizada` — solicitud Ley Transparencia (Fase 2).
- `DUDA::cap_rate_gas_station_Chile` — confirmar con tasador (Tinsa/GPS) en Fase 2.
- `DUDA::renta_terreno_gas_station_Santiago` — sin comparables públicos directos.
- `DUDA::NOI_gas_station_Chile` — proxies internacionales, validar con operador local.

---

## CHECKLIST FINAL ANTES DE TERMINAR

- [ ] Schema `opportunity.*` con 7 tablas + vista creado
- [ ] ≥800k candidatos ingestados con geom
- [ ] ≥1,000 competidores cargados
- [ ] ≥100k valoraciones triangulated
- [ ] ≥800k scores base (use_case='as_is', profile='value')
- [ ] ≥1,000 scores gas_station con validación Las Condes corr ≥ 0.5
- [ ] 5 endpoints API funcionando <500ms
- [ ] Frontend tab "Oportunidades" con test 60s
- [ ] CLAUDE.md y RE_CL.md actualizados
- [ ] Reporte ejecutivo HTML generado
- [ ] Lista de DUDA:: documentada
- [ ] 8 commits atómicos en master

---

*Prompt de ejecución generado con Opus 4.7 · 2026-04-30 · v2.0 · Listo para Sonnet*
