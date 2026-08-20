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
import type { ColumnDef } from '@tanstack/react-table'
import { ApiError } from 'libra-ui/api-client'
import { DataTable, sortableHeader } from 'libra-ui/data-table'
import { Pencil, Plus, RotateCcw, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import type { Maestro, Recurso } from '@/api/maestros'
import { clienteDe } from '@/api/maestros'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

export type Campo = {
  nombre: string
  etiqueta: string
  tipo?: 'texto' | 'numero' | 'booleano' | 'opciones'
  opciones?: { valor: string; etiqueta: string }[]
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
}

export function mensajeDeError(e: unknown): string {
  if (e instanceof ApiError) {
    // `detail` de FastAPI: un string en los 404/409 que arma el producto, y una
    // lista de errores en los 422 de Pydantic. Las dos formas se muestran.
    const d = (e as unknown as { detail?: unknown }).detail
    if (typeof d === 'string') return d
    if (Array.isArray(d)) {
      return d.map((x) => (x as { msg?: string })?.msg ?? String(x)).join(' · ')
    }
  }
  return e instanceof Error ? e.message : 'No se pudo completar la operación.'
}

function CampoForm({ campo, valor, alCambiar }: {
  campo: Campo
  valor: unknown
  alCambiar: (v: unknown) => void
}) {
  const id = `campo-${campo.nombre}`
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
    // `<select>` nativo y no el de Radix: son cinco opciones fijas dentro de un
    // diálogo, y el de Radix monta su propio portal, que ahí pelea por el foco.
    return (
      <div className="grid gap-1">
        <Label htmlFor={id}>{campo.etiqueta}</Label>
        <select id={id} className="h-9 rounded-md border px-3 text-sm"
                value={String(valor ?? '')} onChange={(e) => alCambiar(e.target.value)}>
          {campo.opciones?.map((o) => (
            <option key={o.valor} value={o.valor}>{o.etiqueta}</option>
          ))}
        </select>
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

export function AbmMaestro<T extends Maestro>({
  recurso, titulo, columnas, campos, buscarEn, defaults = {},
}: Props<T>) {
  const [filas, setFilas] = useState<T[]>([])
  const [cargando, setCargando] = useState(true)
  const [abierto, setAbierto] = useState(false)
  const [editando, setEditando] = useState<T | null>(null)
  const [borrador, setBorrador] = useState<Record<string, unknown>>({})
  const [error, setError] = useState<string | null>(null)

  const recargar = useCallback(() => {
    setCargando(true)
    clienteDe<T>(recurso).listar()
      .then(setFilas)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [recurso])

  useEffect(recargar, [recargar])

  function abrir(fila: T | null) {
    setEditando(fila)
    setBorrador(fila ? { ...fila } : { activo: true, ...defaults })
    setError(null)
    setAbierto(true)
  }

  async function guardar() {
    setError(null)
    const cliente = clienteDe<T>(recurso)
    try {
      if (editando) await cliente.editar(editando.id, borrador as Partial<T>)
      else await cliente.crear(borrador as Partial<T>)
      setAbierto(false)
      recargar()
    } catch (e) {
      // El backend distingue 409 (choca con una restricción) de 422 (el cuerpo
      // no vale). Se muestra su mensaje tal cual: reescribirlo acá haría que la
      // pantalla diga algo distinto de lo que decidió la base.
      setError(mensajeDeError(e))
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

  const columnasCompletas = [
    ...columnas,
    {
      id: 'estado',
      header: sortableHeader('Estado'),
      accessorFn: (f: T) => (f.activo ? 'Activo' : 'Baja'),
      cell: ({ row }: { row: { original: T } }) => (
        <Badge variant={row.original.activo ? 'secondary' : 'destructive'}>
          {row.original.activo ? 'Activo' : 'Baja'}
        </Badge>
      ),
    },
    {
      id: 'acciones',
      header: '',
      cell: ({ row }: { row: { original: T } }) => (
        <div className="flex justify-end gap-1">
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

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">{titulo}</h1>
        <Button onClick={() => abrir(null)}>
          <Plus className="size-4" /> Nuevo
        </Button>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={columnasCompletas}
        data={filas}
        emptyMessage={cargando ? 'Cargando…' : 'Todavía no hay nada cargado.'}
        search={{ campos: buscarEn, placeholder: `Buscar en ${titulo.toLowerCase()}…` }}
      />

      <Dialog open={abierto} onOpenChange={setAbierto}>
        <DialogContent className="max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editando ? `Editar ${titulo}` : `Nuevo en ${titulo}`}</DialogTitle>
          </DialogHeader>
          <div className="grid gap-3">
            {campos.map((c) => (
              <CampoForm key={c.nombre} campo={c} valor={borrador[c.nombre]}
                         alCambiar={(v) => setBorrador((b) => ({ ...b, [c.nombre]: v }))} />
            ))}
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
