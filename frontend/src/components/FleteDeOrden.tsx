/** El flete de una orden (ADR-038): los km del viaje y la tarifa por tonelada pactada.
 *
 *  Suitrans cotiza con un **tarifario de referencia** sectorial —una tarifa en pesos por tonelada para cada
 *  kilómetro— y **pacta un porcentaje sobre esa referencia, que varía por viaje**. Esta sección ayuda a cargarlo:
 *  con los km muestra la referencia vigente a la fecha de la orden, y el porcentaje y la tarifa se calculan entre sí.
 *
 *  🔑 **Todo es editable y nada es obligatorio.** La referencia es una ayuda, no una regla: la tarifa se puede tipear
 *  a mano aunque no haya tarifario, y no cambia el importe de la orden (`tarifa`), que sigue siendo otro campo.
 *
 *  🔑 **Manda lo último que se tocó.** Si se escribió el porcentaje, un cambio de km (otra referencia) recalcula la
 *  tarifa; si se escribió la tarifa, recalcula el porcentaje. El porcentaje no viaja al servidor: es sólo la forma de
 *  llegar a la tarifa, que es lo que se guarda.
 */
import { useEffect, useRef, useState } from 'react'
import type { UseFormReturn } from 'react-hook-form'

import { mensajeDeError } from '@/components/AbmMaestro'
import type { Referencia } from '@/api/tarifario'
import { tarifario } from '@/api/tarifario'
import type { DatosOrden, EntradaOrden } from '@/components/esquema-orden'
import { formatearFecha, formatearImporte } from '@/components/esquema-orden'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  aDecimal, formatearPorcentaje, porcentajeDesdeTarifa, tarifaDesdePorcentaje,
} from '@/lib/tarifa'

type Form = UseFormReturn<EntradaOrden, unknown, DatosOrden>

/** Cuánto se espera después de la última tecla antes de consultar la referencia: «80» no pide primero «8». */
const ESPERA_MS = 250

type Consulta =
  | { tipo: 'nada' }
  | { tipo: 'consultando' }
  | { tipo: 'referencia'; referencia: Referencia }
  | { tipo: 'sin-tarifario' }
  | { tipo: 'error'; mensaje: string }

const texto = (v: unknown) => (v == null ? '' : String(v)).trim()
const kmValido = (km: string) => /^\d+$/.test(km) && Number(km) >= 1 && Number(km) <= 99999
const esFechaISO = (f: string) => /^\d{4}-\d{2}-\d{2}$/.test(f)

/** El mensaje que acompaña a los km: qué referencia hay, o por qué no hay. */
function MensajeDeReferencia({ consulta }: { consulta: Consulta }) {
  if (consulta.tipo === 'nada') return null
  let mensaje: string
  switch (consulta.tipo) {
    case 'consultando': mensaje = 'Consultando el tarifario…'; break
    case 'sin-tarifario': mensaje = 'No hay tarifario cargado para esa fecha.'; break
    case 'error': mensaje = consulta.mensaje; break
    case 'referencia': {
      const { tarifa, vigencia } = consulta.referencia
      mensaje = tarifa === null
        ? `Sin tarifa para esos km (tarifario ${formatearFecha(vigencia)}).`
        : `Referencia: ${formatearImporte(tarifa)} (tarifario ${formatearFecha(vigencia)})`
      break
    }
  }
  return <p role="status" className="text-muted-foreground text-xs md:col-span-3">{mensaje}</p>
}

/** La sección «Flete» del formulario de la orden: Km, % sobre la referencia y Tarifa por tonelada. */
export function SeccionFlete({ form }: { form: Form }) {
  const km = texto(form.watch('km'))
  const fecha = texto(form.watch('fecha'))
  const clienteId = Number(form.watch('cliente_id'))
  const errores = form.formState.errors

  const [consulta, setConsulta] = useState<Consulta>({ tipo: 'nada' })
  const [porcentaje, setPorcentaje] = useState('')
  const [pista, setPista] = useState<string | null>(null)
  // Lo mismo que `porcentaje`, para leerlo desde los efectos sin volver a dispararlos.
  const porcentajeRef = useRef('')
  // Qué se tocó último: es el que manda cuando cambia la referencia.
  const ultimo = useRef<'porcentaje' | 'tarifa'>('tarifa')
  // El porcentaje y la tarifa vinieron de la sugerencia del cliente y nadie los tocó: se pueden reemplazar.
  const sugerido = useRef(false)

  const referencia = consulta.tipo === 'referencia' ? consulta.referencia.tarifa : null

  function ponerPorcentaje(valor: string) {
    porcentajeRef.current = valor
    setPorcentaje(valor)
  }

  function ponerTarifaDesde(base: string | null, pct: string) {
    const tarifa = base === null ? null : tarifaDesdePorcentaje(base, pct)
    if (tarifa !== null) form.setValue('tarifa_tonelada', tarifa, { shouldDirty: true, shouldValidate: true })
  }

  // La referencia de esos km a la fecha de la orden.
  useEffect(() => {
    if (!kmValido(km)) { setConsulta({ tipo: 'nada' }); return }
    let vigente = true
    setConsulta({ tipo: 'consultando' })
    const espera = setTimeout(() => {
      tarifario.referencia(Number(km), esFechaISO(fecha) ? fecha : undefined)
        .then((r) => { if (vigente) setConsulta(r ? { tipo: 'referencia', referencia: r } : { tipo: 'sin-tarifario' }) })
        .catch((e) => { if (vigente) setConsulta({ tipo: 'error', mensaje: mensajeDeError(e) }) })
    }, ESPERA_MS)
    return () => { vigente = false; clearTimeout(espera) }
  }, [km, fecha])

  // Cambió la referencia (otros km, otra fecha, o llegó recién): se reacomoda lo que no se tocó último.
  useEffect(() => {
    if (ultimo.current === 'porcentaje' && porcentajeRef.current !== '') {
      ponerTarifaDesde(referencia, porcentajeRef.current)
    } else {
      const tarifa = texto(form.getValues('tarifa_tonelada'))
      ponerPorcentaje(referencia !== null && tarifa !== '' ? (porcentajeDesdeTarifa(referencia, aDecimal(tarifa) ?? '') ?? '') : '')
    }
  }, [referencia])

  // Al elegir el cliente, el porcentaje de su último viaje como punto de partida.
  useEffect(() => {
    setPista(null)
    if (!(clienteId > 0)) return
    const libre = () => (texto(form.getValues('tarifa_tonelada')) === '' && porcentajeRef.current === '') || sugerido.current
    if (!libre()) return
    let vigente = true
    tarifario.sugerencia(clienteId)
      .then((s) => {
        if (!vigente || !libre()) return
        if (s === null) {
          // El cliente nuevo no tiene viaje: lo que había venía del anterior y ya no corresponde.
          if (sugerido.current) {
            ponerPorcentaje('')
            form.setValue('tarifa_tonelada', '', { shouldDirty: true })
            sugerido.current = false
          }
          return
        }
        ponerPorcentaje(s.porcentaje)
        ultimo.current = 'porcentaje'
        sugerido.current = true
        setPista(`Último viaje de este cliente: ${formatearPorcentaje(s.porcentaje)} %`)
        ponerTarifaDesde(referencia, s.porcentaje)
      })
      // La sugerencia es una ayuda: si falla, se carga a mano como siempre.
      .catch(() => undefined)
    return () => { vigente = false }
  }, [clienteId])

  function cambiarPorcentaje(valor: string) {
    sugerido.current = false
    ultimo.current = 'porcentaje'
    ponerPorcentaje(valor)
    ponerTarifaDesde(referencia, valor)
  }

  const { onChange: alCambiarTarifa, ...tarifa } = form.register('tarifa_tonelada')

  return (
    <section aria-label="Flete" className="grid gap-3 md:col-span-2">
      <h3 className="text-sm font-semibold">Flete</h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="km">Km</Label>
          <Input id="km" type="number" min={1} max={99999} step={1} inputMode="numeric" className="tabular-nums"
                 aria-invalid={errores.km ? true : undefined} {...form.register('km')} />
          {errores.km && <p className="text-destructive text-xs">{String(errores.km.message)}</p>}
        </div>
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="porcentaje-referencia">% sobre referencia</Label>
          <Input id="porcentaje-referencia" inputMode="decimal" className="tabular-nums" value={porcentaje}
                 onChange={(e) => cambiarPorcentaje(e.target.value)} />
        </div>
        <div className="grid min-w-0 gap-1">
          <Label htmlFor="tarifa_tonelada">Tarifa por tonelada</Label>
          <Input id="tarifa_tonelada" inputMode="decimal" className="tabular-nums"
                 aria-invalid={errores.tarifa_tonelada ? true : undefined} {...tarifa}
                 onChange={(e) => {
                   void alCambiarTarifa(e)
                   sugerido.current = false
                   ultimo.current = 'tarifa'
                   const decimal = aDecimal(e.target.value)
                   ponerPorcentaje(referencia !== null && decimal !== null ? (porcentajeDesdeTarifa(referencia, decimal) ?? '') : '')
                 }} />
          {errores.tarifa_tonelada && (
            <p className="text-destructive text-xs">{String(errores.tarifa_tonelada.message)}</p>
          )}
        </div>
        <MensajeDeReferencia consulta={consulta} />
        {pista && <p className="text-muted-foreground text-xs md:col-span-3">{pista}</p>}
      </div>
      <p className="text-muted-foreground text-xs">
        La tarifa por tonelada se pacta por viaje, como un porcentaje de la referencia. No cambia el importe de la orden.
      </p>
    </section>
  )
}
