import { useState, useMemo } from 'react'
import { useAppStore } from '../store'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(n: number, decimals = 2): string {
  return n.toLocaleString('es-CL', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })
}

function fmtPct(n: number): string {
  return `${fmt(n, 2)}%`
}

function fmtUF(n: number): string {
  return `UF ${fmt(n, 1)}`
}

function fmtCLP(n: number): string {
  return `$${Math.round(n).toLocaleString('es-CL')}`
}

// Simple IRR approximation via binary search over [-50%, 200%]
function approxIRR(cashflows: number[]): number | null {
  // cashflows[0] is the initial outlay (negative), subsequent are inflows
  const npvAt = (r: number) =>
    cashflows.reduce((acc, cf, t) => acc + cf / Math.pow(1 + r, t), 0)

  let lo = -0.5
  let hi = 2.0
  if (npvAt(lo) * npvAt(hi) > 0) return null // no sign change → no real IRR in range

  for (let i = 0; i < 100; i++) {
    const mid = (lo + hi) / 2
    if (npvAt(mid) > 0) lo = mid
    else hi = mid
    if (hi - lo < 1e-8) break
  }
  return (lo + hi) / 2
}

// ---------------------------------------------------------------------------
// Collapsible card
// ---------------------------------------------------------------------------

function Card({
  title,
  children,
  defaultOpen = true,
}: {
  title: string
  children: React.ReactNode
  defaultOpen?: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="bg-gray-800 rounded-lg overflow-hidden border border-gray-700">
      <button
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-gray-750 transition-colors"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="text-sm font-semibold text-gray-200">{title}</span>
        <span className="text-gray-500 text-xs">{open ? '▲' : '▼'}</span>
      </button>
      {open && <div className="px-4 pb-4 pt-1">{children}</div>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Input row helper
// ---------------------------------------------------------------------------

function InputRow({
  label,
  value,
  onChange,
  min,
  max,
  step,
  suffix,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min?: number
  max?: number
  step?: number
  suffix?: string
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <label className="text-xs text-gray-400 flex-1">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step ?? 1}
          onChange={(e) => onChange(parseFloat(e.target.value) || 0)}
          className="w-24 bg-gray-700 border border-gray-600 rounded px-2 py-1 text-xs text-gray-200 text-right focus:outline-none focus:border-blue-500"
        />
        {suffix && <span className="text-xs text-gray-500 w-8">{suffix}</span>}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Cap-rate colour
// ---------------------------------------------------------------------------

function capRateColor(cr: number): string {
  if (cr >= 5) return 'text-green-400'
  if (cr >= 3) return 'text-yellow-400'
  return 'text-red-400'
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function FinanzasPanel() {
  const { selectedProperty } = useAppStore()

  // ---------- Section 1 — Configuración ----------
  const [precioUF, setPrecioUF] = useState<number>(
    selectedProperty?.real_value_uf ?? 5000
  )
  const [superficieM2, setSuperficieM2] = useState<number>(
    selectedProperty?.surface_m2 ?? 80
  )
  const [arriendoMensualUF, setArriendoMensualUF] = useState<number>(20)
  const [ufValue, setUfValue] = useState<number>(38000)

  // When the selected property changes, update precio / superficie
  // (controlled by the useState init above; user can still override)

  // ---------- Section 2 — Cap Rate & Yield ----------
  const [vacanciaPct, setVacanciaPct] = useState<number>(5)
  const [gastosMensualesUF, setGastosMensualesUF] = useState<number>(2)

  // ---------- Section 3 — DCF ----------
  const [tasaDescuento, setTasaDescuento] = useState<number>(8)
  const [crecimientoRenta, setCrecimientoRenta] = useState<number>(3)
  const [terminalMult, setTerminalMult] = useState<number>(20)

  // ---------- Derived calculations (useMemo) ----------
  const calc = useMemo(() => {
    const vacancia = vacanciaPct / 100
    const rd = tasaDescuento / 100
    const g = crecimientoRenta / 100

    // Yield
    const arriendoAnual = arriendoMensualUF * 12
    const grossYield = precioUF > 0 ? (arriendoAnual / precioUF) * 100 : 0
    const netYield = grossYield * (1 - vacancia)

    // NOI year 0 (base)
    const noi0 = arriendoAnual * (1 - vacancia) - gastosMensualesUF * 12
    const capRate = precioUF > 0 ? (noi0 / precioUF) * 100 : 0

    // DCF — 5 cash flows
    const cashFlows: number[] = []
    for (let t = 1; t <= 5; t++) {
      cashFlows.push(noi0 * Math.pow(1 + g, t - 1))
    }

    // Terminal value = NOI_year5 × mult
    const terminalValue = cashFlows[4] * terminalMult

    // NPV discounted
    let npvCF = 0
    for (let t = 1; t <= 5; t++) {
      npvCF += cashFlows[t - 1] / Math.pow(1 + rd, t)
    }
    const npvTerminal = terminalValue / Math.pow(1 + rd, 5)
    const npvTotal = npvCF + npvTerminal

    // IRR — cashflows[0] = -precioUF (investment), then annual NOIs + terminal at year 5
    const irrInput = [
      -precioUF,
      ...cashFlows.slice(0, 4),
      cashFlows[4] + terminalValue,
    ]
    const irrRaw = approxIRR(irrInput)
    const irr = irrRaw !== null ? irrRaw * 100 : null

    // Equity multiple
    const equityMult = precioUF > 0 ? (npvTotal + precioUF) / precioUF : 1

    return {
      grossYield,
      netYield,
      capRate,
      noi0,
      cashFlows,
      terminalValue,
      npvTotal,
      npvCLP: npvTotal * ufValue,
      irr,
      equityMult,
    }
  }, [
    precioUF,
    arriendoMensualUF,
    vacanciaPct,
    gastosMensualesUF,
    tasaDescuento,
    crecimientoRenta,
    terminalMult,
    ufValue,
  ])

  // ---------- Scenario calculations ----------
  const scenarios = useMemo(() => {
    const vacanciaValues = [0.10, vacanciaPct / 100, 0.02]
    const rentMultipliers = [0.80, 1.0, 1.20]
    const rd = tasaDescuento / 100
    const g = crecimientoRenta / 100

    return ['Pesimista', 'Base', 'Optimista'].map((label, i) => {
      const arrUF = arriendoMensualUF * rentMultipliers[i]
      const vac = vacanciaValues[i]
      const arrAnual = arrUF * 12
      const noi = arrAnual * (1 - vac) - gastosMensualesUF * 12
      const cap = precioUF > 0 ? (noi / precioUF) * 100 : 0
      const yld = precioUF > 0 ? (arrAnual / precioUF) * 100 * (1 - vac) : 0

      // 5-year NPV
      let npv = 0
      let noiT = noi
      for (let t = 1; t <= 5; t++) {
        npv += noiT / Math.pow(1 + rd, t)
        noiT *= 1 + g
      }
      const tv = noi * Math.pow(1 + g, 4) * terminalMult
      npv += tv / Math.pow(1 + rd, 5)

      return { label, arrUF, vac: vac * 100, cap, yld, npv }
    })
  }, [
    arriendoMensualUF,
    vacanciaPct,
    gastosMensualesUF,
    precioUF,
    tasaDescuento,
    crecimientoRenta,
    terminalMult,
  ])

  // ---------- Render ----------
  return (
    <div className="h-full overflow-auto bg-gray-900 p-4">
      <h2 className="text-base font-bold text-gray-100 mb-4">Simulador Financiero</h2>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

        {/* ── Section 1 — Configuración ── */}
        <Card title="1. Configuración del inmueble">
          {selectedProperty && (
            <div className="mb-3 p-2 bg-gray-700 rounded text-xs text-gray-300 space-y-1">
              <div className="flex justify-between">
                <span className="text-gray-400">Tipo</span>
                <span>{selectedProperty.project_type ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Comuna</span>
                <span>{selectedProperty.county_name ?? '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Superficie</span>
                <span>{selectedProperty.surface_m2 ? `${selectedProperty.surface_m2} m²` : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Precio</span>
                <span>{selectedProperty.real_value_uf ? fmtUF(selectedProperty.real_value_uf) : '—'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-400">Score</span>
                <span className="text-blue-400">
                  {selectedProperty.opportunity_score
                    ? (selectedProperty.opportunity_score * 100).toFixed(1)
                    : '—'}
                </span>
              </div>
            </div>
          )}

          {!selectedProperty && (
            <p className="text-xs text-gray-500 mb-3 italic">
              Sin propiedad seleccionada — usando valores manuales.
            </p>
          )}

          <div className="space-y-2">
            <InputRow label="Precio (UF)" value={precioUF} onChange={setPrecioUF} min={100} step={100} suffix="UF" />
            <InputRow label="Superficie" value={superficieM2} onChange={setSuperficieM2} min={10} step={5} suffix="m²" />
            <InputRow label="Arriendo mensual" value={arriendoMensualUF} onChange={setArriendoMensualUF} min={1} step={0.5} suffix="UF" />
            <InputRow label="Valor UF (CLP)" value={ufValue} onChange={setUfValue} min={30000} step={100} suffix="$" />
          </div>

          {/* Price per m² */}
          <div className="mt-3 pt-3 border-t border-gray-700 flex justify-between text-xs text-gray-400">
            <span>Precio / m²</span>
            <span className="text-gray-200">
              {superficieM2 > 0 ? fmtUF(precioUF / superficieM2) : '—'} / m²
            </span>
          </div>
          <div className="flex justify-between text-xs text-gray-400 mt-1">
            <span>Precio total (CLP)</span>
            <span className="text-gray-200">{fmtCLP(precioUF * ufValue)}</span>
          </div>
        </Card>

        {/* ── Section 2 — Cap Rate & Yield ── */}
        <Card title="2. Cap Rate & Yield">
          <div className="space-y-2 mb-4">
            <InputRow label="Vacancia" value={vacanciaPct} onChange={setVacanciaPct} min={0} max={50} step={0.5} suffix="%" />
            <InputRow label="Gastos mensuales" value={gastosMensualesUF} onChange={setGastosMensualesUF} min={0} step={0.5} suffix="UF" />
          </div>

          <div className="space-y-2">
            {/* Gross yield */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">Yield bruto</span>
              <span className={`text-sm font-semibold ${capRateColor(calc.grossYield)}`}>
                {fmtPct(calc.grossYield)}
              </span>
            </div>
            {/* Net yield */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">Yield neto</span>
              <span className={`text-sm font-semibold ${capRateColor(calc.netYield)}`}>
                {fmtPct(calc.netYield)}
              </span>
            </div>
            {/* Cap rate */}
            <div className="flex justify-between items-center border-t border-gray-700 pt-2 mt-2">
              <span className="text-xs text-gray-300 font-medium">Cap rate</span>
              <span className={`text-base font-bold ${capRateColor(calc.capRate)}`}>
                {fmtPct(calc.capRate)}
              </span>
            </div>
            {/* NOI */}
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">NOI anual</span>
              <span className="text-sm text-gray-200">{fmtUF(calc.noi0)}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">NOI anual (CLP)</span>
              <span className="text-sm text-gray-200">{fmtCLP(calc.noi0 * ufValue)}</span>
            </div>
          </div>

          {/* Cap rate legend */}
          <div className="mt-4 flex gap-3 text-xs">
            <span className="text-green-400">● ≥ 5% excelente</span>
            <span className="text-yellow-400">● 3-5% aceptable</span>
            <span className="text-red-400">● &lt; 3% bajo</span>
          </div>
        </Card>

        {/* ── Section 3 — DCF ── */}
        <Card title="3. Simulador DCF (5 años)">
          <div className="space-y-2 mb-4">
            <InputRow label="Tasa de descuento" value={tasaDescuento} onChange={setTasaDescuento} min={1} max={30} step={0.5} suffix="%" />
            <InputRow label="Crecimiento de renta" value={crecimientoRenta} onChange={setCrecimientoRenta} min={0} max={15} step={0.5} suffix="%" />
            <InputRow label="Múltiplo terminal" value={terminalMult} onChange={setTerminalMult} min={5} max={50} step={1} suffix="×" />
          </div>

          {/* Cash flow table */}
          <div className="overflow-x-auto mb-4">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left pb-1">Año</th>
                  <th className="text-right pb-1">NOI (UF)</th>
                  <th className="text-right pb-1">NOI (CLP)</th>
                </tr>
              </thead>
              <tbody>
                {calc.cashFlows.map((cf, i) => (
                  <tr key={i} className="border-b border-gray-700/50">
                    <td className="py-1 text-gray-400">Año {i + 1}</td>
                    <td className="py-1 text-right text-gray-200">{fmt(cf, 1)}</td>
                    <td className="py-1 text-right text-gray-400">{fmtCLP(cf * ufValue)}</td>
                  </tr>
                ))}
                <tr className="border-b border-gray-700">
                  <td className="py-1 text-gray-500 italic">Valor terminal</td>
                  <td className="py-1 text-right text-gray-300">{fmt(calc.terminalValue, 1)}</td>
                  <td className="py-1 text-right text-gray-400">{fmtCLP(calc.terminalValue * ufValue)}</td>
                </tr>
              </tbody>
            </table>
          </div>

          {/* Summary metrics */}
          <div className="space-y-2">
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">VAN (NPV)</span>
              <div className="text-right">
                <span className={`text-sm font-semibold ${calc.npvTotal >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {fmtUF(calc.npvTotal)}
                </span>
                <div className="text-xs text-gray-500">{fmtCLP(calc.npvCLP)}</div>
              </div>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">TIR (IRR)</span>
              <span className={`text-sm font-semibold ${calc.irr !== null && calc.irr >= tasaDescuento ? 'text-green-400' : 'text-yellow-400'}`}>
                {calc.irr !== null ? fmtPct(calc.irr) : 'N/A'}
              </span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-xs text-gray-400">Equity multiple</span>
              <span className={`text-sm font-semibold ${calc.equityMult >= 1.5 ? 'text-green-400' : calc.equityMult >= 1 ? 'text-yellow-400' : 'text-red-400'}`}>
                {fmt(calc.equityMult, 2)}×
              </span>
            </div>
          </div>
        </Card>

        {/* ── Section 4 — Escenarios ── */}
        <Card title="4. Análisis de escenarios">
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-gray-500 border-b border-gray-700">
                  <th className="text-left pb-2 font-medium">Métrica</th>
                  {scenarios.map((s) => (
                    <th key={s.label} className={`text-right pb-2 font-medium ${
                      s.label === 'Pesimista' ? 'text-red-400' :
                      s.label === 'Optimista' ? 'text-green-400' : 'text-yellow-400'
                    }`}>
                      {s.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-700/50">
                {/* Arriendo mensual */}
                <tr>
                  <td className="py-2 text-gray-400">Arriendo mensual (UF)</td>
                  {scenarios.map((s) => (
                    <td key={s.label} className={`py-2 text-right ${
                      s.label === 'Pesimista' ? 'text-red-300' :
                      s.label === 'Optimista' ? 'text-green-300' : 'text-gray-200'
                    }`}>
                      {fmt(s.arrUF, 1)}
                    </td>
                  ))}
                </tr>
                {/* Vacancia */}
                <tr>
                  <td className="py-2 text-gray-400">Vacancia</td>
                  {scenarios.map((s) => (
                    <td key={s.label} className={`py-2 text-right ${
                      s.label === 'Pesimista' ? 'text-red-300' :
                      s.label === 'Optimista' ? 'text-green-300' : 'text-gray-200'
                    }`}>
                      {fmtPct(s.vac)}
                    </td>
                  ))}
                </tr>
                {/* Cap rate */}
                <tr>
                  <td className="py-2 text-gray-400">Cap rate</td>
                  {scenarios.map((s) => (
                    <td key={s.label} className={`py-2 text-right font-semibold ${capRateColor(s.cap)}`}>
                      {fmtPct(s.cap)}
                    </td>
                  ))}
                </tr>
                {/* Net yield */}
                <tr>
                  <td className="py-2 text-gray-400">Yield neto</td>
                  {scenarios.map((s) => (
                    <td key={s.label} className={`py-2 text-right font-semibold ${capRateColor(s.yld)}`}>
                      {fmtPct(s.yld)}
                    </td>
                  ))}
                </tr>
                {/* NPV */}
                <tr>
                  <td className="py-2 text-gray-400">VAN (UF)</td>
                  {scenarios.map((s) => (
                    <td key={s.label} className={`py-2 text-right font-semibold ${s.npv >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {fmt(s.npv, 0)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>

          <p className="mt-3 text-xs text-gray-600 italic">
            Pesimista: arriendo −20%, vacancia 10%. Base: valores actuales. Optimista: arriendo +20%, vacancia 2%.
          </p>
        </Card>

      </div>
    </div>
  )
}
