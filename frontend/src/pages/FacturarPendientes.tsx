/** Facturar pendientes: una pantalla, no un modal. **Emite el comprobante directo por ARCA** (ADR-048).
 *
 * 🔑 **Antes (ADR-032) acá se generaba una pre factura**, un documento intermedio que se mandaba al cliente y se
 * facturaba después. El humano la sacó el 2026-10-13: ahora el CAE sale en el momento, y como no se deshace (se
 * corrige con una nota de crédito) el botón pide una confirmación. Sigue sin haber punto de venta ni número: los
 * pone ARCA. El emisor es siempre la empresa (ADR-035). Los ítems y los importes salen de las órdenes, nunca de
 * esta pantalla: lo que se ve abajo es sólo la vista previa.
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

import type { AvisoFce, CuentasFce, TipoComprobante } from '@/api/comprobantes'
import { comprobantes, etiquetaDeCuenta, sumarImportes } from '@/api/comprobantes'
import type { Opciones, Orden } from '@/api/ordenes'
import { cargarOpciones, ordenes as apiOrdenes } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS_LC } from '@/iconos'
import { irA } from '@/navegacion'

type Borrador = {
  fecha: string
  tipo: string
  /** Sólo la FCE lo lleva, y ARCA la rechaza sin él. */
  vencimiento: string
  /** Sólo la FCE: el CBU de la cuenta donde se cobra (libracore ADR-040). `''` es la predeterminada. */
  cuenta: string
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
  fecha: hoyEnArgentina(),
  tipo: 'factura_a', vencimiento: '', cuenta: '',
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
      {/* select-cerrado: el tipo de comprobante, `<option>` escritos en cada uso (seis). El cliente va por `Elegir`, que se busca */}
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
  // Emitir por ARCA no se deshace: el primer click pide confirmar, el segundo emite.
  const [confirmando, setConfirmando] = useState(false)
  const [aviso, setAviso] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const clienteId = params.get('cliente') ?? ''

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // Las pendientes del cliente elegido. Sin cliente no se piden: un comprobante es de un solo cliente, y una lista de
  // todos invitaría a mezclarlos.
  useEffect(() => {
    if (!clienteId) { setPendientes([]); return }
    let vigente = true
    setCargando(true)
    apiOrdenes.listar({ cliente_id: Number(clienteId), facturada: false, estado: 'pendiente' })
      .then((lista) => {
        if (vigente) setPendientes([...lista].sort((x, y) => (y.fecha.localeCompare(x.fecha)) || (y.id - x.id)))
      })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
      .finally(() => { if (vigente) setCargando(false) })
    return () => { vigente = false }
  }, [clienteId])

  // Todas las pendientes del cliente se pueden facturar: hay un solo emisor.
  const visibles = pendientes

  // Se factura lo elegido **y visible**: si cambia el cliente, lo que dejó de
  // estar a la vista deja de contar, en la vista previa y en el envío.
  const aFacturar = visibles.filter((o) => elegidas.includes(o.id))
  const totalPrevio = sumarImportes(aFacturar.map((o) => o.total))
  const todasElegidas = visibles.length > 0 && aFacturar.length === visibles.length

  const set = (c: Partial<Borrador>) => { setConfirmando(false); setBorrador((b) => ({ ...b, ...c })) }
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
    if (clienteNumero == null || fce || totalPrevio === '0.00') return
    let vigente = true
    // Un respiro: marcar diez órdenes seguidas no tiene que ser diez consultas a ARCA.
    const espera = setTimeout(() => {
      comprobantes
        .fceCorresponde({ cliente_id: clienteNumero, total: totalPrevio, fecha: borrador.fecha })
        .then((r) => {
          if (vigente && r && typeof r === 'object' && 'disponible' in r) setAvisoFce(r)
        })
        .catch(() => { /* es un aviso: si falla, se factura como siempre */ })
    }, 400)
    return () => { vigente = false; clearTimeout(espera) }
  }, [clienteNumero, fce, totalPrevio, borrador.fecha])
  const correspondeFce = !fce && avisoFce?.disponible === true && avisoFce.corresponde === true

  // ── En qué cuenta se cobra la FCE (libracore ADR-040) ────────────────────
  // Las cuentas son de la empresa y no cambian con el cliente: se piden una vez, cuando hace falta elegir.
  const [cuentasFce, setCuentasFce] = useState<CuentasFce | null>(null)
  useEffect(() => {
    if (!fce || cuentasFce) return
    let vigente = true
    comprobantes.fceCuentas()
      // Una respuesta sin lista (un servidor viejo) es «no hay cuentas», no un error de pantalla.
      .then((r) => {
        if (vigente) setCuentasFce(r && Array.isArray(r.cuentas) ? r : { cuentas: [], predeterminada: '', transmision: '' })
      })
      .catch(() => { if (vigente) setCuentasFce({ cuentas: [], predeterminada: '', transmision: '' }) })
    return () => { vigente = false }
  }, [fce, cuentasFce])
  // Sin elegir, la predeterminada: lo que se ve es lo que va a salir.
  const cuentaElegida = borrador.cuenta || cuentasFce?.predeterminada || ''

  const alternar = (id: number) => {
    setConfirmando(false)
    setElegidas((previas) => (previas.includes(id) ? previas.filter((i) => i !== id) : [...previas, id]))
  }

  const columnas = useMemo(() => [
    {
      id: 'elegir',
      header: () => (
        <input
          type="checkbox"
          aria-label={todasElegidas ? 'Desmarcar todas' : 'Marcar todas'}
          checked={todasElegidas}
          onChange={() => { setConfirmando(false); setElegidas(todasElegidas ? [] : visibles.map((o) => o.id)) }}
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

  async function emitir() {
    setError(null)
    setAviso(null)
    setEnviando(true)
    try {
      // Sin ítems, importes, punto de venta ni número: salen de las órdenes, y el número lo pone ARCA.
      const hecho = await comprobantes.facturarOrdenes({
        cliente_id: Number(clienteId),
        fecha: borrador.fecha,
        tipo: borrador.tipo as TipoComprobante,
        // Sólo la FCE lleva vencimiento de pago y cuenta de cobro; `undefined` no viaja en el JSON. La cuenta
        // va siempre que es FCE: `''` vuelve a la predeterminada.
        fecha_vencimiento_pago: fce ? borrador.vencimiento : undefined,
        fce_cbu: fce ? borrador.cuenta : undefined,
        orden_ids: aFacturar.map((o) => o.id),
      })
      if (hecho && 'ensayo' in hecho) {
        // Homologación: se corrió todo contra ARCA y no se guardó nada. Las órdenes siguen pendientes.
        setAviso(`Ensayo contra ${hecho.ambiente}: ARCA autorizó una factura de prueba `
          + `(CAE ${hecho.cae ?? 's/n'}) y no se guardó nada.`)
        setConfirmando(false)
        setEnviando(false)
        return
      }
      // Se va al comprobante: la pregunta que sigue es siempre «¿cómo quedó?», y desde ahí se baja el PDF.
      navegar(hecho?.id ? irA.comprobante(hecho.id) : '/comprobantes')
    } catch (e) {
      setError(mensajeDeError(e))
      setConfirmando(false)
      setEnviando(false)
    }
  }

  const faltan = !clienteId ? 'Elegí el cliente.'
    : fce && !borrador.vencimiento ? 'Falta el vencimiento de pago.'
    // `AAAA-MM-DD` ordena como texto. Se mira acá y no sólo en el backend porque la
    // fecha puede cambiar **después** de que se propuso el vencimiento a 30 días.
    : fce && borrador.vencimiento < borrador.fecha
      ? 'El vencimiento de pago no puede ser anterior a la fecha del comprobante.'
    : aFacturar.length === 0 ? 'No elegiste ninguna orden.'
    : null

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <Button variant="ghost" size="icon" asChild aria-label="Volver a Comprobantes">
          <Link to="/comprobantes"><ArrowLeft className="size-4" /></Link>
        </Button>
        <TituloPantalla icono={ICONOS_LC.comprobantes}>Facturar pendientes</TituloPantalla>
      </div>

      <p className="text-muted-foreground mb-4 text-sm">
        Se factura <strong>directo por ARCA</strong>: el CAE sale en el momento y el comprobante no se puede
        deshacer (se corrige con una nota de crédito). Los importes salen de las órdenes; el punto de venta y el
        número los pone ARCA. ¿Una factura sin órdenes? Usá{' '}
        <Link className="underline" to={irA.nuevaFactura()}>Nueva factura</Link>.
      </p>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {aviso && <p role="status" className="mb-4 rounded border p-3 text-sm font-semibold">{aviso}</p>}

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
              La empresa todavía no puede emitirla: cargá el CBU y la modalidad de
              transmisión en Configuración → ARCA.
            </p>
          )}
        </section>
      )}

      <section className="mb-6 rounded border p-4">
        <h2 className="mb-3 text-sm font-semibold">Datos del comprobante</h2>
        <div className="grid gap-3 md:grid-cols-3">
          <Campo id="n-fecha" etiqueta="Fecha" tipo="date" valor={borrador.fecha}
                 alCambiar={(v) => set({ fecha: v })} />
          <Elegir id="n-cliente" etiqueta="Cliente" vacio="Elegir…"
                  valor={clienteId} opciones={opciones?.clientes ?? []}
                  alCambiar={(v) => {
                    setConfirmando(false)
                    setElegidas([])
                    setParams(v ? { cliente: v } : {}, { replace: true })
                  }} />
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
          {fce && cuentasFce && (cuentasFce.cuentas.length > 0 ? (
            // Se busca escribiendo el alias o el CBU: la etiqueta lleva los dos.
            <Elegir id="n-cuenta" etiqueta="Cobrar en" vacio="La predeterminada" valor={cuentaElegida}
                    opciones={cuentasFce.cuentas.map((c) => ({
                      id: c.cbu,
                      etiqueta: c.cbu === cuentasFce.predeterminada
                        ? `${etiquetaDeCuenta(c)} (predeterminada)` : etiquetaDeCuenta(c),
                    }))}
                    alCambiar={(v) => set({ cuenta: v === cuentasFce.predeterminada ? '' : v })} />
          ) : (
            <p role="status" className="text-muted-foreground self-end text-sm md:col-span-3">
              No hay cuentas para cobrar la factura de crédito: cargalas en Configuración → ARCA.
            </p>
          ))}
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
        {!clienteId ? (
          <p className="text-muted-foreground rounded border p-4 text-sm">
            Elegí el cliente para ver qué se puede facturar.
          </p>
        ) : (
          <DataTable
            columns={columnas}
            data={visibles}
            onRowClick={(o: Orden) => alternar(o.id)}
            emptyMessage={cargando ? 'Cargando…'
              : 'Este cliente no tiene órdenes pendientes y libres.'}
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
          {confirmando ? (
            <>
              <span className="text-sm">Se emite por ARCA ahora y no se deshace.</span>
              <Button variant="ghost" onClick={() => setConfirmando(false)} disabled={enviando}>No</Button>
              <Button onClick={emitir} disabled={enviando}>
                {enviando ? 'Emitiendo…' : 'Confirmar y emitir'}
              </Button>
            </>
          ) : (
            <Button onClick={() => setConfirmando(true)} disabled={faltan != null || enviando}>
              Facturar
            </Button>
          )}
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
