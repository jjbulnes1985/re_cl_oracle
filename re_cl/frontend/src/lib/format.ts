/** Format helpers for UF and CLP currencies, surface areas, etc. */

export function fmtUF(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k UF`
  return `${Math.round(n).toLocaleString('es-CL')} UF`
}

export function fmtUFFull(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  return `${Math.round(n).toLocaleString('es-CL')} UF`
}

export function fmtCLP(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `$${Math.round(n / 1000)}k`
  return `$${Math.round(n).toLocaleString('es-CL')}`
}

export function fmtM2(v: number | null | undefined): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  return `${Math.round(n).toLocaleString('es-CL')} m²`
}

export function fmtPct(v: number | null | undefined, digits = 1): string {
  if (v === null || v === undefined) return '—'
  const n = Number(v)
  if (isNaN(n)) return '—'
  return `${n.toFixed(digits)}%`
}

export function scoreColor(score: number): string {
  if (score >= 0.75) return '#22c55e'
  if (score >= 0.60) return '#eab308'
  return '#ef4444'
}

export function scoreLabel(score: number): string {
  if (score >= 0.85) return 'Excelente oportunidad'
  if (score >= 0.75) return 'Muy buena oportunidad'
  if (score >= 0.60) return 'Buena oportunidad'
  if (score >= 0.40) return 'Oportunidad razonable'
  return 'Oportunidad baja'
}

export function scoreStars(score: number): string {
  const stars = Math.max(1, Math.min(5, Math.round(score * 5)))
  return '★'.repeat(stars) + '☆'.repeat(5 - stars)
}

export function gapText(drivers: Record<string, unknown> | undefined | null): { text: string; color: string } {
  const gap = drivers?.gap_pct as number | null | undefined
  if (gap === null || gap === undefined) return { text: 'Sin comparación', color: '#888' }
  const g = Number(gap)
  if (isNaN(g)) return { text: 'Sin comparación', color: '#888' }
  if (g < -3) return { text: `${Math.abs(g).toFixed(0)}% bajo el precio promedio`, color: '#22c55e' }
  if (g > 3)  return { text: `${g.toFixed(0)}% sobre el precio promedio`, color: '#ef4444' }
  return { text: 'Cercano al precio de mercado', color: '#888' }
}

export const PROPERTY_TYPE_LABELS: Record<string, { label: string; icon: string }> = {
  apartment:   { label: 'Departamento',  icon: '🏢' },
  house:       { label: 'Casa',          icon: '🏠' },
  land:        { label: 'Terreno',       icon: '🌳' },
  retail:      { label: 'Local comercial', icon: '🏪' },
  office:      { label: 'Oficina',       icon: '🏢' },
  warehouse:   { label: 'Bodega',        icon: '📦' },
  industrial:  { label: 'Industrial',    icon: '🏭' },
}
