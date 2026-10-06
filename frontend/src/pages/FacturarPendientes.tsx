/** Facturar pendientes: una pantalla, no un modal. Genera la **pre factura** (ADR-032).
 *
 * 🔑 **Acá ya no se factura: se genera la pre factura**, el documento que se manda al cliente para que
 * confirme los datos. La factura sale después, de la pre factura, por ARCA (pantalla `PreFactura`). Por eso
 * no hay punto de venta ni número: el de la pre factura (`PF-0001`) lo pone el motor, y el de la factura lo
 * pone ARCA. Es la misma pantalla para **editar** una pre factura abierta (`/pre-facturas/:id/editar`):
 * cambian las órdenes, la razón social, el tipo y las fechas, pero no el cliente.
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
import { ArrowLeft, Receipt } from 'lucide-react'
import type { ReactNode } from 'react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'

import type { AvisoFce } from '@/api/comprobantes'
import { comprobantes, sumarImportes } from '@/api/comprobantes'
import type { Opciones, Orden } from '@/api/ordenes'
import { cargarOpciones, ordenes as apiOrdenes } from '@/api/ordenes'
import type { PreFactura } from '@/api/pre-facturas'
import { ESTADOS_ABIERTOS, NOMBRE_DE_ESTADO, preFacturas, tipoDe } from '@/api/pre-facturas'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

type Borrador = {
  fecha: string
  razon_social_id: string
  tipo: string
  /** Sólo la FCE lo lleva, y ARCA la rechaza sin él. */
  vencimiento: string
}

/** Una fecha `AAAA-MM-DD` más `dias`, por componentes: ni zona horaria ni `toISOString`. */
function masDias(iso: string, dias: number): string {
  const [a, m, d] = iso.split('-').map(Number)
  const f = new Date(Date.UTC(a, m - 1, d + dias))
  const dos = (n: number) => String(n).padStart(2, '0')
  return `${f.getUTCFullYear()}-${dos(f.getUTCMonth() + 1)}-${dos(f.getUTCDate())}`
}

/** La Factura de Crédito Electrónica MiPyME: exige vencimiento de pago. */
const esFce = (tipo: string) => tipo.startsWith('fce_')

// La fecha por defecto sale de la de Argentina y no de `toISOString`: un
// comprobante cargado de noche nacía con la fecha de mañana.
const VACIO: Borrador = {
  fecha: hoyEnArgentina(), razon_social_id: '',
  tipo: 'factura_a', vencimiento: '',
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

/** `titulo` lo pone quien la usa para **editar** (`EditarPreFactura`): el título de editar es otro
 *  («Editar pre factura N»). Las dos cuelgan de «Comprobantes» en el menú. Sin él, es «Facturar pendientes». */
export default function FacturarPendientes({ titulo }: { titulo?: (numero: string) => ReactNode } = {}) {
  const [params, setParams] = useSearchParams()
  const navegar = useNavigate()
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [borrador, setBorrador] = useState<Borrador>(VACIO)
  const [pendientes, setPendientes] = useState<Orden[]>([])
  const [elegidas, setElegidas] = useState<number[]>([])
  const [cargando, setCargando] = useState(false)
  const [enviando, setEnviando] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // `/pre-facturas/:id/editar` es esta misma pantalla sobre una pre factura que ya existe.
  const { id: idDeLaRuta } = useParams()
  const editandoId = idDeLaRuta ? Number(idDeLaRuta) : null
  const editando = editandoId != null
  const [existente, setExistente] = useState<PreFactura | null>(null)

  // Al editar, el cliente es el de la pre factura y no se cambia: otro cliente es otra pre factura.
  const clienteId = editando ? String(existente?.cliente_id ?? '') : (params.get('cliente') ?? '')

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // La pre factura que se edita: sus datos pasan al borrador y sus órdenes quedan elegidas.
  useEffect(() => {
    if (editandoId == null) return
    let vigente = true
    preFacturas.ver(editandoId)
      .then((p) => {
        if (!vigente) return
        setExistente(p)
        setBorrador({
          fecha: p.fecha_sugerida, razon_social_id: String(p.razon_social_id ?? ''),
          tipo: tipoDe(p) ?? 'factura_a', vencimiento: p.fecha_vencimiento_pago ?? '',
        })
        setElegidas(p.orden_ids)
      })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [editandoId])

  // Las pendientes **libres** del cliente elegido (las reservadas en otra pre factura no se pueden incluir),
  // más —al editar— las que ya son de esta pre factura. Sin cliente no se piden: una pre factura es de un
  // solo cliente, y una lista de todos invitaría a mezclarlos.
  useEffect(() => {
    if (!clienteId) { setPendientes([]); return }
    let vigente = true
    setCargando(true)
    const libres = apiOrdenes.listar(
      { cliente_id: Number(clienteId), facturada: false, estado: 'pendiente', reservada: false })
    const propias = editandoId != null
      ? apiOrdenes.listar({ pre_factura_id: editandoId }) : Promise.resolve([] as Orden[])
    Promise.all([libres, propias])
      .then(([a, b]) => {
        if (!vigente) return
        const porId = new Map([...a, ...b].map((o) => [o.id, o]))
        setPendientes([...porId.values()].sort((x, y) => (y.fecha.localeCompare(x.fecha)) || (y.id - x.id)))
      })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [clienteId, editandoId])

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
  const fce = esFce(borrador.tipo)

  // ── El aviso de FCE ──────────────────────────────────────────────────────
  // ARCA no frena una factura común a un receptor obligado a recibir FCE, y una
  // factura emitida no se cambia: el aviso tiene que llegar **antes** de emitir.
  // La regla es del motor; acá sólo se pregunta con lo que se está por facturar.
  // Es un aviso y no un bloqueo: si no se puede preguntar, no se muestra nada.
  const [avisoFce, setAvisoFce] = useState<AvisoFce | null>(null)
  const clienteNumero = clienteId ? Number(clienteId) : null
  useEffect(() => {
    setAvisoFce(null)
    if (clienteNumero == null || razon == null || fce || totalPrevio === '0.00') return
    let vigente = true
    // Un respiro: marcar diez órdenes seguidas no tiene que ser diez consultas a ARCA.
    const espera = setTimeout(() => {
      comprobantes
        .fceCorresponde({ razon_social_id: razon, cliente_id: clienteNumero,
                          total: totalPrevio, fecha: borrador.fecha })
        .then((r) => {
          if (vigente && r && typeof r === 'object' && 'disponible' in r) setAvisoFce(r)
        })
        .catch(() => { /* es un aviso: si falla, se factura como siempre */ })
    }, 400)
    return () => { vigente = false; clearTimeout(espera) }
  }, [clienteNumero, razon, fce, totalPrevio, borrador.fecha])
  const correspondeFce = !fce && avisoFce?.disponible === true && avisoFce.corresponde === true

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

  async function guardar() {
    setError(null)
    setEnviando(true)
    try {
      // Sin ítems, importes, punto de venta ni número: salen de las órdenes, y la pre factura lleva el suyo.
      const datos = {
        fecha: borrador.fecha,
        razon_social_id: Number(borrador.razon_social_id),
        tipo: borrador.tipo,
        // Sólo la FCE lleva vencimiento de pago; `undefined` no viaja en el JSON.
        fecha_vencimiento_pago: fce ? borrador.vencimiento : undefined,
        orden_ids: aFacturar.map((o) => o.id),
      }
      const hecha = editandoId != null
        ? await preFacturas.editar(editandoId, datos)
        : await preFacturas.crear({ ...datos, cliente_id: Number(clienteId) })
      // Se va a la pre factura: la pregunta que sigue es siempre «¿cómo quedó?», y lo que sigue es mandarla.
      navegar(hecha?.id ? `/pre-facturas/${hecha.id}` : '/pre-facturas')
    } catch (e) {
      setError(mensajeDeError(e))
      setEnviando(false)
    }
  }

  // Una facturada o anulada no se edita.
  const cerrada = editando && existente != null && !ESTADOS_ABIERTOS.includes(existente.estado)

  const faltan = !clienteId ? 'Elegí el cliente.'
    : !borrador.razon_social_id ? 'Elegí la razón social.'
    : fce && !borrador.vencimiento ? 'Falta el vencimiento de pago.'
    // `AAAA-MM-DD` ordena como texto. Se mira acá y no sólo en el backend porque la
    // fecha puede cambiar **después** de que se propuso el vencimiento a 30 días.
    : fce && borrador.vencimiento < borrador.fecha
      ? 'El vencimiento de pago no puede ser anterior a la fecha del comprobante.'
    : aFacturar.length === 0 ? 'No elegiste ninguna orden.'
    : null

  return (
    <div className="p-4">
      <div className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild
                aria-label={editando ? 'Volver a la pre factura' : 'Volver a Comprobantes'}>
          <Link to={editando ? `/pre-facturas/${editandoId}` : '/comprobantes'}>
            <ArrowLeft className="size-4" />
          </Link>
        </Button>
        {editando && titulo
          ? titulo(existente?.numero_interno ?? '')
          : <TituloPantalla icono={Receipt}>Facturar pendientes</TituloPantalla>}
      </div>

      <p className="text-muted-foreground mb-4 text-sm">
        Se genera una <strong>pre factura</strong>: un documento sin valor fiscal que se manda al cliente
        para que confirme los datos. La factura se emite después, por ARCA, desde la pre factura; el
        punto de venta y el número los pone ARCA.
      </p>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {cerrada && existente && (
        <p role="alert" className="mb-4 rounded border p-3 text-sm">
          La pre factura {existente.numero_interno} está {NOMBRE_DE_ESTADO[existente.estado].toLowerCase()}:
          no se edita.
        </p>
      )}

      {editando && existente && (existente.estado === 'enviado' || existente.estado === 'aceptado') && (
        <p role="status" className="mb-4 rounded border border-amber-500/50 p-3 text-sm">
          Está {NOMBRE_DE_ESTADO[existente.estado].toLowerCase()}: si cambia algo, vuelve a Pendiente. El
          cliente vio otros datos, así que hay que volver a enviarla y a marcarla como aceptada.
        </p>
      )}

      {correspondeFce && avisoFce && (
        <section role="status" aria-label="Aviso de FCE"
                 className="mb-4 rounded border border-amber-500/50 p-4 text-sm">
          <h2 className="mb-1 font-semibold">
            A este comprobante le corresponde ser una factura de crédito electrónica
          </h2>
          <p className="mb-2 text-muted-foreground">
            El cliente está obligado a recibir FCE
            {avisoFce.monto_desde ? ` desde ${formatearImporte(avisoFce.monto_desde)}` : ''}, y
            este total lo supera. ARCA no frena una factura común, pero una vez emitida no se
            cambia.
          </p>
          {avisoFce.fce_habilitada ? (
            <Button variant="outline" size="sm" onClick={() => set({
              tipo: `fce_${borrador.tipo.slice(-1)}`,
              vencimiento: borrador.vencimiento || masDias(borrador.fecha, 30),
            })}>
              Pasar a factura de crédito electrónica
            </Button>
          ) : (
            <p>
              Esta razón social todavía no puede emitirla: cargá el CBU y la modalidad de
              transmisión en Configuración → ARCA.
            </p>
          )}
        </section>
      )}

      <section className="mb-6 rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Datos de la pre factura</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <Campo id="n-fecha" etiqueta="Fecha" tipo="date" valor={borrador.fecha}
                 alCambiar={(v) => set({ fecha: v })} />
          <Elegir id="n-cliente" etiqueta="Cliente" vacio="Elegir…" deshabilitado={editando}
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
                    alCambiar={(v) => set({
                      tipo: v,
                      // Al pasar a FCE se propone 30 días: se puede cambiar.
                      ...(esFce(v) && !borrador.vencimiento
                        ? { vencimiento: masDias(borrador.fecha, 30) } : {}),
                    })}>
            <option value="factura_a">Factura A</option>
            <option value="factura_b">Factura B</option>
            <option value="factura_c">Factura C</option>
            <option value="fce_a">Factura de crédito electrónica A</option>
            <option value="fce_b">Factura de crédito electrónica B</option>
            <option value="fce_c">Factura de crédito electrónica C</option>
          </Eleccion>
          {fce && (
            <Campo id="n-vencimiento" etiqueta="Vencimiento de pago" tipo="date"
                   valor={borrador.vencimiento}
                   alCambiar={(v) => set({ vencimiento: v })} />
          )}
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
              : 'Este cliente no tiene órdenes pendientes y libres para esa razón social.'}
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
          <Button onClick={guardar} disabled={faltan != null || enviando || cerrada}>
            {editando
              ? (enviando ? 'Guardando…' : 'Guardar cambios')
              : (enviando ? 'Generando…' : 'Generar pre factura')}
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
