# PROMPT MAESTRO — Simplificación Radical UX (Phase 4)

> **Para sesión Opus 4.7 (diseño) + Sonnet 4.6 (ejecución).**
> Misión: que un inversionista chileno **sin formación técnica** pueda encontrar 3 oportunidades reales de inversión inmobiliaria en menos de **30 segundos** desde el primer click.

---

## 1. CONTEXTO — qué tenemos hoy

**Backend (no tocar):**
- API FastAPI funcional con 6 endpoints `/opportunity/*`
- 829k candidatos · 1.6M valuaciones · 7 use cases scored
- Modelo XGBoost + comparables zonales triangulados

**Frontend actual (a rediseñar desde cero):**
- Existe un tab "Oportunidades" pero es una mezcla de mapa + sidebar + filtros que abruma al usuario
- Búsqueda libre por texto que no es obvia
- Ficha lateral con demasiada información
- El usuario no entiende cómo filtrar ni qué significa cada cosa

**Diagnóstico explícito del usuario:**
> *"la plataforma no cambió en nada. muy compleja de entender. quiero que un experto en diseño y orquestador me ayude a variabilizar las variables dentro de la página y que sea extremadamente simple buscar oportunidades."*

Esto significa:
- **Variabilizar las variables** = todo dato del backend (precio, m², score, descuento, comuna, tipo) debe ser un filtro UI obvio y manipulable
- **Extremadamente simple** = sin texto libre, sin jerga técnica, sin scroll horizontal, sin paneles superpuestos
- **Buscar oportunidades** = el flujo principal debe ser una decisión de filtros → mapa → click → comprar/guardar

---

## 2. PRINCIPIOS DE DISEÑO — no negociables

### El test de los 3 segundos
Al abrir la página el usuario debe ver:
- Un **mapa de Santiago** dominando la pantalla
- Pins coloreados (verde/amarillo/rojo) por nivel de oportunidad
- Una **barra de filtros visibles** arriba (no escondidos en menús)
- Sin tutoriales, sin onboarding, sin texto de bienvenida

### El test de los 30 segundos
En 30 segundos cualquier usuario debe poder:
1. Filtrar por comuna (1 click)
2. Filtrar por presupuesto máximo (1 slider)
3. Filtrar por tipo (1 grupo de chips)
4. Ver el top 5 inmediatamente en el mapa Y en una lista
5. Hacer click en uno y ver una **ficha de 1 sola pantalla** con la decisión obvia: "Esta propiedad está X% bajo valor de mercado, vale Y UF"

### Las 5 reglas absolutas

1. **Cero texto libre.** Todos los filtros son sliders, dropdowns o chips. El usuario no escribe nunca.
2. **Cero jerga.** Reemplazar `score`, `gap_pct`, `cap_rate` por palabras humanas: "ahorro estimado", "precio justo", "rentabilidad esperada".
3. **Cero scroll en la pantalla principal.** Todo cabe en 1 viewport (1920×1080 mínimo).
4. **Una decisión por vista.** No mezclar buscar + comparar + guardar en la misma pantalla.
5. **El mapa es el héroe.** 70% del espacio. Filtros y lista son satélites.

---

## 3. INSPIRACIÓN — qué copiar literal

### Idealista.com (España) — referencia principal
- Mapa fullscreen como pantalla home
- Filtros como **chips arriba**: precio, habitaciones, m², zona
- Click en chip → dropdown con opciones simples
- Pin con **precio directo** (no abstracto)
- Click en pin → preview pequeño emerge sobre el mapa → click en preview → ficha completa

### Zillow.com (US)
- "Hot Home" badge en lugar de score numérico
- Slider de precio con histograma de distribución
- Filtros guardados con 1 click ("Mis búsquedas")

### Toctoc.com (Chile)
- Mapa + lista lado a lado (no encima)
- Cards de propiedad grandes con foto + precio + 3 datos
- Comparación rápida marcando 2 propiedades

### Notion / Linear (UX simple en general)
- Atajos de teclado: `/` para buscar, `Cmd+K` para todo
- Comandos rápidos visibles ("Press / to filter")
- Animaciones suaves pero no decorativas

---

## 4. VARIABLES A VARIABILIZAR — checklist exhaustivo

Cada variable del backend debe tener un **control visual** en el frontend:

### Variables de filtro (obligatorias visibles)

| Variable backend | Control UI | Default |
|------------------|-----------|---------|
| `commune` | Dropdown con autocomplete + chips de comunas seleccionadas | "Toda RM" |
| `property_type_code` | Chips icon: 🏠 Casa · 🏢 Depto · 🌳 Terreno · 🏪 Local · 🏭 Industrial | Todos |
| `surface_land_m2` (rango) | Slider doble (min-max) en m² | 0–10000 |
| `last_transaction_uf` (rango) | Slider doble (min-max) en UF | 0–50000 |
| `opportunity_score` (umbral) | Toggle 3 estados: Cualquiera / ⭐ Buena / 🔥 Top | Cualquiera |
| `is_eriazo` | Toggle on/off "Solo terrenos subutilizados" | off |
| `use_case` (modo operador) | Solo en modo "Operador": chips por uso comercial | gas_station |

### Variables de display (siempre visibles en pin/card)

| Variable | Display |
|----------|---------|
| `estimated_uf` | Precio grande "12,500 UF" |
| `gap_pct` | "20% bajo valor" o "5% sobre valor" en color |
| `surface_land_m2` | "250 m² terreno" |
| `county_name` | Comuna en bold |
| `property_type_code` | Icono + label |
| `is_eriazo` | Badge "Subutilizado" si TRUE |

### Variables ocultas (solo en ficha detallada)

- `confidence`, `valuation_confidence` → "Confianza alta/media/baja"
- `max_payable_uf` → solo modo operador, con disclaimer
- `n_competitors_2km` → "X competidores cerca"
- `drivers` JSONB → tooltips opcionales

---

## 5. ESTRUCTURA DE PANTALLA — wireframe ASCII

### Pantalla principal (TODO lo importante en un viewport)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  RE_CL Oportunidades                              [Inversión][Operador]      │  ← Header 50px
├──────────────────────────────────────────────────────────────────────────────┤
│  📍 Comuna ▾   🏠 Tipo ▾   💰 Precio ▾   📐 Tamaño ▾   ⭐ Score: Top  [✕]   │  ← Filter bar 50px
├──────────────────────────────────────────────────────────────────────────────┤
│                                                          ┌─────────────────┐ │
│                                                          │ 1. Maipú        │ │
│                                                          │   12,500 UF     │ │
│                                                          │   20% bajo  🟢  │ │
│                                                          ├─────────────────┤ │
│   [MAPA DECK.GL FULLSCREEN]                              │ 2. La Florida   │ │
│   - Pins con precio directo                              │   18,200 UF     │ │
│   - Color por score                                      │   15% bajo  🟢  │ │
│   - Tamaño por terreno                                   ├─────────────────┤ │
│   - Click → preview                                      │ 3. Ñuñoa        │ │
│                                                          │   25,800 UF     │ │
│                                                          │   12% bajo  🟡  │ │
│                                                          ├─────────────────┤ │
│                                                          │ ... (scroll)    │ │
│                                                          └─────────────────┘ │
├──────────────────────────────────────────────────────────────────────────────┤
│  248 oportunidades encontradas · Promedio descuento 18%   [Exportar][Guardar]│  ← Footer 40px
└──────────────────────────────────────────────────────────────────────────────┘
   ↑ Filtros en chips arriba         ↑ Mapa centro                ↑ Lista derecha 280px
```

### Click en pin → preview emerge (no panel lateral)

```
┌─────────────────────────────────┐
│  Maipú · Casa 250m²            │
│  ─────────────────────────────  │
│  💰 12,500 UF                   │
│  📉 20% bajo valor de mercado   │
│  🟢 Alta oportunidad            │
│  ─────────────────────────────  │
│  [Ver detalle]  [Guardar]  [×]  │
└─────────────────────────────────┘
```

### Click en "Ver detalle" → ficha 1 pantalla (no scroll)

```
┌──────────────────────────────────────────────────────────────┐
│  ← Volver                                                    │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│   📍 Av. Pajaritos 5432, Maipú                  Score: 87    │
│                                                              │
│   ┌─────────────────────┬──────────────────────────────────┐ │
│   │                     │  💰 Precio justo                  │ │
│   │   [MINI MAPA]       │     12,500 UF (rango 10k–15k)     │ │
│   │   con pin           │                                   │ │
│   │                     │  📉 20% bajo valor de mercado     │ │
│   │                     │                                   │ │
│   │                     │  🏠 Casa · 250 m² terreno         │ │
│   │                     │     • A 200m de Av. Pajaritos     │ │
│   │                     │     • Año construcción: 1995      │ │
│   │                     │     • Subutilizada (terreno alto) │ │
│   └─────────────────────┴──────────────────────────────────┘ │
│                                                              │
│   ⚠ Antes de comprar:                                        │
│      ☐ Verificar uso permitido (DOM Maipú)                  │
│      ☐ Solicitar certificado de hipotecas (CBR)             │
│      ☐ Tasación independiente                               │
│                                                              │
│   [Ver en Google Maps]  [Guardar]  [Descargar PDF]          │
└──────────────────────────────────────────────────────────────┘
```

---

## 6. CONTROLES DETALLADOS — comportamiento exacto

### Filtro: 📍 Comuna
- Click → dropdown con buscador interno
- Lista las 40 comunas RM ordenadas por nº oportunidades
- Multi-selección (chips abajo del filtro)
- "Toda RM" como default

### Filtro: 🏠 Tipo
- Click → menú con 5 chips icon
- Default: todos seleccionados
- Click en chip → toggle on/off

### Filtro: 💰 Precio
- Click → slider doble con histograma de distribución debajo
- Rango: 0 — 50,000 UF
- Mostrar "1.2k–18.5k UF" en el botón cuando hay valores

### Filtro: 📐 Tamaño
- Click → slider doble en m² terreno
- Rango: 0 — 10,000 m²
- Cuadrícula visual (chip "≤ 100 m²", "100–500 m²", etc.) opcional

### Filtro: ⭐ Score
- 3 estados toggle:
  - Cualquiera (default)
  - ⭐ Buena (score ≥ 0.6)
  - 🔥 Top (score ≥ 0.75)

### Botón: [✕] Limpiar
- Reset todos los filtros al default

### Toggle: 🏠 Inversión / 🏪 Operador
- Modo Inversión: filtros = comuna, tipo, precio, tamaño, score
- Modo Operador: agrega selector de uso (gas_station, pharmacy, etc.) y muestra `max_payable_uf`

---

## 7. INTERACCIONES — 30 segundos en detalle

```
Segundo 0   → Usuario abre /oportunidades
Segundo 2   → Ve mapa con pins, lista con top oportunidades
Segundo 5   → Click en chip "📍 Comuna" → selecciona "Maipú"
Segundo 10  → Pins se filtran instantáneamente, lista se actualiza
Segundo 15  → Click en chip "💰 Precio" → arrastra slider a "5,000–15,000 UF"
Segundo 20  → Click en pin más grande del mapa → preview emerge
Segundo 25  → Click en "Ver detalle" → ficha 1 pantalla
Segundo 30  → Decide: guardar, descargar PDF, ir a Google Maps
```

---

## 8. ROADMAP EJECUTABLE — 8 horas

```
HORA 1 — Wireframe + componentes base
  ├─ Filter bar component (responsive, sticky)
  ├─ Map component (Deck.gl fullscreen)
  └─ Sidebar list component (cards verticales)

HORA 2 — Filtros funcionales
  ├─ ComunaFilter: dropdown con autocomplete + multi-select
  ├─ TipoFilter: chips con iconos
  └─ Estado global con Zustand (no useState)

HORA 3 — Sliders complejos
  ├─ PrecioFilter: range slider + histograma
  ├─ TamañoFilter: range slider con presets
  └─ ScoreFilter: toggle 3 estados

HORA 4 — Mapa interactivo
  ├─ ScatterplotLayer + TextLayer con precio
  ├─ Click handler con preview overlay
  └─ Auto-fit bbox al filtrar comuna

HORA 5 — Lista lateral
  ├─ Card design: comuna + precio + descuento + score visual
  ├─ Hover sync con mapa (highlight pin)
  └─ Click → mismo behavior que pin

HORA 6 — Ficha de detalle
  ├─ Layout 2-col: mini-mapa + datos
  ├─ Riesgos primero (regla institucional)
  └─ Botones de acción [Maps] [Guardar] [PDF]

HORA 7 — Polish
  ├─ Loading skeletons
  ├─ Empty state cuando no hay resultados
  ├─ Animaciones (Framer Motion)
  └─ Mobile responsive (sidebar → bottom sheet)

HORA 8 — User testing simulado
  ├─ Test 3 segundos (heatmap visual)
  ├─ Test 30 segundos (flujo completo)
  ├─ Documentar fricciones
  └─ Iterar top 3
```

---

## 9. CRITERIOS DE VALIDACIÓN

- [ ] **Test 3 segundos:** usuario nuevo sabe qué ve y dónde clicar
- [ ] **Test 30 segundos:** filtra por comuna + precio + score y abre detalle
- [ ] **Cero scroll** en pantalla principal (1920×1080)
- [ ] **Cero jerga técnica** visible (no "score", no "gap_pct")
- [ ] **Mobile usable** (375px width)
- [ ] **Filtros responsivos** (<200ms para actualizar mapa)
- [ ] **Riesgos antes que upside** en cada vista
- [ ] **Disclaimer cap rate** solo en modo Operador, siempre visible

---

## 10. STACK TÉCNICO — qué reusar, qué reemplazar

**Reusar:**
- `DeckGL`, `ScatterplotLayer`, `TextLayer` (ya integrados)
- `useQuery` de TanStack Query
- API endpoints `/opportunity/*`
- Zustand store

**Reemplazar:**
- ❌ Búsqueda libre con NLP → ✅ Filtros visuales
- ❌ Ficha lateral con scroll → ✅ Modal/page de 1 pantalla
- ❌ Sidebar denso de 260px → ✅ Sidebar de 280px con cards limpias
- ❌ Toggle filtros pequeños → ✅ Filter bar prominente arriba

**Agregar:**
- Histograma sobre precio (Recharts o custom SVG)
- Range sliders (rc-slider o custom)
- Animaciones (Framer Motion)
- Iconos consistentes (lucide-react ya está)

---

## 11. INSTITUCIONAL — qué NO simplificar

1. **Bandas de precio** — siempre p25-p50-p75
2. **Disclaimer cap rate** — visible en modo Operador
3. **Riesgos primero** — sin excepciones
4. **Versión modelo** — footer pequeño "data v3.2 · model v1.0"
5. **Trazabilidad** — tooltip "según comparables 24m" en cada precio

---

## 12. INSTRUCCIÓN AL EJECUTOR

1. Leer `prompts/opportunity_engine_design.md` y `prompts/ux_simplification_phase3.md` para contexto
2. **NO modificar el backend** — solo frontend y reportes
3. Ejecutar las 8 horas en orden
4. Commit por hora con prefijo `feat(ux-v4):`
5. Generar 3 capturas de pantalla del flujo completo
6. Actualizar CLAUDE.md y RE_CL.md con sección "UX Phase 4"
7. **Test obligatorio:** mostrar la pantalla a alguien sin contexto y medir 3s/30s
8. NO push remoto sin autorización

---

*Prompt generado con Opus 4.7 · 2026-04-30 · v4.0 · Simplificación Radical · Listo para Sonnet*
