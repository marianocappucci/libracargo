/** La pantalla de un maestro: tabla, buscador, alta, edición y baja.
 *
 * Una sola para los seis, por el mismo motivo que el backend tiene un solo
 * constructor: hacen lo mismo. Lo que cambia —qué columnas se ven y qué campos
 * se editan— entra por parámetro.
 *
 * > 🔑 **Formularios con estado propio, no React Hook Form + Zod.** El stack
 * > estándar de la familia los incluye y acá se deja afuera a propósito: son
 * > seis formularios planos de 3 a 8 campos, sin reglas cruzadas ni pasos, y la
 * > validación que importa —unicidad, roles— sólo la puede hacer el backend,
 * > que ya contesta 409 y 422 y se muestran tal cual. **El disparador para
 * > traerlos es el formulario de órdenes de F3**, que sí tiene reglas entre
 * > campos.
 */
import type { ColumnDef } from 'libra-ui/data-table'
import { ApiError } from 'libra-ui/api-client'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import type { ReactNode } from 'react'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Maestro, Recurso } from '@/api/maestros'
import { clienteDe } from '@/api/maestros'
import { enmascararCuit } from '@/api/cartas-porte'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { AccionesDelTitulo } from '@/components/AccionesDelTitulo'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { SelectLocalidad, SelectProvincia } from '@/components/CamposGeo'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export type Campo = {
  nombre: string
  etiqueta: string
  // `provincia` y `localidad` guardan **texto**, no un id: son los mismos
  // campos de siempre con un desplegable adelante. Ver `CamposGeo`.
  tipo?: 'texto' | 'numero' | 'booleano' | 'opciones' | 'provincia' | 'localidad' | 'cuit'
  opciones?: { valor: string; etiqueta: string }[]
  /** Sólo para `localidad`: de qué campo del formulario sale la provincia con
   *  la que se filtra el catálogo. */
  provinciaEn?: string
  /** Sólo para `opciones`: el valor es un número (un id) y no un texto; la opción de valor `''` es `null`. */
  numerico?: boolean
  /** Los campos seguidos con el mismo `grupo` se dibujan juntos, dentro de un recuadro con este título (los tres
   *  roles de una entidad: una misma persona o empresa puede tener más de uno). */
  grupo?: string
}

/** Lo que recibe quien quiere dibujar el error de guardado a su manera (el CUIT repetido de Entidades). */
export type ContextoDeConflicto<T extends Maestro> = {
  /** Qué se estaba editando, o `null` si era un alta. */
  editando: T | null
  /** Cierra el formulario. */
  cerrar: () => void
  /** Vuelve a pedir el listado. */
  recargar: () => void
  /** Marca una fila en la tabla, para que se vea dónde quedó lo que se acaba de hacer. */
  destacar: (id: number) => void
}

/** Lo que recibe quien agrega algo propio a la lista (botones por fila, una barra de altas y filtros). */
export type ContextoDeLista<T extends Maestro> = {
  /** Todas las filas cargadas, también las que un filtro esconde. */
  filas: T[]
  /** Vuelve a pedir el listado. */
  recargar: () => void
  /** Marca una fila en la tabla, para que se vea dónde quedó lo que se acaba de hacer. */
  destacar: (id: number) => void
  /** Muestra (o, con `null`, saca) un aviso de error arriba de la tabla, el mismo que usan las bajas y reactivaciones. */
  fallar: (mensaje: string | null) => void
}

type Props<T extends Maestro> = {
  recurso: Recurso
  titulo: string
  /** Columnas propias del maestro. La de estado y la de acciones las agrega
   *  esta pantalla, para que las seis se vean igual. */
  columnas: ColumnDef<T, unknown>[]
  campos: Campo[]
  /** Sobre qué texto busca el buscador de la tabla. */
  buscarEn: (fila: T) => (string | number | null | undefined)[]
  /** Valores iniciales de un alta. */
  defaults?: Partial<T>
  /** `false` esconde el título: la pantalla que contiene al maestro (Entidades) ya tiene el suyo. Queda el botón «Nuevo». */
  encabezado?: boolean
  /** El nombre de una fila en singular, para el título del formulario («Editar fletero»). Sin él, el de la tabla. */
  singular?: string
  /** Cómo se pide el listado. Sin esto es `GET /api/<recurso>`. */
  cargar?: () => Promise<T[]>
  /** Abre el formulario de esta fila en cuanto llega el listado (`?ver=` en la URL). */
  abrirId?: number | null
  /** Se llama al cerrar el formulario, para que quien lo abrió por la URL la limpie. */
  alCerrarFicha?: () => void
  /** Se llama al abrirse el formulario de una fila existente, con ella: se dibuja bajo los campos (la ficha del fletero). */
  fichaExtra?: (fila: T) => ReactNode
  /** Si devuelve algo para ese error de guardado, se dibuja en vez del texto pelado. */
  conflicto?: (error: unknown, ctx: ContextoDeConflicto<T>) => ReactNode
  /** Botones propios de cada fila, antes del lápiz (Localidades: vincular, marcar como paraje, unificar). */
  accionesDeFila?: (fila: T, ctx: ContextoDeLista<T>) => ReactNode
  /** Lo que va arriba, junto al botón «Nuevo»: altas alternativas y filtros rápidos. */
  barra?: (ctx: ContextoDeLista<T>) => ReactNode
  /** Esconde «Nuevo»: la pantalla trae sus propias altas en la `barra`. */
  sinNuevo?: boolean
  /** Un filtro rápido: sólo se ven las filas para las que da `true`. Las otras siguen cargadas. */
  visibles?: (fila: T) => boolean
}

export function mensajeDeError(e: unknown): string {
  if (e instanceof ApiError) {
    // `detail` de FastAPI: un string en los 404/409 que arma el producto, y una
    // lista de errores en los 422 de Pydantic. Las dos formas se muestran.
    const d = (e as unknown as { detail?: unknown }).detail
    if (typeof d === 'string') return d
    // Un `detail` objeto (el 409 del CUIT repetido) trae su texto en `mensaje`. `libra-ui` ya lo aplana a eso;
    // esto cubre el error que llega con el objeto entero.
    if (d && typeof d === 'object' && !Array.isArray(d)
        && typeof (d as { mensaje?: unknown }).mensaje === 'string') {
      return (d as { mensaje: string }).mensaje
    }
    if (Array.isArray(d)) {
      return d.map((x) => (x as { msg?: string })?.msg ?? String(x)).join(' · ')
    }
  }
  return e instanceof Error ? e.message : 'No se pudo completar la operación.'
}

function CampoForm({ campo, valor, borrador, alCambiar }: {
  campo: Campo
  valor: unknown
  /** El formulario entero: la localidad necesita leer la provincia elegida. */
  borrador: Record<string, unknown>
  alCambiar: (v: unknown) => void
}) {
  const id = `campo-${campo.nombre}`
  if (campo.tipo === 'provincia') {
    return (
      <SelectProvincia id={id} etiqueta={campo.etiqueta}
                       valor={valor === null || valor === undefined ? '' : String(valor)}
                       // Sólo las localidades llevan `pais` (ADR-042); en los demás maestros es Argentina.
                       pais={typeof borrador.pais === 'string' ? borrador.pais : undefined}
                       alCambiar={alCambiar} />
    )
  }
  if (campo.tipo === 'localidad') {
    const provincia = borrador[campo.provinciaEn ?? 'provincia']
    return (
      <SelectLocalidad id={id} etiqueta={campo.etiqueta}
                       valor={valor === null || valor === undefined ? '' : String(valor)}
                       provincia={provincia ? String(provincia) : ''}
                       alCambiar={alCambiar} />
    )
  }
  if (campo.tipo === 'booleano') {
    return (
      <div className="flex items-center gap-2">
        <input id={id} type="checkbox" checked={Boolean(valor)}
               onChange={(e) => alCambiar(e.target.checked)} />
        <Label htmlFor={id}>{campo.etiqueta}</Label>
      </div>
    )
  }
  if (campo.tipo === 'opciones') {
    // Se busca escribiendo (ADR-039 del kit): estas opciones pueden venir de datos —el fletero de un chofer o de un vehículo
    // son los 186 de la instancia— y no sólo de una constante (la condición de IVA). Es el selector del kit y no el de Radix, así
    // que dentro del diálogo no pelea por el foco. Sin ×: donde se puede vaciar hay una opción vacía («Sin fletero»), y vaciar una
    // condición de IVA no era posible con el `<select>` de antes y no pasa a serlo.
    const lista = campo.opciones ?? []
    return (
      <div className="grid gap-1">
        <Label htmlFor={id}>{campo.etiqueta}</Label>
        <SelectBuscable
          id={id} ariaLabel={campo.etiqueta} placeholder="Elegí una opción…"
          emptyMessage="No hay ninguna con ese nombre."
          value={String(valor ?? '')} limpiable={false}
          onChange={(v) => alCambiar(campo.numerico ? (v === '' ? null : Number(v)) : v)}
          opciones={lista.map((o) => ({ value: o.valor, label: o.etiqueta }))}
        />
      </div>
    )
  }
  if (campo.tipo === 'cuit') {
    // Se ve con guiones (`20-12345678-6`) y así viaja: el servidor acepta con o sin y lo guarda en once dígitos.
    // Vacío es `null`: «sin CUIT» no es un CUIT de cero dígitos. El verificador lo controla sólo el backend.
    return (
      <div className="grid gap-1">
        <Label htmlFor={id}>{campo.etiqueta}</Label>
        <Input id={id} inputMode="numeric" placeholder="20-12345678-6" autoComplete="off"
               value={enmascararCuit(valor === null || valor === undefined ? '' : String(valor))}
               onChange={(e) => alCambiar(enmascararCuit(e.target.value) || null)} />
      </div>
    )
  }
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{campo.etiqueta}</Label>
      <Input
        id={id}
        type={campo.tipo === 'numero' ? 'number' : 'text'}
        value={valor === null || valor === undefined ? '' : String(valor)}
        onChange={(e) => alCambiar(
          campo.tipo === 'numero'
            ? (e.target.value === '' ? null : Number(e.target.value))
            : e.target.value,
        )}
      />
    </div>
  )
}

/** Los campos en el orden del formulario, con los de un mismo `grupo` seguidos juntos en un solo bloque. */
function agrupar(campos: Campo[]): { grupo?: string; campos: Campo[] }[] {
  const bloques: { grupo?: string; campos: Campo[] }[] = []
  for (const c of campos) {
    const ultimo = bloques[bloques.length - 1]
    if (c.grupo && ultimo?.grupo === c.grupo) ultimo.campos.push(c)
    else bloques.push({ grupo: c.grupo, campos: [c] })
  }
  return bloques
}

export function AbmMaestro<T extends Maestro>({
  recurso, titulo, columnas, campos, buscarEn, defaults = {},
  encabezado = true, singular, cargar, abrirId = null, alCerrarFicha,
  fichaExtra, conflicto, accionesDeFila, barra, sinNuevo = false, visibles,
}: Props<T>) {
  const [filas, setFilas] = useState<T[]>([])
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<T | null>(null)
  const [borrador, setBorrador] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)
  // El error tal cual llegó, para que `conflicto` pueda leer lo que trae adentro (el texto ya está en `error`).
  const [errorCrudo, setErrorCrudo] = useState<unknown>(null)
  const [destacada, setDestacada] = useState<number | null>(null)
  // `cargar` es casi siempre una función nueva en cada render del padre: va por ref para no pedir el listado de nuevo.
  const cargarRef = useRef(cargar)
  cargarRef.current = cargar
  const yaAbierta = useRef<number | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    const pedido = cargarRef.current ? cargarRef.current() : clienteDe<T>(recurso).listar()
    pedido
      .then(setFilas)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [recurso])

  useEffect(recargar, [recargar])

  // La fila marcada se apaga sola: es para ver dónde quedó, no un estado.
  useEffect(() => {
    if (destacada === null) return
    const t = setTimeout(() => setDestacada(null), 6000)
    return () => clearTimeout(t)
  }, [destacada])

  function abrir(fila: T | null) {
    setEditando(fila)
    setBorrador(fila ? { ...fila } : { activo: true, ...defaults })
    setError(null)
    setErrorCrudo(null)
    setAbierto(true)
  }

  // `?ver=` de la URL: abre la ficha de esa fila una sola vez por id, cuando el listado ya la trae.
  useEffect(() => {
    if (abrirId === null) { yaAbierta.current = null; return }
    if (yaAbierta.current === abrirId) return
    const fila = filas.find((f) => f.id === abrirId)
    if (!fila) return
    yaAbierta.current = abrirId
    abrir(fila)
  }, [abrirId, filas])

  function alCambiarApertura(valor: boolean) {
    setAbierto(valor)
    if (!valor) alCerrarFicha?.()
  }

  async function guardar() {
    setError(null)
    setErrorCrudo(null)
    const cliente = clienteDe<T>(recurso)
    try {
      if (editando) await cliente.editar(editando.id, borrador as Partial<T>)
      else await cliente.crear(borrador as Partial<T>)
      alCambiarApertura(false)
      recargar()
    } catch (e) {
      // El backend distingue 409 (choca con una restricción) de 422 (el cuerpo
      // no vale). Se muestra su mensaje tal cual: reescribirlo acá haría que la
      // pantalla diga algo distinto de lo que decidió la base.
      setError(mensajeDeError(e))
      setErrorCrudo(e)
    }
  }

  async function cambiarEstado(fila: T) {
    setError(null)
    const cliente = clienteDe<T>(recurso)
    try {
      if (fila.activo) await cliente.darDeBaja(fila.id)
      else await cliente.editar(fila.id, { ...fila, activo: true } as Partial<T>)
      recargar()
    } catch (e) {
      setError(mensajeDeError(e))
    }
  }

  const contexto: ContextoDeLista<T> = { filas, recargar, destacar: setDestacada, fallar: setError }

  const columnasCompletas = [
    ...columnas,
    {
      id: 'estado',
      header: sortableHeader('Estado'),
      accessorFn: (f: T) => (f.activo ? 'Activo' : 'Baja'),
      cell: ({ row }: { row: { original: T } }) => (
        <BadgeEstado tono={row.original.activo ? 'ok' : 'negativo'}>
          {row.original.activo ? 'Activo' : 'Baja'}
        </BadgeEstado>
      ),
    },
    {
      id: 'acciones',
      header: '',
      cell: ({ row }: { row: { original: T } }) => (
        <div className="flex justify-end gap-1">
          {accionesDeFila?.(row.original, contexto)}
          <Button variant="ghost" size="icon" aria-label="Editar"
                  onClick={() => abrir(row.original)}>
            <Pencil className="size-4" />
          </Button>
          <Button variant="ghost" size="icon"
                  aria-label={row.original.activo ? 'Dar de baja' : 'Reactivar'}
                  onClick={() => cambiarEstado(row.original)}>
            {row.original.activo
              ? <Trash2 className="size-4" />
              : <RotateCcw className="size-4" />}
          </Button>
        </div>
      ),
    },
  ] as ColumnDef<T, unknown>[]

  const acciones = (
    <>
      {barra?.(contexto)}
      {!sinNuevo && (
        <Button onClick={() => abrir(null)}>
          <Plus className="size-4" /> Nuevo
        </Button>
      )}
    </>
  )

  return (
    // Con título propio es una pantalla; sin él va metido en otra (una pestaña de Entidades). Ninguna de las dos pone relleno
    // propio: el `Layout` ya separa el contenido del borde y baja el título a la altura de la marca (ADR-040 del kit).
    <div>
      {encabezado ? (
        <div className="mb-4 flex items-center justify-between">
          <h1 className="text-2xl font-semibold">{titulo}</h1>
          <div className="flex flex-wrap items-center justify-end gap-2">{acciones}</div>
        </div>
      ) : (
        // Metido en otra pantalla (Entidades): los botones suben a la línea del título de ésta.
        <AccionesDelTitulo>{acciones}</AccionesDelTitulo>
      )}

      {/* Con el formulario abierto el error se lee adentro: el de la página queda detrás del modal y el 422 del
          servidor («el CUIT del chofer no es válido…») no lo vería nadie. */}
      {error && !abierto && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {/* Click en la fila abre el formulario de edicion, que es lo unico que
          se puede hacer con la fila de un maestro. El lapiz de la columna de
          acciones queda: es el que se descubre mirando, y no todo el mundo
          prueba clickear una fila. */}
      <DataTable
        columns={columnasCompletas}
        data={visibles ? filas.filter(visibles) : filas}
        onRowClick={abrir}
        getRowClassName={(f) => (f.id === destacada ? 'bg-primary/10' : undefined)}
        emptyMessage={cargando ? 'Cargando…'
          : visibles && filas.length > 0 ? 'Ninguna coincide con el filtro.' : 'Todavía no hay nada cargado.'}
        search={{ campos: buscarEn, placeholder: `Buscar en ${titulo.toLowerCase()}…` }}
      />

      <Dialog open={abierto} onOpenChange={alCambiarApertura}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {singular
                ? (editando ? `Editar ${singular}` : `Nuevo ${singular}`)
                : (editando ? `Editar ${titulo}` : `Nuevo en ${titulo}`)}
            </DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            {agrupar(campos).map((bloque) => {
              const campoDe = (c: Campo) => (
                <CampoForm key={c.nombre} campo={c} valor={borrador[c.nombre]}
                           borrador={borrador as Record<string, unknown>}
                           alCambiar={(v) => setBorrador((b) => ({ ...b, [c.nombre]: v }))} />
              )
              if (!bloque.grupo) return campoDe(bloque.campos[0])
              return (
                <fieldset key={bloque.grupo} className="grid gap-2 rounded-md border p-3">
                  <legend className="px-1 text-sm font-medium">{bloque.grupo}</legend>
                  {bloque.campos.map(campoDe)}
                </fieldset>
              )
            })}
          </div>
          {editando && fichaExtra?.(editando)}
          {error && (
            conflicto?.(errorCrudo, {
              editando, recargar,
              cerrar: () => alCambiarApertura(false),
              destacar: setDestacada,
            }) ?? <p role="alert" className="rounded border border-destructive/40 p-3 text-sm">{error}</p>
          )}
          <DialogFooter>
            <Button variant="ghost" onClick={() => alCambiarApertura(false)}>Cancelar</Button>
            <Button onClick={guardar}>Guardar</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
