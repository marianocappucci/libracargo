/** Los kilos de una orden de carga (ADR-037): lo que se pesó al cargar y lo que dice el ticket al descargar.
 *
 *  Dos piezas: la sección del formulario (`SeccionKilos`) y la ficha de sólo lectura (`KilosDelDetalle`).
 *
 *  🔑 **Con bruto y tara el neto no se tipea**: es la resta, y el servidor la recalcula igual. Mostrarlo editable
 *  invitaría a cargar uno distinto, que el backend rechaza con un 422. Sin bruto o sin tara el neto sí se carga,
 *  porque a veces es lo único que se sabe (lo que dice el ticket).
 */
import type { UseFormReturn } from 'react-hook-form'

import type { Orden } from '@/api/ordenes'
import { formatearKilos } from '@/api/cartas-porte'
import type { DatosOrden, EntradaOrden, TramoDeKilos } from '@/components/esquema-orden'
import { TRAMOS_DE_KILOS, netoCalculado } from '@/components/esquema-orden'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Form = UseFormReturn<EntradaOrden, unknown, DatosOrden>

const ETIQUETA: Record<TramoDeKilos, string> = { carga: 'Carga', descarga: 'Descarga' }

function TramoDeKilos({ form, tramo }: { form: Form; tramo: TramoDeKilos }) {
  const campoBruto = `kg_bruto_${tramo}` as const
  const campoTara = `kg_tara_${tramo}` as const
  const campoNeto = `kg_neto_${tramo}` as const
  const calculado = netoCalculado(form.watch(campoBruto), form.watch(campoTara))
  const errores = form.formState.errors

  const entrada = (campo: typeof campoBruto | typeof campoTara | typeof campoNeto, etiqueta: string) => (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={campo}>
        {etiqueta}<span className="sr-only"> de {tramo}</span>
      </Label>
      {campo === campoNeto && calculado !== null ? (
        // Calculado: se ve, no se toca. `readOnly` y no `disabled` para que se pueda seleccionar y copiar.
        <Input id={campo} readOnly value={String(calculado)} inputMode="numeric"
               title="Bruto menos tara" className="bg-muted tabular-nums" />
      ) : (
        <Input id={campo} type="number" min={0} step={1} inputMode="numeric" className="tabular-nums"
               aria-invalid={errores[campo] ? true : undefined} {...form.register(campo)} />
      )}
      {errores[campo] && <p className="text-destructive text-xs">{String(errores[campo]?.message)}</p>}
    </div>
  )

  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-sm font-medium">{ETIQUETA[tramo]}</legend>
      <div className="grid grid-cols-3 gap-3">
        {entrada(campoBruto, 'Bruto')}
        {entrada(campoTara, 'Tara')}
        {entrada(campoNeto, 'Neto')}
      </div>
    </fieldset>
  )
}

/** La sección «Kilos» del formulario: dos filas, Carga y Descarga, cada una con bruto, tara y neto. */
export function SeccionKilos({ form }: { form: Form }) {
  return (
    <section aria-label="Kilos" className="grid gap-3 md:col-span-2">
      <h3 className="text-sm font-semibold">Kilos</h3>
      {TRAMOS_DE_KILOS.map((t) => <TramoDeKilos key={t} form={form} tramo={t} />)}
      <p className="text-muted-foreground text-xs">
        Con bruto y tara completos, el neto es la resta y se calcula solo. Si no, se puede cargar a mano.
      </p>
    </section>
  )
}

/** Los kilos de la orden, de sólo lectura, para el detalle. */
export function KilosDelDetalle({ orden }: { orden: Orden }) {
  return (
    <section aria-label="Kilos" className="col-span-2">
      <p className="text-muted-foreground mb-1 text-xs">Kilos</p>
      <table className="w-full text-sm tabular-nums">
        <thead>
          <tr className="text-muted-foreground text-xs">
            <th className="text-left font-normal"><span className="sr-only">Tramo</span></th>
            <th className="text-right font-normal">Bruto</th>
            <th className="text-right font-normal">Tara</th>
            <th className="text-right font-normal">Neto</th>
          </tr>
        </thead>
        <tbody>
          {TRAMOS_DE_KILOS.map((t) => (
            <tr key={t}>
              <th scope="row" className="text-left font-normal">{ETIQUETA[t]}</th>
              <td className="text-right">{formatearKilos(orden[`kg_bruto_${t}`])}</td>
              <td className="text-right">{formatearKilos(orden[`kg_tara_${t}`])}</td>
              <td className="text-right font-medium">{formatearKilos(orden[`kg_neto_${t}`])}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  )
}
