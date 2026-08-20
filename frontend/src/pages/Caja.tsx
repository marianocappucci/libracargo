/** Cobros y pagos. Cada movimiento con tercero deja su contrapartida en la
 *  cuenta corriente, y eso lo hace el servidor en la misma transacción. */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { MovimientoCaja, Rol } from '@/api/cuentas'
import { caja } from '@/api/cuentas'
import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import type { Columna } from '@/components/impresion'
import { BotonImprimir, traerTodo } from '@/components/impresion'
import { sumarImportes } from '@/api/comprobantes'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

type Borrador = {
  fecha: string
  tipo: 'ingreso' | 'egreso'
  concepto: string
  descripcion: string
  tercero_id: string
  rol: '' | Rol
  importe: string
  medio_pago: string
  recibo: string
}

// La fecha por defecto es la de Argentina, no la de UTC: ver `hoyEnArgentina`.
// Un cobro cargado de noche nacía con la fecha de mañana.
const VACIO: Borrador = {
  fecha: hoyEnArgentina(), tipo: 'ingreso', concepto: '', descripcion: '',
  tercero_id: '', rol: '', importe: '', medio_pago: 'efectivo', recibo: '',
}

function Texto({ id, etiqueta, valor, alCambiar, tipo = 'text' }: {
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

function Opcion({ id, etiqueta, valor, alCambiar, deshabilitado, children }: {
  id: string; etiqueta: string; valor: string
  alCambiar: (v: string) => void; deshabilitado?: boolean; children: React.ReactNode
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <select id={id} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
              disabled={deshabilitado} value={valor}
              onChange={(e) => alCambiar(e.target.value)}>
        {children}
      </select>
    </div>
  )
}

export default function Caja() {
  const [filas, setFilas] = useState<MovimientoCaja[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [tipo, setTipo] = useState('')
  const [abierto, setAbierto] = useState(false)
  const [borrador, setBorrador] = useState<Borrador>(VACIO)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  const recargar = useCallback(() => {
    setCargando(true)
    caja.listar({ desde, hasta, tipo })
      .then(setFilas)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [desde, hasta, tipo])

  useEffect(recargar, [recargar])

  const terceros = [...(opciones?.clientes ?? []), ...(opciones?.fleteros ?? [])]
  const set = (c: Partial<Borrador>) => setBorrador((b) => ({ ...b, ...c }))

  async function guardar() {
    setError(null)
    try {
      await caja.registrar({
        ...borrador,
        tercero_id: borrador.tercero_id ? Number(borrador.tercero_id) : null,
        // Sin tercero no hay rol: el backend rechaza el par incompleto, y
        // mandarlo a medias seria pedirle que adivine cual de las tres cuentas.
        rol: borrador.tercero_id ? (borrador.rol || null) : null,
        descripcion: borrador.descripcion || null,
        recibo: borrador.recibo || null,
      })
      setAbierto(false)
      setBorrador(VACIO)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  const COLUMNAS_IMPRESAS: Columna<MovimientoCaja>[] = [
    { encabezado: 'Fecha', valor: (m) => m.fecha },
    { encabezado: 'Tipo', valor: (m) => m.tipo },
    { encabezado: 'Concepto', valor: (m) => m.concepto },
    { encabezado: 'Tercero',
      valor: (m) => terceros.find((t) => t.id === m.tercero_id)?.etiqueta ?? '' },
    { encabezado: 'Medio', valor: (m) => m.medio_pago },
    { encabezado: 'Recibo', valor: (m) => m.recibo },
    { encabezado: 'Importe', valor: (m) => m.importe, numerica: true, moneda: true },
  ]

  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha') },
    { id: 'tipo', header: 'Tipo', accessorFn: (m: MovimientoCaja) => m.tipo,
      cell: ({ row }: { row: { original: MovimientoCaja } }) => (
        <Badge variant={row.original.tipo === 'ingreso' ? 'secondary' : 'destructive'}>
          {row.original.tipo}
        </Badge>
      ) },
    { accessorKey: 'concepto', header: sortableHeader('Concepto') },
    { id: 'tercero', header: 'Tercero',
      accessorFn: (m: MovimientoCaja) =>
        terceros.find((t) => t.id === m.tercero_id)?.etiqueta ?? '' },
    { accessorKey: 'medio_pago', header: 'Medio' },
    { accessorKey: 'recibo', header: 'Recibo' },
    { id: 'importe', header: sortableHeader('Importe'),
      accessorFn: (m: MovimientoCaja) => formatearImporte(m.importe) },
  ]

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Caja</h1>
        <div className="flex gap-2">
          <BotonImprimir
            titulo="Movimientos de caja"
            filtros={[desde && `desde ${desde}`, hasta && `hasta ${hasta}`,
                      tipo && `tipo ${tipo}`].filter(Boolean).join(' · ') || 'sin filtros'}
            columnas={COLUMNAS_IMPRESAS}
            traer={() => traerTodo(async (desplazamiento, limite) =>
              desplazamiento > 0 ? [] : caja.listar({ desde, hasta, tipo, limite }))}
            totales={(f) => [
              { etiqueta: 'Ingresos',
                valor: sumarImportes(f.filter((m) => m.tipo === 'ingreso').map((m) => m.importe)) },
              { etiqueta: 'Egresos',
                valor: sumarImportes(f.filter((m) => m.tipo === 'egreso').map((m) => m.importe)) },
            ]}
          />
          <Button onClick={() => { setBorrador(VACIO); setError(null); setAbierto(true) }}>
            <Plus className="size-4" /> Nuevo movimiento
          </Button>
        </div>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Texto id="c-desde" etiqueta="Desde" tipo="date" valor={desde} alCambiar={setDesde} />
        <Texto id="c-hasta" etiqueta="Hasta" tipo="date" valor={hasta} alCambiar={setHasta} />
        <Opcion id="c-tipo" etiqueta="Tipo" valor={tipo} alCambiar={setTipo}>
          <option value="">Todos</option>
          <option value="ingreso">Ingresos</option>
          <option value="egreso">Egresos</option>
        </Opcion>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={columnas}
        data={filas}
        emptyMessage={cargando ? 'Cargando…' : 'No hay movimientos en ese rango.'}
      />

      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader><DialogTitle>Nuevo movimiento de caja</DialogTitle></DialogHeader>
          <div className="grid gap-3 md:grid-cols-2">
            <Texto id="m-fecha" etiqueta="Fecha" tipo="date" valor={borrador.fecha}
                   alCambiar={(v) => set({ fecha: v })} />
            <Opcion id="m-tipo" etiqueta="Tipo" valor={borrador.tipo}
                    alCambiar={(v) => set({ tipo: v as 'ingreso' | 'egreso' })}>
              <option value="ingreso">Ingreso (cobro)</option>
              <option value="egreso">Egreso (pago)</option>
            </Opcion>
            <Texto id="m-concepto" etiqueta="Concepto" valor={borrador.concepto}
                   alCambiar={(v) => set({ concepto: v })} />
            <Texto id="m-importe" etiqueta="Importe" valor={borrador.importe}
                   alCambiar={(v) => set({ importe: v })} />
            <Elegir id="m-tercero" etiqueta="Tercero" valor={borrador.tercero_id}
                    vacio="Ninguno (gasto general)" opciones={terceros}
                    alCambiar={(v) => set({ tercero_id: v })} />
            {/* Deshabilitado sin tercero: el rol sin tercero es un par
                incompleto que el backend rechaza, y ofrecerlo invita a
                mandarlo. */}
            <Opcion id="m-rol" etiqueta="Cuenta del tercero" valor={borrador.rol}
                    deshabilitado={!borrador.tercero_id}
                    alCambiar={(v) => set({ rol: v as Rol })}>
              <option value="">Elegir…</option>
              <option value="cliente">Cliente</option>
              <option value="fletero">Fletero</option>
              <option value="proveedor">Proveedor</option>
            </Opcion>
            <Opcion id="m-medio" etiqueta="Medio de pago" valor={borrador.medio_pago}
                    alCambiar={(v) => set({ medio_pago: v })}>
              <option value="efectivo">Efectivo</option>
              <option value="transferencia">Transferencia</option>
              <option value="cheque">Cheque</option>
              <option value="otro">Otro</option>
            </Opcion>
            <Texto id="m-recibo" etiqueta="Recibo" valor={borrador.recibo}
                   alCambiar={(v) => set({ recibo: v })} />
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setAbierto(false)}>Cancelar</Button>
            <Button onClick={guardar}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
