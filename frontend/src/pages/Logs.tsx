/** El log: quién hizo qué, y qué cambió.
 *
 * Sobre la instancia de Suitrans esta pantalla arranca con **15.884 registros
 * migrados** de la tabla `sucesos` del legado. Esos traen quién y cuándo pero
 * **no qué cambió**, porque el sistema viejo nunca lo guardó: se ven con la
 * columna de cambios vacía, y eso es un dato, no un error.
 */
import { DataTable } from 'libra-ui/data-table'
import { useCallback, useEffect, useState } from 'react'

import type { FiltrosDeLog, Registro } from '@/api/auditoria'
import { auditoria, describirCambio } from '@/api/auditoria'
import { mensajeDeError } from '@/components/AbmMaestro'
import type { Columna } from '@/components/impresion'
import { BotonImprimir, traerTodo } from '@/components/impresion'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const POR_PAGINA = 50

const COLOR: Record<string, 'secondary' | 'destructive' | 'outline'> = {
  alta: 'secondary', modificacion: 'outline', baja: 'destructive',
}

function Campo({ id, etiqueta, children }: {
  id: string; etiqueta: string; children: React.ReactNode
}) {
  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      {children}
    </div>
  )
}

export default function Logs() {
  const [filtros, setFiltros] = useState<FiltrosDeLog>({})
  const [pagina, setPagina] = useState(0)
  const [datos, setDatos] = useState<{ total: number; registros: Registro[] }>(
    { total: 0, registros: [] })
  const [entidades, setEntidades] = useState<string[]>([])
  const [usuarios, setUsuarios] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    Promise.all([auditoria.entidades(), auditoria.usuarios()])
      .then(([e, u]) => { setEntidades(e); setUsuarios(u) })
      .catch((e) => setError(mensajeDeError(e)))
  }, [])

  const recargar = useCallback(() => {
    setCargando(true)
    auditoria.listar({ ...filtros, limite: POR_PAGINA, desplazamiento: pagina * POR_PAGINA })
      .then(setDatos)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [filtros, pagina])

  useEffect(recargar, [recargar])

  const set = (c: Partial<FiltrosDeLog>) => {
    // Cualquier cambio de filtro vuelve a la primera página: quedarse en la 7
    // de un listado que ahora tiene 3 muestra una tabla vacía que parece un
    // resultado.
    setPagina(0)
    setFiltros((f) => ({ ...f, ...c }))
  }

  const columnas: Columna<Registro>[] = [
    { encabezado: 'Cuándo', valor: (r) => r.ts.replace('T', ' ').slice(0, 16) },
    { encabezado: 'Usuario', valor: (r) => r.usuario_nombre ?? '' },
    { encabezado: 'Acción', valor: (r) => r.accion },
    { encabezado: 'Entidad', valor: (r) => r.entidad },
    { encabezado: 'Id', valor: (r) => r.entidad_id, numerica: true },
    { encabezado: 'Qué cambió', valor: (r) => describirCambio(r) },
  ]

  const desde = pagina * POR_PAGINA
  const hasta = Math.min(desde + POR_PAGINA, datos.total)

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Log de actividad</h1>
          <p className="text-muted-foreground text-sm">
            Quién hizo qué, y qué cambió. Los registros migrados del sistema viejo
            traen quién y cuándo, pero no el detalle: ese sistema no lo guardaba.
          </p>
        </div>
        <BotonImprimir
          titulo="Log de actividad"
          filtros={Object.entries(filtros).filter(([, v]) => v).map(([k, v]) => `${k}: ${v}`)
            .join(' · ') || 'sin filtros'}
          columnas={columnas}
          traer={() => traerTodo((desplazamiento, limite) =>
            auditoria.listar({ ...filtros, desplazamiento, limite: Math.min(limite, 500) })
              .then((p) => p.registros))}
        />
      </div>

      <div className="no-imprimir mb-4 grid grid-cols-2 gap-3 md:grid-cols-5">
        <Campo id="l-entidad" etiqueta="Entidad">
          <select id="l-entidad" className="h-9 rounded-md border px-2 text-sm"
                  value={filtros.entidad ?? ''}
                  onChange={(e) => set({ entidad: e.target.value || undefined })}>
            <option value="">Todas</option>
            {entidades.map((e) => <option key={e} value={e}>{e}</option>)}
          </select>
        </Campo>
        <Campo id="l-usuario" etiqueta="Usuario">
          <select id="l-usuario" className="h-9 rounded-md border px-2 text-sm"
                  value={filtros.usuario ?? ''}
                  onChange={(e) => set({ usuario: e.target.value || undefined })}>
            <option value="">Todos</option>
            {usuarios.map((u) => <option key={u} value={u}>{u}</option>)}
          </select>
        </Campo>
        <Campo id="l-accion" etiqueta="Acción">
          <select id="l-accion" className="h-9 rounded-md border px-2 text-sm"
                  value={filtros.accion ?? ''}
                  onChange={(e) => set({ accion: e.target.value || undefined })}>
            <option value="">Todas</option>
            <option value="alta">Alta</option>
            <option value="modificacion">Modificación</option>
            <option value="baja">Baja</option>
          </select>
        </Campo>
        <Campo id="l-desde" etiqueta="Desde">
          <Input id="l-desde" type="date" value={filtros.desde ?? ''}
                 onChange={(e) => set({ desde: e.target.value || undefined })} />
        </Campo>
        <Campo id="l-hasta" etiqueta="Hasta">
          <Input id="l-hasta" type="date" value={filtros.hasta ?? ''}
                 onChange={(e) => set({ hasta: e.target.value || undefined })} />
        </Campo>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <DataTable
        columns={[
          { id: 'ts', header: 'Cuándo',
            accessorFn: (r: Registro) => r.ts.replace('T', ' ').slice(0, 16) },
          { id: 'usuario', header: 'Usuario',
            accessorFn: (r: Registro) => r.usuario_nombre ?? '—' },
          { id: 'accion', header: 'Acción',
            accessorFn: (r: Registro) => r.accion,
            cell: ({ row }: { row: { original: Registro } }) => (
              <Badge variant={COLOR[row.original.accion] ?? 'outline'}>
                {row.original.accion}
              </Badge>
            ) },
          { id: 'entidad', header: 'Qué',
            accessorFn: (r: Registro) => `${r.entidad} #${r.entidad_id ?? '—'}` },
          { id: 'cambio', header: 'Qué cambió',
            accessorFn: (r: Registro) => describirCambio(r) || '—' },
        ]}
        data={datos.registros}
        emptyMessage={cargando ? 'Cargando…' : 'No hay actividad con esos filtros.'}
      />

      <div className="no-imprimir mt-4 flex items-center justify-between text-sm">
        <span className="text-muted-foreground">
          {datos.total === 0 ? 'Sin registros' : `${desde + 1} a ${hasta} de ${datos.total}`}
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={pagina === 0}
                  onClick={() => setPagina((p) => p - 1)}>Anterior</Button>
          <Button variant="outline" size="sm" disabled={hasta >= datos.total}
                  onClick={() => setPagina((p) => p + 1)}>Siguiente</Button>
        </div>
      </div>
    </div>
  )
}
