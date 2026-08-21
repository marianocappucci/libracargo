/** Facturar pendientes: una pantalla, no un modal.
 *
 * 🔑 **Era un `<Dialog>` y el humano pidió sacarlo de ahí.** Con razón: un
 * cliente tiene hasta **82 órdenes pendientes** —AGROPECUARIA PEREIRO, medido
 * sobre los datos reales—, y elegirlas de a una dentro de una caja con
 * `max-h-[85vh] overflow-y-auto` obliga a scrollear el modal mientras los
 * campos del comprobante y el total quedan fuera de la vista. Un modal sirve
 * para confirmar algo corto; esto es una tarea con lista, totales y decisiones.
 *
 * El cliente elegido vive en la URL (`/comprobantes/facturar?cliente=1`), como
 * el resto de las pantallas del sistema: así se puede volver, refrescar o
 * mandarle el link a alguien sin perder dónde estaba.
 */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { ArrowLeft } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'

import { comprobantes, sumarImportes } from '@/api/comprobantes'
import type { Opciones, Orden } from '@/api/ordenes'
import { cargarOpciones, ordenes as apiOrdenes } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Borrador = {
  fecha: string
  razon_social_id: string
  tipo: string
  punto_venta: string
  numero: string
}

// La fecha por defecto sale de la de Argentina y no de `toISOString`: un
// comprobante cargado de noche nacía con la fecha de mañana.
const VACIO: Borrador = {
  fecha: hoyEnArgentina(), razon_social_id: '',
  tipo: 'factura_a', punto_venta: '1', numero: '',
}

function Campo({ id, etiqueta, valor, alCambiar, tipo = 'text' }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; tipo?: string
}) {
  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <Input id={id} type={tipo} value={valor} onChange={(e) => alCambiar(e.target.value)} />
    </div>
  )
}

function Eleccion({ id, etiqueta, valor, alCambiar, children }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; children: React.ReactNode
}) {
  return (
    <div className="grid min-w-0 gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <select id={id} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
              value={valor} onChange={(e) => alCambiar(e.target.value)}>
        {children}
      </select>
    </div>
  )
}

const nombreDe = (lista: { id: number; etiqueta: string }[] | undefined, id: number | null) =>
  lista?.find((o) => o.id === id)?.etiqueta ?? ''

export default function FacturarPendientes() {
  const [params, setParams] = useSearchParams()
  const navegar = useNavigate()
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [borrador, setBorrador] = useState<Borrador>(VACIO)
  const [pendientes, setPendientes] = useState<Orden[]>([])
  const [elegidas, setElegidas] = useState<number[]>([])
  const [cargando, setCargando] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const clienteId = params.get('cliente') ?? ''

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // Las pendientes del cliente elegido. Sin cliente no se piden: un comprobante
  // es de un solo cliente, y una lista de todos invitaría a mezclarlos.
  useEffect(() => {
    if (!clienteId) { setPendientes([]); return }
    let vigente = true
    setCargando(true)
    apiOrdenes
      .listar({ cliente_id: Number(clienteId), facturada: false, estado: 'pendiente' })
      .then((filas) => { if (vigente) setPendientes(filas) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [clienteId])

  const razon = borrador.razon_social_id ? Number(borrador.razon_social_id) : null
  // Una orden que ya tiene OTRA razón social no entra en este comprobante: el
  // backend la rechaza, y ofrecerla en la lista invita a mandarla. Las que no
  // tienen ninguna heredan la del comprobante.
  const visibles = useMemo(() => pendientes.filter(
    (o) => razon != null && (o.razon_social_id == null || o.razon_social_id === razon),
  ), [pendientes, razon])

  // Se factura lo elegido **y visible**: si cambia la razón social, lo que dejó
  // de poder facturarse deja de contar, en la vista previa y en el envío.
  const aFacturar = visibles.filter((o) => elegidas.includes(o.id))
  const totalPrevio = sumarImportes(aFacturar.map((o) => o.total))
  const todasElegidas = visibles.length > 0 && aFacturar.length === visibles.length

  const set = (c: Partial<Borrador>) => setBorrador((b) => ({ ...b, ...c }))

  const alternar = (id: number) => setElegidas((previas) => (
    previas.includes(id) ? previas.filter((i) => i !== id) : [...previas, id]
  ))

  const columnas = useMemo(() => [
    {
      id: 'elegir',
      header: () => (
        <input
          type="checkbox"
          aria-label={todasElegidas ? 'Desmarcar todas' : 'Marcar todas'}
          checked={todasElegidas}
          onChange={() => setElegidas(todasElegidas ? [] : visibles.map((o) => o.id))}
        />
      ),
      cell: ({ row }: { row: { original: Orden } }) => (
        <input
          type="checkbox"
          aria-label={`Elegir la orden ${row.original.id}`}
          checked={elegidas.includes(row.original.id)}
          // La fila entera ya alterna (ver `onRowClick`). Sin esto el click en
          // la casilla lo haría dos veces y quedaría como estaba.
          onChange={() => {}}
          onClick={(e) => { e.stopPropagation(); alternar(row.original.id) }}
        />
      ),
    },
    { accessorKey: 'id', header: sortableHeader('Orden') },
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'remito', header: 'Remito', accessorFn: (o: Orden) => o.remito || 's/n' },
    { id: 'tramo', header: 'Tramo',
      accessorFn: (o: Orden) => `${nombreDe(opciones?.localidades, o.origen_id)} - ${nombreDe(opciones?.localidades, o.destino_id)}` },
    { id: 'total', header: sortableHeader('Total'),
      accessorFn: (o: Orden) => formatearImporte(o.total) },
  ], [elegidas, opciones, todasElegidas, visibles])

  async function facturar() {
    setError(null)
    setEnviando(true)
    try {
      const creado = await comprobantes.facturar({
        fecha: borrador.fecha,
        cliente_id: Number(clienteId),
        razon_social_id: Number(borrador.razon_social_id),
        tipo: borrador.tipo,
        punto_venta: Number(borrador.punto_venta),
        numero: Number(borrador.numero),
        orden_ids: aFacturar.map((o) => o.id),
      })
      // Se vuelve al listado **con el comprobante recién hecho abierto**: la
      // pregunta que sigue a facturar es siempre "¿cómo quedó?".
      navegar(creado?.id ? `/comprobantes?ver=${creado.id}` : '/comprobantes')
    } catch (e) {
      setError(mensajeDeError(e))
      setEnviando(false)
    }
  }

  const faltan = !clienteId ? 'Elegí el cliente.'
    : !borrador.razon_social_id ? 'Elegí la razón social.'
    : !borrador.numero ? 'Falta el número del comprobante.'
    : aFacturar.length === 0 ? 'No elegiste ninguna orden.'
    : null

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Volver a Comprobantes">
          <Link to="/comprobantes"><ArrowLeft className="size-4" /></Link>
        </Button>
        <h1 className="text-xl font-semibold">Facturar pendientes</h1>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <section className="mb-6 rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Datos del comprobante</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <Campo id="n-fecha" etiqueta="Fecha" tipo="date" valor={borrador.fecha}
                 alCambiar={(v) => set({ fecha: v })} />
          <Elegir id="n-cliente" etiqueta="Cliente" vacio="Elegir…"
                  valor={clienteId} opciones={opciones?.clientes ?? []}
                  alCambiar={(v) => {
                    setElegidas([])
                    setParams(v ? { cliente: v } : {}, { replace: true })
                  }} />
          <Eleccion id="n-razon" etiqueta="Razón social" valor={borrador.razon_social_id}
                    alCambiar={(v) => set({ razon_social_id: v })}>
            <option value="">Elegir…</option>
            {(opciones?.razones ?? []).map((r) => (
              <option key={r.id} value={r.id}>{r.etiqueta}</option>
            ))}
          </Eleccion>
          <Eleccion id="n-tipo" etiqueta="Tipo" valor={borrador.tipo}
                    alCambiar={(v) => set({ tipo: v })}>
            <option value="factura_a">Factura A</option>
            <option value="factura_b">Factura B</option>
            <option value="factura_c">Factura C</option>
          </Eleccion>
          <Campo id="n-pv" etiqueta="Punto de venta" valor={borrador.punto_venta}
                 alCambiar={(v) => set({ punto_venta: v })} />
          <Campo id="n-numero" etiqueta="Número" valor={borrador.numero}
                 alCambiar={(v) => set({ numero: v })} />
        </div>
      </section>

      <section className="mb-6">
        <div className="mb-2 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold">Órdenes pendientes</h2>
          {visibles.length > 0 && (
            <span className="text-muted-foreground text-sm">
              {visibles.length} disponible/s
            </span>
          )}
        </div>
        {!clienteId || !borrador.razon_social_id ? (
          <p className="text-muted-foreground rounded border p-4 text-sm">
            Elegí el cliente y la razón social para ver qué se puede facturar.
          </p>
        ) : (
          <DataTable
            columns={columnas}
            data={visibles}
            onRowClick={(o: Orden) => alternar(o.id)}
            emptyMessage={cargando ? 'Cargando…'
              : 'Este cliente no tiene órdenes pendientes para esa razón social.'}
          />
        )}
      </section>

      {/* Pegado abajo: con 82 órdenes en pantalla, un total que hay que ir a
          buscar al final del scroll no se mira antes de confirmar. */}
      <div className="bg-background sticky bottom-0 flex flex-wrap items-center justify-between gap-3 border-t py-3">
        <span className="text-sm">
          {aFacturar.length} orden/es elegida/s
        </span>
        <div className="flex items-center gap-4">
          {/* Vista previa: el importe que queda guardado lo calcula el
              servidor sobre las mismas órdenes. La suma de acá va en
              centavos enteros, no en punto flotante. */}
          <span className="text-lg font-semibold">
            Total: {formatearImporte(totalPrevio)}
          </span>
          <Button onClick={facturar} disabled={faltan != null || enviando}>
            {enviando ? 'Facturando…' : 'Facturar'}
          </Button>
        </div>
      </div>
      {faltan && (
        // Decir POR QUÉ no se puede: un botón gris sin motivo obliga a
        // adivinar cuál de los cinco campos falta.
        <p className="text-muted-foreground pb-2 text-right text-xs">{faltan}</p>
      )}
    </div>
  )
}
