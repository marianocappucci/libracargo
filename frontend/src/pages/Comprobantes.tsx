/** Comprobantes: lo facturado, y el gate de F5 a la vista.
 *
 * Acá no se crean comprobantes (ADR-032): salen de una pre factura, por ARCA, que
 * les pone el número y el punto de venta. Esta pantalla lista lo emitido, lo
 * anterior (registrado a mano y migrado del legado) y deja anular lo que no
 * tiene CAE o acreditarlo con una nota de crédito.
 *
 * 🔑 **El panel de totales muestra los dos lados, no uno.** El total facturado
 * se cuenta por los encabezados de los comprobantes y por las órdenes
 * que agrupan. Mostrar sólo uno haría que un total divergente se viera igual de
 * confiable que uno sano — que es justo cuando no hay que usarlo.
 */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Download, ExternalLink, FileText, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'

import type { Comprobante, ComprobanteConOrdenes, TotalDeComprobantes } from '@/api/comprobantes'
import { NOMBRE_DE_TIPO, comprobantes, numeroDe } from '@/api/comprobantes'
import type { Opcion, Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { api } from 'libra-ui/api-client'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearImporte } from '@/components/esquema-orden'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { irA } from '@/navegacion'
import { formatearFecha } from '@/components/esquema-orden'
import { ICONOS_LC } from '@/iconos'

function Campo({ id, etiqueta, valor, alCambiar, tipo = 'text' }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; tipo?: string
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <Input id={id} type={tipo} value={valor} onChange={(e) => alCambiar(e.target.value)} />
    </div>
  )
}

function nombre(opciones: Opcion[], id: number | null): string {
  return opciones.find((o) => o.id === id)?.etiqueta ?? ''
}

/** El panel del gate: lo facturado, contado por los dos lados. Hay un solo emisor (ADR-035). */
function Totales({ total }: { total: TotalDeComprobantes | null }) {
  if (total === null || (total.cantidad_comprobantes === 0 && total.cantidad_ordenes === 0
      && total.coinciden)) return null
  return (
    <section className="mb-6 rounded border p-4">
      <h2 className="mb-3 text-sm font-semibold">Total facturado</h2>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="text-muted-foreground text-xs">
            <tr>
              <th className="p-1 text-right">Comprobantes</th>
              <th className="p-1 text-right">Total por comprobantes</th>
              <th className="p-1 text-right">Órdenes</th>
              <th className="p-1 text-right">Total por órdenes</th>
            </tr>
          </thead>
          <tbody>
            <tr className={total.coinciden ? '' : 'text-destructive font-semibold'}>
              <td className="p-1 text-right">{total.cantidad_comprobantes}</td>
              <td className="p-1 text-right">{total.total_comprobantes}</td>
              <td className="p-1 text-right">{total.cantidad_ordenes}</td>
              <td className="p-1 text-right">{total.total_ordenes}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {!total.coinciden && (
        <p role="alert" className="text-destructive mt-3 text-sm font-semibold">
          🔴 Los dos lados NO coinciden. No usar estos totales: hay importes que
          dicen una cosa por los comprobantes y otra por las órdenes.
        </p>
      )}
    </section>
  )
}

/** Una factura (o una FCE), no una nota: lo único a lo que se le emite una nota de crédito. */
function esFactura(tipo: Comprobante['tipo']): boolean {
  return tipo.startsWith('factura_') || tipo.startsWith('fce_')
}

/** `"1.234,5"` o `"121.5"` → centavos enteros, o `null` si no es un importe de hasta dos decimales. */
function centavosDe(texto: string): number | null {
  const limpio = texto.trim().replace(',', '.')
  if (!/^\d+(\.\d{1,2})?$/.test(limpio)) return null
  const [entero, dec = ''] = limpio.split('.')
  return Number(entero) * 100 + Number((dec + '00').slice(0, 2))
}

/** Centavos → `"121.00"`: lo que viaja al servidor, como texto. */
function deCentavos(centavos: number): string {
  return `${Math.floor(centavos / 100)}.${String(centavos % 100).padStart(2, '0')}`
}

export default function Comprobantes() {
  const [filas, setFilas] = useState<Comprobante[]>([])
  const [totales, setTotales] = useState<TotalDeComprobantes | null>(null)
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [detalle, setDetalle] = useState<ComprobanteConOrdenes | null>(null)
  const [params, setParams] = useSearchParams()
  const [confirmando, setConfirmando] = useState(false)
  // La nota de crédito: pide un motivo y se confirma aparte, igual que anular. Total o por un importe (ADR-028).
  const [notaAbierta, setNotaAbierta] = useState(false)
  const [motivo, setMotivo] = useState('')
  const [parcial, setParcial] = useState(false)
  const [importe, setImporte] = useState('')
  const [emitiendo, setEmitiendo] = useState(false)
  // El PDF por correo (ADR-034): un campo en el mismo detalle, con el correo del cliente prellenado.
  const [correoAbierto, setCorreoAbierto] = useState(false)
  const [correo, setCorreo] = useState('')
  const [enviando, setEnviando] = useState(false)
  // El error del envío va **dentro** del detalle: el del resto de la pantalla queda tapado por el diálogo.
  const [errorDeCorreo, setErrorDeCorreo] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // `/comprobantes?ver=123` abre ese comprobante. Es a donde lleva un asiento
  // de cuenta corriente que salio de una factura.
  const idAVer = params.get('ver')
  useEffect(() => {
    if (!idAVer) return
    let vigente = true
    comprobantes.ver(Number(idAVer))
      .then((c) => { if (vigente) setDetalle(c) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [idAVer])

  const recargar = useCallback(() => {
    setCargando(true)
    Promise.all([
      comprobantes.listar({ desde, hasta }),
      comprobantes.totales(desde || undefined, hasta || undefined),
    ])
      .then(([lista, tot]) => { setFilas(lista); setTotales(tot) })
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [desde, hasta])

  useEffect(recargar, [recargar])

  async function ver(id: number) {
    setError(null)
    setAviso(null)
    setConfirmando(false)
    setNotaAbierta(false)
    setCorreoAbierto(false)
    setMotivo('')
    setImporte('')
    try {
      setDetalle(await comprobantes.ver(id))
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  function abrirCorreo(clienteId: number) {
    setErrorDeCorreo(null)
    setAviso(null)
    setCorreo('')
    setCorreoAbierto(true)
    // El correo del cliente, si lo tiene cargado: es lo que se prellena. Si no se puede leer, se tipea.
    api.get<{ email?: string | null }>(`/api/terceros/${clienteId}`)
      .then((t) => setCorreo((previo) => previo || t?.email || ''))
      .catch(() => { /* es una comodidad: si no se pudo leer, se escribe a mano */ })
  }

  async function enviarPdf(id: number) {
    setErrorDeCorreo(null)
    setEnviando(true)
    try {
      await comprobantes.enviarPorCorreo(id, correo.trim())
      setAviso(`Enviado a ${correo.trim()}.`)
      setCorreoAbierto(false)
    } catch (e) {
      // El mensaje es el del servidor, tal cual: dice dónde falta configurar el correo.
      setErrorDeCorreo(mensajeDeError(e))
    } finally {
      setEnviando(false)
    }
  }

  async function anular(id: number) {
    setError(null)
    try {
      await comprobantes.anular(id)
      setDetalle(null)
      setConfirmando(false)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function emitirNota(id: number) {
    setError(null)
    setEmitiendo(true)
    try {
      const r = await comprobantes.notaDeCredito(
        id, motivo.trim(), parcial && importeValido !== null ? deCentavos(importeValido) : undefined)
      if ('ensayo' in r) {
        // Homologación: se corrió todo contra ARCA y no se guardó nada. El comprobante sigue como estaba.
        setAviso(`Ensayo contra ${r.ambiente}: ARCA autorizó una nota de crédito de prueba `
          + `(CAE ${r.cae ?? 's/n'}) y no se guardó nada.`)
        setNotaAbierta(false)
        return
      }
      setDetalle(null)
      setNotaAbierta(false)
      setMotivo('')
      setImporte('')
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setEmitiendo(false)
    }
  }

  // Lo que la pantalla sabe para ofrecer la nota. Sin `saldo_acreditable` (un servidor anterior) se ofrece
  // sólo la total, como antes. El tope de verdad lo valida el motor; esto es para no ofrecer lo que va a rechazar.
  const esFceDetalle = detalle?.comprobante.tipo.startsWith('fce_') ?? false
  const saldoCentavos = detalle?.saldo_acreditable != null ? centavosDe(detalle.saldo_acreditable) : null
  const tieneNotas = (detalle?.notas?.length ?? 0) > 0
  // La total copia la factura entera: sólo sin notas previas, y nunca en una FCE (ARCA: 10184).
  const admiteTotal = !tieneNotas && !esFceDetalle
  const tecleado = centavosDe(importe)
  const importeValido = tecleado !== null && tecleado > 0 && (saldoCentavos === null
    || (esFceDetalle ? tecleado < saldoCentavos : tecleado <= saldoCentavos)) ? tecleado : null

  function abrirNota() {
    // Sin la total posible, arranca por el importe; con notas previas, propone el saldo.
    setParcial(!admiteTotal)
    setImporte(tieneNotas && !esFceDetalle && detalle?.saldo_acreditable ? detalle.saldo_acreditable : '')
    setNotaAbierta(true)
  }

  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'comprobante', header: 'Comprobante',
      accessorFn: (c: Comprobante) => `${NOMBRE_DE_TIPO[c.tipo]} ${numeroDe(c)}` },
    { id: 'cliente', header: 'Cliente',
      accessorFn: (c: Comprobante) => nombre(opciones?.clientes ?? [], c.cliente_id) },
    { id: 'neto', header: 'Neto',
      accessorFn: (c: Comprobante) => formatearImporte(c.neto) },
    { id: 'iva', header: 'IVA',
      accessorFn: (c: Comprobante) => formatearImporte(c.iva) },
    { id: 'total', header: sortableHeader('Total'),
      accessorFn: (c: Comprobante) => formatearImporte(c.total) },
    { id: 'estado', header: 'Estado',
      accessorFn: (c: Comprobante) => (c.anulado ? 'anulado' : 'vigente'),
      cell: ({ row }: { row: { original: Comprobante } }) => (
        <BadgeEstado tono={row.original.anulado ? 'negativo' : 'ok'}>
          {row.original.anulado ? 'anulado' : 'vigente'}
        </BadgeEstado>
      ) },
    { id: 'acciones', header: '',
      cell: ({ row }: { row: { original: Comprobante } }) => (
        <Button variant="ghost" size="sm" onClick={() => ver(row.original.id)}>
          <FileText className="size-4" /> Ver
        </Button>
      ) },
  ]

  return (
    <div>
      <div className="mb-4 flex items-center justify-end">
        {/* El título «Comprobantes» y las pestañas son de `ComprobantesSeccion`.
            Los dos accesos de arriba: facturar pendientes (que genera la pre
            factura) y la lista de pre facturas, que ya no está en el menú.

            El listado se imprime desde reportes (`listado-comprobantes`), que
            exige rango. Aca el boton salia sin fechas y mandaba al papel todos
            los comprobantes que hubiera. */}
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <Link to="/pre-facturas">
              <ICONOS_LC.preFacturas className="size-4" /> Pre facturas
            </Link>
          </Button>
          <Button asChild>
            <Link to={irA.facturarPendientes()}>
              <Plus className="size-4" /> Facturar pendientes
            </Link>
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Campo id="f-desde" etiqueta="Desde" tipo="date" valor={desde} alCambiar={setDesde} />
        <Campo id="f-hasta" etiqueta="Hasta" tipo="date" valor={hasta} alCambiar={setHasta} />
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <Totales total={totales} />

      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={(c) => ver(c.id)}
        emptyMessage={cargando ? 'Cargando…' : 'No hay comprobantes en ese rango.'}
      />

      <Dialog open={detalle != null}
              onOpenChange={(v) => {
                if (v) return
                setDetalle(null)
                setCorreoAbierto(false)
                if (params.has('ver')) {
                  const otros = new URLSearchParams(params)
                  otros.delete('ver')
                  setParams(otros, { replace: true })
                }
              }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {detalle && `${NOMBRE_DE_TIPO[detalle.comprobante.tipo]} ${numeroDe(detalle.comprobante)}`}
            </DialogTitle>
          </DialogHeader>
          {detalle && (
            <div className="grid gap-3 text-sm">
              <div className="flex flex-wrap gap-6">
                <div>
                  <p className="text-muted-foreground text-xs">Total del comprobante</p>
                  <p className="text-lg font-semibold">
                    {formatearImporte(detalle.comprobante.total)}
                  </p>
                </div>
                {/* Los dos numeros a la vista, igual que en la cuenta
                    corriente: el encabezado y lo que suman sus ordenes. */}
                <div>
                  <p className="text-muted-foreground text-xs">
                    Suma de sus {detalle.suma_de_ordenes.cantidad} orden/es
                  </p>
                  <p className="text-lg font-semibold">
                    {formatearImporte(detalle.suma_de_ordenes.total)}
                  </p>
                </div>
              </div>
              {detalle.comprobante.comprobante_asociado_id != null && (
                <p role="note" className="text-sm">
                  Acredita al comprobante #{detalle.comprobante.comprobante_asociado_id}
                  {detalle.comprobante.motivo ? ` · ${detalle.comprobante.motivo}` : ''}
                </p>
              )}
              {(detalle.notas?.length ?? 0) > 0 && (
                <div>
                  <p className="text-muted-foreground text-xs">Notas de crédito</p>
                  <ul className="divide-y rounded border">
                    {detalle.notas!.map((n) => (
                      <li key={n.id} className="flex items-center gap-3 p-2">
                        <span className="flex-1">
                          {NOMBRE_DE_TIPO[n.tipo]} {numeroDe(n)} · {formatearFecha(n.fecha)}
                          {n.motivo ? ` · ${n.motivo}` : ''}
                        </span>
                        {n.cae && (
                          <a className="underline" href={comprobantes.urlDelPdf(n.id)} target="_blank"
                             rel="noreferrer" aria-label={`PDF de la nota ${numeroDe(n)}`}>PDF</a>
                        )}
                        <span className="tabular-nums">{formatearImporte(n.total)}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {detalle.saldo_acreditable != null && (
                <p className="text-sm">
                  Acreditado {formatearImporte(detalle.acreditado ?? '0.00')} · queda por
                  acreditar {formatearImporte(detalle.saldo_acreditable)}
                </p>
              )}
              {aviso && <p role="status" className="text-sm font-semibold">{aviso}</p>}
              {!detalle.coinciden && (
                <p role="alert" className="text-destructive text-sm font-semibold">
                  🔴 El comprobante no dice lo mismo que sus órdenes. No usarlo
                  hasta saber cuál de los dos importes es el bueno.
                </p>
              )}
              <ul className="divide-y rounded border">
                {detalle.ordenes.map((o) => (
                  <li key={o.id} className="flex items-center gap-3 p-2">
                    <span className="flex-1">#{o.id} · {formatearFecha(o.fecha)} · remito {o.remito || 's/n'}</span>
                    <span className="tabular-nums">{o.total}</span>
                  </li>
                ))}
              </ul>
              {/* El PDF es de lo que ARCA autorizó: sin CAE (lo registrado a mano y lo migrado del legado) no
                  hay PDF, porque parecería una factura que ARCA no conoce. Las notas de crédito tienen el suyo. */}
              {detalle.comprobante.cae && (
                <div className="grid gap-2 border-t pt-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Button variant="outline" size="sm" asChild>
                      <a href={comprobantes.urlDelPdf(detalle.comprobante.id)} target="_blank" rel="noreferrer">
                        <ExternalLink className="size-4" /> Ver PDF
                      </a>
                    </Button>
                    <Button variant="outline" size="sm" asChild>
                      <a href={comprobantes.urlDelPdf(detalle.comprobante.id)}
                         download={`${NOMBRE_DE_TIPO[detalle.comprobante.tipo]} ${numeroDe(detalle.comprobante)}.pdf`}>
                        <Download className="size-4" /> Descargar PDF
                      </a>
                    </Button>
                    {!correoAbierto && (
                      <Button variant="outline" size="sm"
                              onClick={() => abrirCorreo(detalle.comprobante.cliente_id)}>
                        Enviar por correo
                      </Button>
                    )}
                  </div>
                  {correoAbierto && (
                    <div className="grid gap-2">
                      <Campo id="correo-pdf" etiqueta="Correo del cliente" tipo="email" valor={correo}
                             alCambiar={setCorreo} />
                      {errorDeCorreo && <p role="alert" className="text-destructive text-xs">{errorDeCorreo}</p>}
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" size="sm" onClick={() => setCorreoAbierto(false)}>Cancelar</Button>
                        <Button size="sm" disabled={enviando || !correo.includes('@')}
                                onClick={() => enviarPdf(detalle.comprobante.id)}>
                          Enviar
                        </Button>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
          <DialogFooter>
            {detalle && !detalle.comprobante.anulado && detalle.comprobante.cae && (
              // 🔴 Con CAE no se ofrece anular: anular no llega a ARCA, y el comprobante seguiría vigente
              // allá mientras sus órdenes se podrían facturar de nuevo. Se revierte con una nota de crédito
              // **emitida por ARCA**; la de una FCE, sólo por menos que su saldo.
              <span className="mr-auto self-center text-sm" role="note">
                Lo emitió ARCA (CAE {detalle.comprobante.cae}): no se anula desde acá.
                {esFactura(detalle.comprobante.tipo)
                  ? (esFceDetalle
                    ? ' Se acredita con notas de crédito por menos que su saldo: ARCA sólo deja anularla'
                      + ' entera si el comprador la rechazó.'
                    : ' Para revertirlo, emití una nota de crédito.')
                  : ''}
              </span>
            )}
            {detalle && !detalle.comprobante.anulado && detalle.comprobante.cae
              && esFactura(detalle.comprobante.tipo) && (
              notaAbierta ? (
                <div className="grid w-full gap-2">
                  <Campo id="motivo-nota" etiqueta="Motivo de la nota de crédito" valor={motivo}
                         alCambiar={setMotivo} />
                  {saldoCentavos !== null && (
                    <fieldset className="flex gap-4 text-sm">
                      <legend className="sr-only">Por cuánto</legend>
                      <label className="flex items-center gap-1">
                        <input type="radio" name="alcance-nota" checked={!parcial} disabled={!admiteTotal}
                               onChange={() => setParcial(false)} />
                        Por el total
                      </label>
                      <label className="flex items-center gap-1">
                        <input type="radio" name="alcance-nota" checked={parcial}
                               onChange={() => setParcial(true)} />
                        Por un importe
                      </label>
                    </fieldset>
                  )}
                  {parcial && (
                    <Campo id="importe-nota" etiqueta="Importe a acreditar (con IVA)" valor={importe}
                           alCambiar={setImporte} />
                  )}
                  <p className="text-muted-foreground text-xs">
                    {parcial
                      ? `Acredita ese importe, con fecha de hoy: ARCA la autoriza y la cuenta del cliente recibe el
                        abono. Las órdenes no se tocan, salvo que con esta nota quede acreditado todo el
                        comprobante: ahí vuelven a pendientes.${esFceDetalle
                          ? ' En una factura de crédito electrónica tiene que ser menos que el saldo.' : ''}`
                      : `Es por el total, con fecha de hoy. ARCA la autoriza, las órdenes vuelven a
                        pendientes y la cuenta del cliente recibe el abono.`}
                  </p>
                  {parcial && importe.trim() !== '' && importeValido === null && (
                    <p role="alert" className="text-destructive text-xs">
                      {tecleado === null || tecleado <= 0
                        ? 'El importe tiene que ser mayor que cero, con hasta dos decimales.'
                        : `Supera lo que queda por acreditar (${formatearImporte(detalle.saldo_acreditable ?? '')})`
                          + (esFceDetalle ? ': en una FCE tiene que ser menos.' : '.')}
                    </p>
                  )}
                  <div className="flex justify-end gap-2">
                    <Button variant="ghost" onClick={() => setNotaAbierta(false)}>No</Button>
                    <Button variant="destructive"
                            disabled={emitiendo || motivo.trim().length < 3 || (parcial && importeValido === null)}
                            onClick={() => emitirNota(detalle.comprobante.id)}>
                      Confirmar nota de crédito
                    </Button>
                  </div>
                </div>
              ) : (
                <Button variant="destructive" onClick={abrirNota}
                        disabled={saldoCentavos !== null && saldoCentavos <= 0}>
                  Emitir nota de crédito
                </Button>
              )
            )}
            {detalle && !detalle.comprobante.anulado && !detalle.comprobante.cae && (
              confirmando ? (
                <>
                  <span className="mr-auto self-center text-sm">
                    Las órdenes vuelven a pendientes y la cuenta se revierte.
                  </span>
                  <Button variant="ghost" onClick={() => setConfirmando(false)}>No</Button>
                  <Button variant="destructive"
                          onClick={() => anular(detalle.comprobante.id)}>
                    Confirmar anulación
                  </Button>
                </>
              ) : (
                // Dos pasos a proposito: anular mueve la cuenta corriente del
                // cliente, y es la clase de boton que no se aprieta sin querer.
                <Button variant="destructive" onClick={() => setConfirmando(true)}>
                  Anular comprobante
                </Button>
              )
            )}
            <Button variant="ghost" onClick={() => setDetalle(null)}>Cerrar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
