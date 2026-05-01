/**
 * QuickReturnSimulator.tsx — Geltner-grade DCF simplificado.
 *
 * Inputs: hold period, pie %, tasa hipoteca anual.
 * Outputs: IRR anualizado, ROI total, payback period.
 *
 * Modelo:
 *   NOI = renta_bruta_anual × (1 - vacancia) - gastos_admin - contribuciones
 *   service_deuda = anualidad(monto_credito, tasa, 30 años)
 *   exit = precio × (1 + growth)^N - saldo_deuda
 *   IRR = solve(NPV=0)
 */

import { useMemo, useState } from 'react'
import { fmtPct, fmtUF } from '../lib/format'
import type { Candidate } from './HomeShell'

interface Props {
  candidate: Candidate
}

const VACANCY     = 0.05   // 5% vacancia (Geltner default urbano CL)
const ADMIN_PCT   = 0.10   // 10% gastos admin
const CONTRIB_PCT = 0.011  // 1.1% del avalúo (proxy)
const GROWTH      = 0.05   // 5% anual histórico RM
const YIELD_BASE  = 0.055  // 5.5% yield bruto residencial RM
const MORTGAGE_TERM = 30   // años plazo crédito

function annuity(principal: number, annualRate: number, years: number): number {
  if (annualRate <= 0) return principal / years
  const r = annualRate / 12
  const n = years * 12
  const monthly = principal * (r * Math.pow(1 + r, n)) / (Math.pow(1 + r, n) - 1)
  return monthly * 12
}

function npv(rate: number, cashflows: number[]): number {
  return cashflows.reduce((acc, cf, t) => acc + cf / Math.pow(1 + rate, t), 0)
}

function irr(cashflows: number[], guess = 0.10): number | null {
  let r = guess
  for (let i = 0; i < 200; i++) {
    const npv0 = npv(r, cashflows)
    const dnpv = cashflows.reduce((acc, cf, t) => acc - t * cf / Math.pow(1 + r, t + 1), 0)
    if (Math.abs(npv0) < 0.01) return r
    if (dnpv === 0) return null
    r = r - npv0 / dnpv
    if (r < -0.99) r = -0.99
    if (r > 10) return null
  }
  return r
}

export function QuickReturnSimulator({ candidate }: Props) {
  const [holdYears, setHoldYears] = useState(5)
  const [downPct, setDownPct] = useState(20)
  const [mortgageRate, setMortgageRate] = useState(5.5)

  const result = useMemo(() => {
    const price = candidate.estimated_uf ?? 0
    if (!price) return null

    const downPayment = price * (downPct / 100)
    const debt = price - downPayment

    const grossRent = price * YIELD_BASE  // rent UF/yr (proxy)
    const noi = grossRent * (1 - VACANCY) - grossRent * ADMIN_PCT - price * CONTRIB_PCT
    const debtService = annuity(debt, mortgageRate / 100, MORTGAGE_TERM)

    // Cash flows year-by-year
    const cashflows: number[] = [-downPayment]
    let outstandingDebt = debt
    for (let yr = 1; yr <= holdYears; yr++) {
      // Saldo deuda decreciendo (simple amortización lineal proxy)
      const principalPaid = debt / MORTGAGE_TERM
      outstandingDebt = Math.max(0, outstandingDebt - principalPaid)

      const annualCf = noi - debtService
      if (yr < holdYears) {
        cashflows.push(annualCf)
      } else {
        // Year N: annual CF + exit value
        const exitPrice = price * Math.pow(1 + GROWTH, holdYears)
        cashflows.push(annualCf + exitPrice - outstandingDebt)
      }
    }

    const irrResult = irr(cashflows)
    const totalIn  = downPayment
    const totalOut = cashflows.slice(1).reduce((a, b) => a + b, 0)
    const roi      = (totalOut - totalIn) / totalIn

    // Payback: año en que CF acumulado supera 0
    let cum = -downPayment
    let payback: number | null = null
    for (let i = 1; i < cashflows.length; i++) {
      cum += cashflows[i]
      if (cum >= 0 && payback === null) { payback = i; break }
    }

    return {
      downPayment, debt, noi, debtService,
      irrPct: irrResult !== null ? irrResult * 100 : null,
      roiPct: roi * 100,
      payback,
      annualCf: noi - debtService,
      exitPrice: price * Math.pow(1 + GROWTH, holdYears),
    }
  }, [candidate, holdYears, downPct, mortgageRate])

  if (!result) return null

  return (
    <div className="bg-gray-900 rounded-xl p-4 border border-gray-800">
      <div className="flex items-center justify-between mb-3">
        <div className="text-xs text-gray-500 font-semibold">Simulador de retorno (DCF)</div>
        <div className="text-[10px] text-gray-600">Geltner-grade · proxy 5% growth · 5.5% yield</div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-4">
        {/* Years */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Años</label>
          <input
            type="range" min={3} max={20} step={1}
            value={holdYears}
            onChange={e => setHoldYears(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="text-center text-sm text-white font-semibold mt-1">{holdYears} años</div>
        </div>
        {/* Pie */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Pie</label>
          <input
            type="range" min={10} max={50} step={5}
            value={downPct}
            onChange={e => setDownPct(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="text-center text-sm text-white font-semibold mt-1">{downPct}%</div>
        </div>
        {/* Tasa */}
        <div>
          <label className="block text-xs text-gray-500 mb-1">Tasa hipoteca</label>
          <input
            type="range" min={3} max={10} step={0.1}
            value={mortgageRate}
            onChange={e => setMortgageRate(Number(e.target.value))}
            className="w-full accent-blue-500"
          />
          <div className="text-center text-sm text-white font-semibold mt-1">{mortgageRate.toFixed(1)}%</div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 mb-3">
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500">IRR anual</div>
          <div className="text-xl font-bold text-green-400">
            {result.irrPct !== null ? fmtPct(result.irrPct) : '—'}
          </div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500">ROI total</div>
          <div className="text-xl font-bold text-blue-400">{fmtPct(result.roiPct)}</div>
        </div>
        <div className="bg-gray-800 rounded-lg p-3 text-center">
          <div className="text-xs text-gray-500">Payback</div>
          <div className="text-xl font-bold text-amber-400">
            {result.payback !== null ? `${result.payback} años` : '> 20'}
          </div>
        </div>
      </div>

      <details className="text-xs text-gray-500">
        <summary className="cursor-pointer hover:text-gray-400 select-none">Ver desglose</summary>
        <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 font-mono">
          <span>Inversión inicial (pie)</span><span className="text-white">{fmtUF(result.downPayment)}</span>
          <span>Crédito hipotecario</span><span className="text-white">{fmtUF(result.debt)}</span>
          <span>NOI anual estimado</span><span className="text-white">{fmtUF(result.noi)}</span>
          <span>Servicio deuda anual</span><span className="text-white">{fmtUF(result.debtService)}</span>
          <span>Cash flow anual neto</span><span className="text-white">{fmtUF(result.annualCf)}</span>
          <span>Precio salida proyectado</span><span className="text-white">{fmtUF(result.exitPrice)}</span>
        </div>
        <div className="mt-2 text-[10px] text-gray-600 italic">
          Supuestos: vacancia 5%, gastos admin 10%, contribuciones 1.1%, growth 5%/año (RM histórico).
          Sensible a cambios de tasa de descuento ±150 bps. Validar con tasador profesional.
        </div>
      </details>
    </div>
  )
}
