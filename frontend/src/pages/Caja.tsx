/** Cobros y pagos. Cada movimiento con tercero deja su contrapartida en la
 *  cuenta corriente, y eso lo hace el servidor en la misma transacción. */
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Ban, Pencil, Plus } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import type { MovimientoCaja, Rol } from '@/api/cuentas'
import { caja } from '@/api/cuentas'
import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { SelectCliente } from 'libra-ui/SelectCliente'

import { ALTA_DE_CLIENTE, aOpcionDeSelect, conTerceroNuevo, LISTA_DEL_ROL, opcionesCliente } from '@/api/clientes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { useAltaDeCliente } from '@/components/useAltaDeCliente'
import { irA } from '@/navegacion'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { ICONOS_LC } from '@/iconos'

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
const ROLES: Rol[] = ['cliente', 'fletero', 'proveedor']

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
      {/* select-cerrado: lo usan Tipo, Cuenta del tercero y Medio de pago, de dos a cuatro `<option>` escritos en cada uso. Los datos
          (el tercero) van por `SelectCliente`, que se busca escribiendo */}
      <select id={id} className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
              disabled={deshabilitado} value={valor}
              onChange={(e) => alCambiar(e.target.value)}>
        {children}
      </select>
    </div>
  )
}

export default function Caja() {
  const navegar = useNavigate()
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

  // Todos los terceros, no clientes + fleteros: sin los proveedores no se podía
  // registrar un pago a proveedor, y un movimiento cuyo tercero fuera uno
  // mostraba el **nombre en blanco** en la grilla y en la impresión, porque la
  // búsqueda por id no lo encontraba. Además, concatenar dos listas repetía al
  // tercero que tiene los dos roles.
  const terceros = opciones?.terceros ?? []
  const set = (c: Partial<Borrador>) => setBorrador((b) => ({ ...b, ...c }))
  const [editando, setEditando] = useState<MovimientoCaja | null>(null)
  // El alta en el lugar del «Tercero» es en el rol de la cuenta elegida (ADR-053); sin cuenta el campo está deshabilitado y el rol no importa.
  const alta = useAltaDeCliente(borrador.rol || 'cliente')
  const [altaAbierta, setAltaAbierta] = useState(false)

  /** Los terceros que tienen ese rol: la lista de la que se elige una vez elegida la cuenta. */
  const delRol = (r: Rol) => opciones?.[LISTA_DEL_ROL[r]] ?? []
  const tieneRol = (r: Rol, terceroId: string) => delRol(r).some((t) => String(t.id) === terceroId)

  /** 🔑 **Cuenta primero** (ADR-053). Cambiar la cuenta deja el tercero sólo si tiene ese rol: uno que no lo tiene iría a una cuenta que no es
   *  suya (el servidor lo rechaza, o peor, abre una cuenta de fletero a un cliente). «Ninguna» es un gasto general y se lleva el tercero. */
  function elegirCuenta(r: '' | Rol) {
    setAltaAbierta(false)   // el campo se remonta (su `key` es la cuenta) y el panel de alta se cierra sin avisar
    setBorrador((b) => ({ ...b, rol: r, tercero_id: r && b.tercero_id && tieneRol(r, b.tercero_id) ? b.tercero_id : '' }))
  }

  /** Abre el diálogo para uno que ya existe, o vacío para uno nuevo.
   *
   *  🔑 El `rol` no viene en el movimiento —vive en la contrapartida—. Al editar se lo deduce sólo si el tercero tiene **un** rol; si tiene más
   *  de uno arranca vacío, el tercero se ve (deshabilitado) y hay que elegir la cuenta: si es una de las suyas, el tercero queda. */
  function abrir(m: MovimientoCaja | null) {
    setEditando(m)
    setError(null)
    setAltaAbierta(false)
    const terceroId = m?.tercero_id == null ? '' : String(m.tercero_id)
    const suyos = terceroId ? ROLES.filter((r) => tieneRol(r, terceroId)) : []
    setBorrador(m
      ? {
        fecha: m.fecha, tipo: m.tipo, concepto: m.concepto,
        descripcion: m.descripcion ?? '',
        // Como cadena: es lo que el `<select>` maneja, y el borrador lo
        // convierte a numero recien al guardar.
        tercero_id: terceroId,
        rol: suyos.length === 1 ? suyos[0] : '', importe: m.importe, medio_pago: m.medio_pago,
        recibo: m.recibo ?? '',
      }
      : VACIO)
    setAbierto(true)
  }

  /** Cerrar sin guardar se lleva el error del formulario: si no, quedaba en la pantalla hablando de un movimiento que no se guardó. */
  function cerrar() {
    setAbierto(false)
    setError(null)
  }

  async function anular(m: MovimientoCaja) {
    setError(null)
    try {
      await caja.anular(m.id)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  async function guardar() {
    setError(null)
    // Un par a medias no se manda: el servidor lo rechaza con un 422 que no dice qué falta en esta pantalla.
    if (borrador.rol && !borrador.tercero_id) {
      setError('Falta el tercero: elegilo o dalo de alta, o elegí «Ninguna» en la cuenta si es un gasto general.')
      return
    }
    if (borrador.tercero_id && !borrador.rol) {
      setError('Falta la cuenta del tercero: elegí si es cliente, fletero o proveedor.')
      return
    }
    try {
      const cuerpo = {
        ...borrador,
        tercero_id: borrador.tercero_id ? Number(borrador.tercero_id) : null,
        // Sin tercero no hay rol: el backend rechaza el par incompleto, y
        // mandarlo a medias seria pedirle que adivine cual de las tres cuentas.
        rol: borrador.tercero_id ? (borrador.rol || null) : null,
        descripcion: borrador.descripcion || null,
        recibo: borrador.recibo || null,
      }
      if (editando) await caja.editar(editando.id, cuerpo)
      else await caja.registrar(cuerpo)
      setAbierto(false)
      setEditando(null)
      setBorrador(VACIO)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  // 🔴 **Los anchos son obligatorios acá, no cosmética.** El `DataTable` pasa a
  // `table-fixed` en cuanto **alguna** columna declara `size`, y entonces le
  // pone a la tabla un `minWidth` igual a la suma de los anchos. Las columnas
  // que no declaran ninguno caen al default de TanStack —150 px— así que con
  // siete sin declarar la tabla pedía **1.240 px** de mínimo y el contenedor
  // scrolleaba.
  //
  // Es la misma causa que tuvo el log de actividad, y se arregla igual: ancho
  // en todas, y `stretch` en la de texto libre, que se queda con el sobrante en
  // vez de empujar. El primitivo no se toca — sacarle el `nowrap` a `TableCell`
  // afectaría a todas las tablas del producto, y en las demás partir una fecha
  // o un importe en dos líneas se lee peor.
  const columnas = [
    { accessorKey: 'fecha', header: sortableHeader('Fecha'), size: 100 },
    { id: 'tipo', header: 'Tipo', size: 95, accessorFn: (m: MovimientoCaja) => m.tipo,
      cell: ({ row }: { row: { original: MovimientoCaja } }) => (
        <BadgeEstado tono={row.original.tipo === 'ingreso' ? 'ok' : 'negativo'}>
          {row.original.tipo}
        </BadgeEstado>
      ) },
    // La elástica: es la única de texto libre, y la que puede venir larga.
    { accessorKey: 'concepto', header: sortableHeader('Concepto'), size: 190,
      meta: { stretch: true, className: 'whitespace-normal break-words' } },
    { id: 'tercero', header: 'Tercero', size: 175,
      accessorFn: (m: MovimientoCaja) =>
        terceros.find((t) => t.id === m.tercero_id)?.etiqueta ?? '' },
    { accessorKey: 'medio_pago', header: 'Medio', size: 105 },
    { accessorKey: 'recibo', header: 'Recibo', size: 105 },
    { id: 'importe', header: sortableHeader('Importe'), size: 120,
      accessorFn: (m: MovimientoCaja) => formatearImporte(m.importe) },
    // Los anulados se ven, con su marca: un recibo que falta en la numeración
    // necesita explicación. Lo que no hacen es sumar en los totales.
    { id: 'estado', header: 'Estado', size: 90,
      cell: ({ row }: { row: { original: MovimientoCaja } }) => (
        row.original.anulado
          ? <BadgeEstado tono="negativo">anulado</BadgeEstado>
          : <BadgeEstado tono="ok">vigente</BadgeEstado>
      ) },
    { id: 'acciones', header: '', size: 80,
      cell: ({ row }: { row: { original: MovimientoCaja } }) => (
        <div className="flex gap-1">
          <Button variant="ghost" size="icon" aria-label="Editar"
                  disabled={row.original.anulado}
                  onClick={(e: React.MouseEvent) => { e.stopPropagation(); abrir(row.original) }}>
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon" aria-label="Anular"
                  disabled={row.original.anulado}
                  onClick={(e: React.MouseEvent) => { e.stopPropagation(); anular(row.original) }}>
            <Ban className="size-4" />
          </Button>
        </div>
      ) },
  ]

  return (
    <div>
      <div className="mb-4">
        {/* El listado se imprime desde reportes (`listado-caja`), que exige
            rango. Y de paso deja de estar el truco de `desplazamiento > 0 ? []`:
            aca la hoja pedia UNA tanda y lo que no entraba se perdia callado. */}
        <TituloPantalla
          icono={ICONOS_LC.caja}
          acciones={(
            <Button onClick={() => abrir(null)}>
              <Plus className="size-4" /> Nuevo movimiento
            </Button>
          )}
        >
          Caja
        </TituloPantalla>
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

      {/* Con el diálogo abierto el error va adentro: acá quedaba tapado por el diálogo. */}
      {error && !abierto && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {/* Un movimiento de caja lleva a la cuenta del tercero que movio. Sin
          rol: el movimiento guarda el tercero y la contrapartida sabe la
          cuenta, asi que la pantalla de destino elige el primer rol que ese
          tercero tenga. Un gasto general -- sin tercero -- no es clickeable. */}
      <DataTable
        columns={columnas}
        data={filas}
        onRowClick={(m) => { if (m.tercero_id) navegar(irA.cuentaDe(m.tercero_id)) }}
        emptyMessage={cargando ? 'Cargando…' : 'No hay movimientos en ese rango.'}
      />

      <Dialog open={abierto} onOpenChange={(a) => { if (!a) cerrar() }}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {editando ? `Editar movimiento ${editando.id}` : 'Nuevo movimiento de caja'}
            </DialogTitle>
          </DialogHeader>
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
            {/* 🔑 Cuenta primero (ADR-053, decisión del humano 2026-10-18). Antes el tercero —de cualquier rol— iba primero y la cuenta quedaba
                deshabilitada hasta tenerlo, así que el tercero no podía darse de alta ahí: el rol no se deduce (un ingreso puede ser de un
                cliente o la devolución de un proveedor). Con la cuenta elegida, el tercero se busca entre los de ese rol y se da de alta en él. */}
            <Opcion id="m-rol" etiqueta="Cuenta del tercero" valor={borrador.rol}
                    alCambiar={(v) => elegirCuenta(v as '' | Rol)}>
              <option value="">Ninguna (gasto general)</option>
              <option value="cliente">Cliente</option>
              <option value="fletero">Fletero</option>
              <option value="proveedor">Proveedor</option>
            </Opcion>
            {/* Sin cuenta, deshabilitado: es un gasto general. Si viene un tercero (al editar uno de varios roles) se lo muestra igual, para
                que se vea de quién es mientras se elige la cuenta. */}
            {/* `key`: el kit guarda los recién creados para mostrarlos hasta que estén en la lista del producto; sin remontar al cambiar de
                cuenta, un fletero recién creado aparecía entre los clientes. */}
            <SelectCliente
              key={borrador.rol || 'ninguna'}
              id="m-tercero" etiqueta="Tercero" value={borrador.tercero_id}
              opciones={borrador.rol
                ? opcionesCliente(delRol(borrador.rol))
                : opcionesCliente(borrador.tercero_id ? terceros : [], 'Ninguno (gasto general)')}
              onChange={(v) => set({ tercero_id: v })}
              disabled={!borrador.rol}
              entidad={borrador.rol || 'tercero'}
              crear={async (d) => {
                const rol = borrador.rol as Rol
                const t = await alta.crear(d)
                setOpciones((o) => (o ? conTerceroNuevo(o, t, rol) : o))
                return aOpcionDeSelect(t)
              }}
              {...ALTA_DE_CLIENTE} onPanelChange={setAltaAbierta} className={altaAbierta ? 'md:col-span-2' : undefined}
              placeholder={borrador.rol ? 'Elegir…' : 'Ninguno (gasto general)'}
              emptyMessage="No hay ninguno con ese nombre." ariaLabel="Tercero" />
            {alta.dialogo}
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
          {error && (
            <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={cerrar}>Cancelar</Button>
            <Button onClick={guardar}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
