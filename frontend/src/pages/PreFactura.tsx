/** Una pre factura: verla, mandarla, aceptarla, editarla, anularla y facturarla (ADR-032).
 *
 * El circuito es el que pidió el humano: la pre factura se manda al cliente (por correo desde acá, o el PDF
 * por otro medio), el operador marca **Aceptada** cuando el cliente contesta que está de acuerdo, y recién
 * después se **factura por ARCA**, que le pone el número y el punto de venta. Marcar la conformidad no es
 * obligatorio para facturar, pero la pantalla avisa si falta.
 *
 * 🔑 **Facturar es lo único de acá que no se deshace**: una factura con CAE se revierte con una nota de
 * crédito. Por eso pide confirmación, dice qué va a pasar y muestra el resultado (o el error, tal cual
 * lo dice el servidor: «ARCA no está configurado», «la empresa no tiene CUIT cargado»...). El emisor es siempre la
 * empresa (ADR-035): no se elige.
 */
import { api } from 'libra-ui/api-client'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ArrowLeft, Download, ExternalLink } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import type { Ensayo } from '@/api/comprobantes'
import { NOMBRE_DE_TIPO, numeroDe } from '@/api/comprobantes'
import type { PreFactura as PreFacturaT } from '@/api/pre-facturas'
import {
  ESTADOS_ABIERTOS, NOMBRE_DE_ESTADO, TONO_DE_ESTADO, preFacturas, tipoDe,
} from '@/api/pre-facturas'
import { mensajeDeError } from '@/components/AbmMaestro'
import {
  formatearFecha, formatearFechaHoraDeTexto, formatearImporte, hoyEnArgentina,
} from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { irA } from '@/navegacion'
import { ICONOS_LC } from '@/iconos'

type Accion = 'enviar' | 'anular' | 'facturar' | null

/** Lo que hay que mostrar de una factura recién emitida. */
type Emitida = { id: number; texto: string; cae: string | null }

const importe = (n: number | string) => formatearImporte(typeof n === 'number' ? n.toFixed(2) : n)

export default function PreFactura() {
  const { id } = useParams()
  const preFacturaId = Number(id)
  const [pf, setPf] = useState<PreFacturaT | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [emitida, setEmitida] = useState<Emitida | null>(null)
  const [ensayo, setEnsayo] = useState<Ensayo | null>(null)
  const [accion, setAccion] = useState<Accion>(null)
  const [trabajando, setTrabajando] = useState(false)
  const [email, setEmail] = useState('')
  const [motivo, setMotivo] = useState('')
  const [fechaFactura, setFechaFactura] = useState('')

  const cargar = useCallback(() => {
    preFacturas.ver(preFacturaId).then(setPf).catch((e) => setError(mensajeDeError(e)))
  }, [preFacturaId])

  useEffect(cargar, [cargar])

  const abierta = pf != null && ESTADOS_ABIERTOS.includes(pf.estado)
  const tipo = pf ? tipoDe(pf) : null

  async function abrirEnviar() {
    setError(null)
    setAviso(null)
    // El correo del cliente, si lo tiene cargado: es lo que se prellena. Si no se puede leer, se tipea.
    setEmail(pf?.enviado_a ?? '')
    setAccion('enviar')
    if (pf?.cliente_id != null && !pf.enviado_a) {
      api.get<{ email?: string | null }>(`/api/terceros/${pf.cliente_id}`)
        .then((t) => setEmail((previo) => previo || t?.email || ''))
        .catch(() => { /* es una comodidad: si no se pudo leer, se escribe a mano */ })
    }
  }

  async function ejecutar(hacer: () => Promise<void>) {
    setError(null)
    setAviso(null)
    setTrabajando(true)
    try {
      await hacer()
    } catch (e) {
      // El mensaje es el del servidor, tal cual: dice qué falta y qué hacer.
      setError(mensajeDeError(e))
      setAccion(null)
    } finally {
      setTrabajando(false)
    }
  }

  const enviar = () => ejecutar(async () => {
    const r = await preFacturas.enviarPorCorreo(preFacturaId, email.trim())
    setPf(r.id ? await preFacturas.ver(preFacturaId) : pf)
    setAviso(`Enviada a ${email.trim()}.`)
    setAccion(null)
  })

  const aceptar = () => ejecutar(async () => {
    await preFacturas.aceptar(preFacturaId)
    setPf(await preFacturas.ver(preFacturaId))
    setAviso('Marcada como aceptada.')
  })

  const anular = () => ejecutar(async () => {
    await preFacturas.anular(preFacturaId, motivo.trim())
    setPf(await preFacturas.ver(preFacturaId))
    setAviso('Pre factura anulada. Las órdenes quedaron libres para otra pre factura.')
    setAccion(null)
  })

  const facturar = () => ejecutar(async () => {
    setEmitida(null)
    setEnsayo(null)
    const r = await preFacturas.facturar(preFacturaId, fechaFactura || undefined)
    setAccion(null)
    // 🔴 **Un ensayo NO es una factura**: contra homologación el backend corre todo y lo revierte, así que
    // no hay comprobante que abrir. Se muestra qué contestó ARCA, y la pre factura sigue abierta.
    if ('ensayo' in r) {
      setEnsayo(r)
      return
    }
    setEmitida({
      id: r.id, cae: r.cae ?? null,
      texto: `${NOMBRE_DE_TIPO[r.tipo]} ${numeroDe(r)}`,
    })
    setPf(await preFacturas.ver(preFacturaId))
  })

  function abrirFacturar() {
    setError(null)
    setAviso(null)
    setFechaFactura(pf?.fecha_sugerida ?? hoyEnArgentina())
    setAccion('facturar')
  }

  if (!pf) {
    return (
      <div>
        {error
          ? <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>
          : <p className="text-muted-foreground text-sm">Cargando…</p>}
        <Button variant="ghost" asChild className="mt-4">
          <Link to="/pre-facturas"><ArrowLeft className="size-4" /> Volver a Pre facturas</Link>
        </Button>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Volver a Pre facturas">
          <Link to="/pre-facturas"><ArrowLeft className="size-4" /></Link>
        </Button>
        <TituloPantalla icono={ICONOS_LC.preFacturas}>Pre factura {pf.numero_interno}</TituloPantalla>
        <BadgeEstado tono={TONO_DE_ESTADO[pf.estado]}>{NOMBRE_DE_ESTADO[pf.estado]}</BadgeEstado>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">{error}</p>
      )}
      {aviso && <p role="status" className="mb-4 rounded border p-3 text-sm">{aviso}</p>}

      {emitida && (
        <section role="status" aria-label="Factura emitida" className="mb-4 rounded border p-4 text-sm">
          <h2 className="mb-1 font-semibold">Factura emitida por ARCA</h2>
          <p>{emitida.texto}{emitida.cae ? ` · CAE ${emitida.cae}` : ''}</p>
          <Button variant="link" asChild className="px-0">
            <Link to={irA.comprobante(emitida.id)}>Ver el comprobante</Link>
          </Button>
        </section>
      )}

      {ensayo && (
        <section role="status" aria-label="Resultado del ensayo" className="mb-4 rounded border p-4 text-sm">
          <h2 className="mb-1 font-semibold">Ensayo contra homologación — no se guardó nada</h2>
          {/* El «no se guardó nada» va en el título y no en una nota al pie: es lo primero que el operador
              tiene que entender, porque acaba de apretar Facturar y la pantalla no lo llevó a ningún
              comprobante. */}
          <p className="text-muted-foreground mb-3">
            ARCA contestó, así que el camino de emisión funciona. La pre factura sigue abierta, las órdenes
            siguen pendientes y la cuenta corriente no se movió. Para facturar de verdad, pasá el ambiente
            a producción en Configuración → ARCA.
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1">
            <dt className="text-muted-foreground">Número</dt>
            <dd>{String(ensayo.punto_venta).padStart(4, '0')}-{String(ensayo.numero).padStart(8, '0')}</dd>
            <dt className="text-muted-foreground">CAE</dt>
            <dd>{ensayo.cae || '—'}</dd>
            <dt className="text-muted-foreground">Vence</dt>
            <dd>{ensayo.cae_vencimiento ? formatearFecha(ensayo.cae_vencimiento) : '—'}</dd>
          </dl>
        </section>
      )}

      <section className="mb-6 grid gap-4 rounded border p-4 text-sm md:grid-cols-4">
        <div>
          <p className="text-muted-foreground text-xs">Cliente</p>
          <p className="font-semibold">{pf.cliente_razon}</p>
          <p>{pf.cliente_cuit || 'Sin CUIT'}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Comprobante</p>
          <p className="font-semibold">{tipo ? NOMBRE_DE_TIPO[tipo] : 'Sin tipo'}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Fecha</p>
          <p className="font-semibold">{formatearFecha(pf.fecha_sugerida)}</p>
          {pf.fecha_vencimiento_pago && (
            <p>Vence el pago el {formatearFecha(pf.fecha_vencimiento_pago)}</p>
          )}
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Total</p>
          <p className="text-lg font-semibold">{importe(pf.total)}</p>
        </div>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-semibold">Detalle</h2>
        <div className="overflow-x-auto rounded border">
          <table className="w-full text-sm">
            <thead className="text-muted-foreground text-xs">
              <tr>
                <th className="p-2 text-left">Concepto</th>
                <th className="p-2 text-right">Neto</th>
                <th className="p-2 text-right">IVA</th>
              </tr>
            </thead>
            <tbody>
              {pf.items.map((it, i) => (
                <tr key={`${it.orden_id ?? 'x'}-${i}`} className="border-t">
                  <td className="p-2">
                    {it.description}
                    {it.detalle ? <span className="text-muted-foreground"> · {it.detalle}</span> : null}
                  </td>
                  <td className="p-2 text-right tabular-nums">{importe(it.qty * it.unit_price)}</td>
                  <td className="p-2 text-right tabular-nums">{`${+(it.iva_rate * 100).toFixed(2)}%`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="mb-6 text-sm" aria-label="Historial">
        <h2 className="mb-2 text-sm font-semibold">Cómo va</h2>
        <ul className="grid gap-1">
          <li>Generada el {formatearFechaHoraDeTexto(pf.created_at)}.</li>
          {pf.enviado_at && (
            <li>Enviada a {pf.enviado_a} el {formatearFechaHoraDeTexto(pf.enviado_at)}.</li>
          )}
          {pf.aceptado_at && (
            <li>
              Aceptada por el cliente el {formatearFechaHoraDeTexto(pf.aceptado_at)}
              {pf.aceptado_por ? ` (la marcó ${pf.aceptado_por})` : ''}.
            </li>
          )}
          {pf.estado === 'facturado' && pf.factura_id != null && (
            <li>
              Facturada{pf.resuelto_at ? ` el ${formatearFechaHoraDeTexto(pf.resuelto_at)}` : ''}.{' '}
              <Link className="underline" to={irA.comprobante(pf.factura_id)}>Ver el comprobante</Link>
            </li>
          )}
          {pf.estado === 'descartado' && (
            <li>
              Anulada{pf.resuelto_por ? ` por ${pf.resuelto_por}` : ''}
              {pf.motivo_descarte ? `: ${pf.motivo_descarte}` : ''}.
            </li>
          )}
        </ul>
      </section>

      <div className="flex flex-wrap items-center gap-2 border-t pt-4">
        {/* El PDF se pide de cualquier estado: una anulada o una facturada también se puede reimprimir. */}
        <Button variant="outline" asChild>
          <a href={preFacturas.urlDelPdf(pf.id)} target="_blank" rel="noreferrer">
            <ExternalLink className="size-4" /> Ver PDF
          </a>
        </Button>
        <Button variant="outline" asChild>
          <a href={preFacturas.urlDelPdf(pf.id)} download={`${pf.numero_interno}.pdf`}>
            <Download className="size-4" /> Descargar PDF
          </a>
        </Button>
        {abierta && (
          <>
            <Button variant="outline" onClick={abrirEnviar}>Enviar por correo</Button>
            <Button variant="outline" asChild>
              <Link to={`/pre-facturas/${pf.id}/editar`}>Editar</Link>
            </Button>
            {pf.estado !== 'aceptado' && (
              <Button variant="outline" onClick={aceptar} disabled={trabajando}>Marcar aceptada</Button>
            )}
            <Button variant="destructive" onClick={() => { setMotivo(''); setError(null); setAccion('anular') }}>
              Anular
            </Button>
            <Button className="ml-auto" onClick={abrirFacturar}>Facturar por ARCA</Button>
          </>
        )}
      </div>

      {/* ── Enviar por correo ── */}
      <Dialog open={accion === 'enviar'} onOpenChange={(v) => { if (!v) setAccion(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Enviar la pre factura por correo</DialogTitle>
            <DialogDescription>
              Va el PDF de {pf.numero_interno}, con el aviso de que no es una factura.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1">
            <Label htmlFor="pf-email">Correo del cliente</Label>
            <Input id="pf-email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAccion(null)}>Cancelar</Button>
            <Button onClick={enviar} disabled={trabajando || !email.includes('@')}>Enviar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Anular ── */}
      <Dialog open={accion === 'anular'} onOpenChange={(v) => { if (!v) setAccion(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Anular la pre factura {pf.numero_interno}</DialogTitle>
            <DialogDescription>
              Las órdenes quedan libres para otra pre factura. Una anulada no se vuelve a abrir, y su número
              no se reusa.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-1">
            <Label htmlFor="pf-motivo">Motivo</Label>
            <Input id="pf-motivo" value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAccion(null)}>No</Button>
            <Button variant="destructive" onClick={anular}
                    disabled={trabajando || motivo.trim().length < 3}>
              Confirmar anulación
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Facturar por ARCA ── */}
      <Dialog open={accion === 'facturar'} onOpenChange={(v) => { if (!v) setAccion(null) }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Facturar {pf.numero_interno} por ARCA</DialogTitle>
            <DialogDescription>
              ARCA le pone el número y el punto de venta. Las órdenes pasan a facturadas y la deuda entra
              en la cuenta corriente del cliente. Una factura emitida no se anula: se revierte con una
              nota de crédito.
            </DialogDescription>
          </DialogHeader>
          {pf.estado !== 'aceptado' && (
            <p role="note" className="rounded border border-amber-500/50 p-3 text-sm">
              Todavía no está marcada como aceptada: el cliente puede no haber confirmado los datos.
            </p>
          )}
          <div className="grid gap-1">
            <Label htmlFor="pf-fecha-factura">Fecha del comprobante</Label>
            <Input id="pf-fecha-factura" type="date" value={fechaFactura}
                   onChange={(e) => setFechaFactura(e.target.value)} />
            <p className="text-muted-foreground text-xs">
              Por defecto, la de la pre factura. A los días de generarla, ARCA puede no aceptar la fecha vieja.
            </p>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAccion(null)}>No</Button>
            <Button onClick={facturar} disabled={trabajando || !fechaFactura}>
              {trabajando ? 'Facturando…' : 'Confirmar y facturar'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
