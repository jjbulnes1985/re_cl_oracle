# PROMPT MAESTRO — RE_CL UX Simplification (Phase 3)

> **Para sesión Opus 4.7 + Sonnet 4.6 (mixto).** Diseño con Opus, ejecución con Sonnet.
> Misión: tomar el Opportunity Engine v2 (829k candidatos, 7 use cases, 6 endpoints API, tab "Oportunidades") y **convertirlo en una plataforma usable por un inversionista no-técnico en menos de 60 segundos**.

---

## 1. CONTEXTO — qué tenemos hoy

**Backend (sólido):**
- 829,336 candidatos · 1.6M valuaciones (3 métodos triangulados) · 7 use cases scored
- 8,043 competidores OSM · accessibility real (BallTree sobre 116k puntos de vías)
- API FastAPI con 6 endpoints `/opportunity/*`
- Modelo XGBoost R²=0.6850 + comparables zonales

**Frontend (funcional pero no simple):**
- Tab "Oportunidades" como 9no tab de un dashboard de 9 tabs
- Sidebar con 3 dropdowns + slider + lista
- Ficha lateral al hacer click — densa, mucho texto
- Botón CSV export

**El problema:** la plataforma sigue **pensada para data scientists**, no para un inversionista que quiere comprar una propiedad.

---

## 2. PRINCIPIOS DE SIMPLIFICACIÓN

### El test de los 5 segundos
Un usuario nuevo abre la app y en 5 segundos debe entender:
- Qué encontró el sistema
- Cuál es la mejor oportunidad
- Cuánto cuesta y cuánto ahorra

### El test de los 60 segundos
En 60 segundos debe poder:
- Filtrar por su criterio (zona / tipo / presupuesto)
- Ver el top 3 con detalle suficiente para decidir si lo guarda
- Guardar uno favorito o exportar

### Las 3 reglas
1. **Una pantalla, una decisión.** Cada vista debe tener una sola acción primaria obvia.
2. **Lenguaje del inversionista, no del modelo.** "Bajo valor", no "undervaluation_score". "UF descuento", no "gap_pct".
3. **Riesgos antes del upside.** Sin excepciones. La banda de precio se muestra antes que el "máximo pagable".

---

## 3. INSPIRACIÓN — qué copiar de plataformas world-class

### Zillow / Redfin (US)
- **Hero card por propiedad:** foto grande + precio + dirección + 3 datos clave (m², dorms, baños). NADA más en la card.
- **Score visual simple:** "Hot Home" badge en lugar de un número 0-100.
- **Comparables automáticos:** "Esta casa está 12% bajo el promedio de la zona" — frase, no porcentile.

### Idealista (España)
- **Mapa como pantalla principal.** Filtros como overlays sobre el mapa, no en un panel lateral.
- **Pin con precio.** Cada pin muestra el precio directamente — no un dot abstracto.
- **Drill-down progresivo:** click en pin → preview pequeño → click en preview → ficha completa.

### Toctoc (Chile)
- **Buscador único de texto libre.** "Casa en Maipú menos de 5000 UF" → entiende intent.
- **Comparable display nativo en CL:** UF (no CLP), m² útil/total, comuna, año.

### Spotahome / Houzz (premium UX)
- **Storytelling en la ficha:** no datos sueltos. Una narrativa: "Este terreno en Maipú tiene 18% de descuento por estar en una calle interior, pero está a 200m de Avenida Pajaritos".

---

## 4. DIAGNÓSTICO ACTUAL — friction points

### En el sidebar
- "Score min: 60" → un usuario nuevo no sabe qué es score mínimo. **Fix:** "Solo top oportunidades", "Cualquier oportunidad", "Sin filtro" como toggle de 3 estados.
- "Uso: Estación de servicio" mezcla casos de inversionista (comprar para reventa) con operador (operar el negocio). **Fix:** separar perfiles.
- 7 dropdowns de comuna sin búsqueda. **Fix:** autocomplete tipo "Maipú" → "Maipú · 27,203 propiedades · score promedio 0.34".

### En la lista
- Solo muestra `score / county / type / m² / UF` — todo igual de prominente. **Fix:** jerarquía visual: precio HUGE, comuna grande, score como badge color.
- 20 items sin paginación clara. **Fix:** "Mostrar siguientes 20" o scroll infinito real.

### En la ficha
- Muestra `gap_pct: -0.23`. Confuso. **Fix:** "**Esta propiedad está 23% bajo valor de mercado**".
- Banda p25-p50-p75 sin contexto. **Fix:** "Precio justo entre **12,500 y 16,800 UF** según comparables zona".
- "max_payable_uf" con disclaimer de cap rate proxy. **Fix:** mostrar solo en modo "operador comercial", esconder en modo "inversionista".
- Lista de DD muy genérica. **Fix:** checklist con links directos a DOM Maipú, certificado SII.

### En el mapa
- Actualmente NO hay mapa real renderizando — solo placeholder. **Fix crítico:** integrar Deck.gl con ScatterplotLayer real, color por score, size por surface_land_m2.

---

## 5. PROPUESTAS — 3 mejoras de alto impacto

### Mejora 1: Pantalla principal = mapa interactivo (no sidebar denso)

**Antes:**
```
[Sidebar 260px: filtros + lista 20 items] [Mapa placeholder]
```

**Después:**
```
[Mapa fullscreen con pins de precio directamente visibles]
[Floating: 1 search bar arriba + 3 chips de filtro abajo]
[Click en pin → mini-card overlay → click en mini-card → ficha lateral]
```

Implementación:
- `DeckMap.tsx` ya existe, reusar
- ScatterplotLayer con `getRadius` proporcional a `surface_land_m2`
- `getFillColor` por `opportunity_score` (verde-amarillo-rojo)
- IconLayer con texto "12.5k UF" sobre cada pin (top 50 visible por viewport)

### Mejora 2: Búsqueda inteligente con NLP simple

**Input:** `"casa Maipú menos de 5000 UF score alto"`

**Parser frontend:**
```ts
const filters = parseQuery(input)
// → { property_type: 'house', commune: 'Maipú', max_price: 5000, score_min: 0.7 }
```

Reglas simples (regex):
- `casa|departamento|local|terreno` → property_type
- `en (\w+)` → commune (fuzzy match con tabla COMMUNES)
- `menos de (\d+)` → max_price
- `score alto|top|alta oportunidad` → score_min: 0.7
- `cerca metro|cerca colegio` → flags spatial

### Mejora 3: Ficha narrativa (no datasheet)

**Antes:**
```
Score: 87
gap_pct: -0.23
estimated_uf: 14,200
p25_uf: 12,500
p75_uf: 16,800
max_payable_uf: 18,500
```

**Después:**
```
Av. Pajaritos 5432, Maipú

▓▓▓▓▓▓▓▓░░ Alta oportunidad

Esta casa de 89 m² en Maipú está 23% bajo el valor
de mercado. Comparables similares en la zona se
están vendiendo entre 12,500 y 16,800 UF. El precio
estimado justo es 14,200 UF.

📍 A 200m de Avenida Pajaritos (vía estructurante)
🏢 Subutilizada — terreno de 250 m² con poca construcción
📊 17 propiedades transadas en 1km en los últimos 24 meses

⚠ Antes de comprar:
  □ Verificar uso permitido (DOM Maipú)
  □ Solicitar certificado de hipotecas (CBR)
  □ Tasación independiente

[Ver en Google Maps]  [Guardar]  [Descargar PDF]
```

---

## 6. ROADMAP EJECUTABLE — 6 horas

```
HORA 1 — DeckMap real con pins por score
  ├─ ScatterplotLayer + IconLayer
  ├─ Filtros como floating chips (no sidebar)
  └─ Click handler → mini-card overlay

HORA 2 — Búsqueda NLP simple
  ├─ Parser regex frontend
  ├─ UI: input único arriba, chips abajo con filtros activos
  └─ Botón "X" para limpiar filtros

HORA 3 — Ficha narrativa
  ├─ Generador de oraciones desde drivers JSON
  ├─ Layout 2-col: izquierda mapa pequeño, derecha texto
  └─ DD checklist con links externos

HORA 4 — Modo "Inversionista" vs "Operador"
  ├─ Toggle arriba: 🏠 Compra para inversión / 🏪 Operar negocio
  ├─ Cambia filtros visibles + esconde max_payable en modo inversionista
  └─ Persiste en Zustand

HORA 5 — Pulido visual
  ├─ Tipografía jerarquizada (Inter o similar)
  ├─ Loading skeletons
  ├─ Animaciones suaves (Framer Motion)
  └─ Modo claro/oscuro

HORA 6 — User testing simulado
  ├─ Test 5 segundos (heatmap visual)
  ├─ Test 60 segundos (flujo completo)
  ├─ Documentar fricciones encontradas
  └─ Iteración inmediata sobre top 3
```

---

## 7. CRITERIOS DE VALIDACIÓN

- [ ] Usuario nuevo encuentra "casa Maipú score alto" en <60s
- [ ] Mapa fullscreen sin scroll para los filtros principales
- [ ] Ficha tiene narrativa, no datasheet
- [ ] Riesgos visibles antes que oportunidades en cada vista
- [ ] Disclaimer cap rate visible solo en modo "operador"
- [ ] Búsqueda libre acepta queries en español natural
- [ ] Funciona en mobile (responsive)
- [ ] Pinta primer pixel en <2 segundos (perceived performance)

---

## 8. PRINCIPIO INSTITUCIONAL — qué NO simplificar

Hay cosas que **no deben simplificarse** aunque parezca tentador:

1. **Bandas de precio** — siempre p25-p50-p75, nunca un solo número
2. **Disclaimer cap rate** — nunca esconder el `INFO_NO_FIDEDIGNA`
3. **Riesgos primero** — nunca mover la sección de riesgos abajo del upside
4. **Versión del modelo** — siempre visible en el footer (small)
5. **Trazabilidad** — cada número con tooltip "según comparables zonales 24m"

La simplificación es para **reducir fricción**, no para **ocultar incertidumbre**.

---

## 9. INSTRUCCIÓN AL EJECUTOR

1. Leer `prompts/opportunity_engine_design.md` y `prompts/opportunity_engine_execute.md` para contexto
2. Ejecutar las 6 horas en orden
3. Hacer commit por hora con prefijo `feat(ux):`
4. Al final, generar 3 capturas de pantalla del flujo:
   - Pantalla principal con mapa
   - Resultado de búsqueda
   - Ficha narrativa
5. Actualizar CLAUDE.md y RE_CL.md con la sección "UX Phase 3"
6. NO push remoto sin autorización explícita

---

*Prompt generado con Opus 4.7 · 2026-04-30 · v3.0 · Listo para Sonnet*
