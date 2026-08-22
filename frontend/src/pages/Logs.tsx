/** El log: quién hizo qué, y qué cambió.
 *
 * Sobre la instancia de Suitrans esta pantalla arranca con **15.884 registros
 * migrados** de la tabla `sucesos` del legado. Esos traen quién y cuándo pero
 * **no qué cambió**, porque el sistema viejo nunca lo guardó: se ven con el
 * detalle vacío, y eso es un dato, no un error.
 *
 * ## 2026-08-22 — la consola toma las directrices de la de Contalibra
 *
 * La familia tenía tres consolas de Logs distintas y ésta era la que más se
 * apartaba. Adopta lo mismo que adoptó `libra-ui/Logs`:
 *
 * 1. **La actividad se agrupa por día**, con un separador que dice la fecha
 *    una vez (`dd-mm-aaaa`), y la fila muestra sólo la hora.
 * 2. **La acción se filtra con las píldoras de color**, no con un `select`.
 * 3. **El paginador dice cuánto se está viendo** y navega con flechas.
 * 4. **El estado vacío es un icono y una frase centrados.**
 * 5. 🔑 **"Qué cambió" deja de ser una columna y pasa a ser el acordeón** —el
 *    desplegable que ya tenían LibraDesk y los otros cuatro—, con el antes y
 *    el después uno al lado del otro. Era la columna que obligaba a
 *    `whitespace-normal` y la que estiraba la tabla: un diff de seis campos no
 *    entra en una celda. Los registros migrados de Suitrans no tienen diff, y
 *    ésos simplemente no despliegan nada, igual que un alta.
 *
 * Lo que **no** se adopta son las dos pestañas de Contalibra: acá no hay log de
 * accesos que poner en la segunda. Una pestaña sola no es una pestaña.
 *
 * Y por eso ya no usa `DataTable`: la fila desplegable necesita emitir dos
 * `<tr>` por registro, que es justo lo que esa tabla no hace.
 *
 * 🔑 **Acá no se imprime.** El log en papel es un reporte (`listado-logs`), que
 * exige un rango. Este botón salía con la pantalla recién abierta y mandaba los
 * 15.884 registros migrados de una — y encima traía sólo los primeros 500, sin
 * decirlo. Ver ADR-023.
 */
import { Fragment, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronLeft, ChevronRight, Inbox, ScrollText } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import type { FiltrosDeLog, Registro } from '@/api/auditoria'
import { auditoria } from '@/api/auditoria'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { destinoDelLog } from '@/navegacion'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

const POR_PAGINA = 50

const TODAS = '__todas__'

/** Las tres acciones, con el mismo color que manda el backend de los otros
 *  cinco productos (`libraauth.auditoria.ACCION_META`). Acá el color no viene
 *  de la API —este backend no lo manda— pero la familia usa uno solo, así que
 *  se escribe con los mismos valores en vez de inventar una paleta propia. */
const ACCIONES: { id: string; label: string; color: string }[] = [
  { id: 'alta', label: 'Alta', color: '#198754' },
  { id: 'modificacion', label: 'Modificación', color: '#0d6efd' },
  { id: 'baja', label: 'Baja', color: '#dc3545' },
]

const FORMA_TS = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}:\d{2}:\d{2})/

/** `2026-08-05T14:32:10` → `["05-08-2026", "14:32:10"]`. Un `ts` con otra forma
 *  se devuelve entero como fecha y sin hora, en vez de recortarse a ciegas:
 *  un `slice` sobre un texto corto deja la celda en blanco, que se lee como un
 *  dato faltante y no como un formato que no se entendió. */
function partirTs(ts: string): { fecha: string; hora: string } {
  const m = FORMA_TS.exec(ts)
  if (!m) return { fecha: ts, hora: '—' }
  return { fecha: `${m[3]}-${m[2]}-${m[1]}`, hora: m[4] }
}

function valor(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—'
  if (typeof v === 'boolean') return v ? 'sí' : 'no'
  return String(v)
}

/** Las columnas que cambiaron, una por línea, con el antes tachado.
 *
 *  Se arma sobre la UNIÓN de las dos partes y no sobre `datos_despues`: en una
 *  baja hay campos que existen antes y no después, y mirar un solo lado los
 *  perdería. Es el mismo criterio que `describirCambio()` de `@/api/auditoria`,
 *  que sigue existiendo para la hoja impresa — que ahora la arma el reporte
 *  `listado-logs`, donde no hay dónde desplegar y el renglón de una línea es lo
 *  correcto. */
function Cambios({ registro }: { registro: Registro }) {
  const antes = registro.datos_antes ?? {}
  const despues = registro.datos_despues ?? {}
  const claves = [...new Set([...Object.keys(antes), ...Object.keys(despues)])].sort()
  return (
    <table className="w-full text-xs">
      <tbody>
        {claves.map((k) => (
          <tr key={k} className="border-b last:border-0">
            <td className="py-1 pr-3 font-medium text-muted-foreground">{k}</td>
            <td className="py-1 pr-2 text-muted-foreground line-through">
              {registro.accion === 'alta' ? '' : valor(antes[k])}
            </td>
            <td className="py-1 font-medium">
              {registro.accion === 'baja' ? '' : valor(despues[k])}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function Campo({ id, etiqueta, children }: {
  id?: string; etiqueta: string; children: ReactNode
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={id}>{etiqueta}</Label>
      {children}
    </div>
  )
}

function SinDatos({ children }: { children: ReactNode }) {
  return (
    <p className="flex flex-col items-center gap-2 py-10 text-center text-sm text-muted-foreground">
      <Inbox className="size-6" />{children}
    </p>
  )
}

export default function Logs() {
  const navegar = useNavigate()
  const [filtros, setFiltros] = useState<FiltrosDeLog>({})
  const [pagina, setPagina] = useState(0)
  const [datos, setDatos] = useState<{ total: number; registros: Registro[] }>(
    { total: 0, registros: [] })
  const [entidades, setEntidades] = useState<string[]>([])
  const [usuarios, setUsuarios] = useState<string[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)
  const [abierta, setAbierta] = useState<number | null>(null)

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
    // resultado. Y cierra el acordeón, que estaba abierto sobre una fila que
    // quizás ya no está.
    setPagina(0)
    setAbierta(null)
    setFiltros((f) => ({ ...f, ...c }))
  }

  function limpiarFiltros() {
    setPagina(0)
    setAbierta(null)
    setFiltros({})
  }

  // Un grupo por día, en el orden en que vienen las filas. El backend las manda
  // por `ts` descendente, así que basta con cortar cuando cambia la fecha:
  // agrupar con un `Map` reordenaría los días si alguna vez dejaran de venir
  // contiguos, que es peor que mostrar dos grupos con la misma fecha.
  const grupos = useMemo(() => {
    const out: { fecha: string; filas: Registro[] }[] = []
    for (const r of datos.registros) {
      const { fecha } = partirTs(r.ts)
      const ultimo = out[out.length - 1]
      if (ultimo && ultimo.fecha === fecha) ultimo.filas.push(r)
      else out.push({ fecha, filas: [r] })
    }
    return out
  }, [datos])

  const desde = pagina * POR_PAGINA
  const hasta = Math.min(desde + POR_PAGINA, datos.total)
  const paginas = Math.max(1, Math.ceil(datos.total / POR_PAGINA))
  const sinFiltros = Object.values(filtros).every((v) => v == null || v === '')

  return (
    <div className="p-6">
      {/* El titulo, y nada mas. El boton de imprimir se fue a reportes
          (`listado-logs`): desde aca imprimia los 15.884 registros de una,
          porque nada obligaba a poner fechas. */}
      <div className="mb-4">
        <TituloPantalla icono={ScrollText}>Log de actividad</TituloPantalla>
      </div>

      <Card className="no-imprimir mb-4">
        <CardContent className="grid gap-4">
          {/* Las píldoras de acción. La que no está elegida baja a 0.4 de
              opacidad; sin ninguna elegida están todas enteras, que es el
              estado "todas". */}
          <div className="grid gap-2">
            <Label>Acción</Label>
            <div className="flex flex-wrap gap-2">
              {ACCIONES.map(({ id, label, color }) => {
                const elegida = !filtros.accion || filtros.accion === id
                return (
                  <button
                    key={id}
                    type="button"
                    aria-pressed={filtros.accion === id}
                    onClick={() => set({ accion: filtros.accion === id ? undefined : id })}
                    className="rounded-full transition-opacity"
                    style={{ opacity: elegida ? 1 : 0.4 }}
                  >
                    <Badge style={{ backgroundColor: color }} className="cursor-pointer text-white hover:opacity-90">
                      {label}
                    </Badge>
                  </button>
                )
              })}
            </div>
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <Campo id="l-entidad" etiqueta="Entidad">
              <Select
                value={filtros.entidad ?? TODAS}
                onValueChange={(v) => set({ entidad: v === TODAS ? undefined : v })}
              >
                <SelectTrigger id="l-entidad" className="w-48"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={TODAS}>Todas</SelectItem>
                  {entidades.map((e) => (
                    <SelectItem key={e} value={e}>{e.replace(/_/g, ' ')}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Campo>
            <Campo id="l-usuario" etiqueta="Usuario">
              <Select
                value={filtros.usuario ?? TODAS}
                onValueChange={(v) => set({ usuario: v === TODAS ? undefined : v })}
              >
                <SelectTrigger id="l-usuario" className="w-48"><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value={TODAS}>Todos</SelectItem>
                  {usuarios.map((u) => <SelectItem key={u} value={u}>{u}</SelectItem>)}
                </SelectContent>
              </Select>
            </Campo>
            <Campo id="l-desde" etiqueta="Desde">
              <Input id="l-desde" type="date" className="w-40" value={filtros.desde ?? ''}
                     onChange={(e) => set({ desde: e.target.value || undefined })} />
            </Campo>
            <Campo id="l-hasta" etiqueta="Hasta">
              <Input id="l-hasta" type="date" className="w-40" value={filtros.hasta ?? ''}
                     onChange={(e) => set({ hasta: e.target.value || undefined })} />
            </Campo>
            <Button size="sm" variant="outline" onClick={limpiarFiltros}>Limpiar</Button>
          </div>
        </CardContent>
      </Card>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {/* Cuánto se está viendo y de cuánto, arriba de la tabla. Va siempre,
          aunque haya una sola página: ahí lo que informa es el total. */}
      <div className="no-imprimir mb-2 flex items-center justify-between px-1 text-sm text-muted-foreground">
        <span>
          {datos.total === 0
            ? 'Sin registros'
            : <>Mostrando <strong className="text-foreground">{desde + 1} a {hasta}</strong>
                {' '}de <strong className="text-foreground">{datos.total}</strong> registros</>}
        </span>
        <div className="flex items-center gap-2">
          {/* `aria-label` y no sólo el icono: un botón cuyo único contenido es
              un `svg` no tiene nombre accesible. */}
          <Button size="icon" variant="outline" className="size-7" aria-label="Anterior"
                  disabled={pagina === 0}
                  onClick={() => { setPagina((p) => p - 1); setAbierta(null) }}><ChevronLeft /></Button>
          <span>Pág {pagina + 1} / {paginas}</span>
          <Button size="icon" variant="outline" className="size-7" aria-label="Siguiente"
                  disabled={hasta >= datos.total}
                  onClick={() => { setPagina((p) => p + 1); setAbierta(null) }}><ChevronRight /></Button>
        </div>
      </div>

      <Card>
        <CardContent className="p-0">
          {datos.registros.length === 0 ? (
            <SinDatos>
              {cargando
                ? 'Cargando…'
                : sinFiltros
                  ? 'Todavía no hay actividad registrada.'
                  : 'No hay actividad con esos filtros.'}
            </SinDatos>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b text-muted-foreground">
                  <tr>
                    <th className="w-8 p-3" />
                    <th className="w-24 p-3 text-left font-medium">Hora</th>
                    <th className="w-36 p-3 text-left font-medium">Acción</th>
                    <th className="p-3 text-left font-medium">Qué</th>
                    <th className="w-40 p-3 text-left font-medium">Usuario</th>
                  </tr>
                </thead>
                <tbody>
                  {grupos.map((g) => (
                    <Fragment key={g.fecha}>
                      <tr className="bg-muted/50">
                        <td colSpan={5} className="px-3 py-1.5">
                          <span className="text-xs font-semibold text-muted-foreground">{g.fecha}</span>
                        </td>
                      </tr>
                      {g.filas.map((r) => {
                        const meta = ACCIONES.find((a) => a.id === r.accion)
                        const tieneCambios = Object.keys(r.datos_antes ?? {}).length > 0
                          || Object.keys(r.datos_despues ?? {}).length > 0
                        const desplegada = abierta === r.id
                        const destino = destinoDelLog(r.entidad, r.entidad_id)
                        return (
                          <Fragment key={r.id}>
                            <tr
                              className={`border-b last:border-0 ${tieneCambios ? 'cursor-pointer hover:bg-muted/30' : ''}`}
                              onClick={() => tieneCambios && setAbierta(desplegada ? null : r.id)}
                            >
                              <td className="p-3 text-muted-foreground">
                                {tieneCambios && (
                                  <ChevronDown
                                    className={`size-4 transition-transform ${desplegada ? '' : '-rotate-90'}`}
                                  />
                                )}
                              </td>
                              <td className="whitespace-nowrap p-3 font-mono text-xs text-muted-foreground" title={r.ts}>
                                {partirTs(r.ts).hora}
                              </td>
                              <td className="p-3">
                                <Badge style={meta ? { backgroundColor: meta.color } : undefined}
                                       className={meta ? 'text-white' : undefined}
                                       variant={meta ? undefined : 'outline'}>
                                  {meta?.label ?? r.accion}
                                </Badge>
                              </td>
                              <td className="p-3">
                                {/* El nombre de la entidad lleva a su pantalla, y el
                                    click en el resto de la fila despliega el diff: dos
                                    acciones distintas necesitan dos blancos distintos.
                                    Antes toda la fila navegaba, y con el acordeón
                                    encima eso sería un click que hace dos cosas. */}
                                {destino ? (
                                  <button
                                    type="button"
                                    className="underline-offset-2 hover:underline"
                                    onClick={(e) => { e.stopPropagation(); navegar(destino) }}
                                  >
                                    {r.entidad.replace(/_/g, ' ')}
                                  </button>
                                ) : r.entidad.replace(/_/g, ' ')}
                                {r.entidad_id !== null && (
                                  <span className="ml-1 text-xs text-muted-foreground">#{r.entidad_id}</span>
                                )}
                              </td>
                              <td className="whitespace-nowrap p-3">{r.usuario_nombre ?? '—'}</td>
                            </tr>
                            {desplegada && (
                              <tr className="border-b bg-muted/20 last:border-0">
                                <td />
                                <td colSpan={4} className="p-3"><Cambios registro={r} /></td>
                              </tr>
                            )}
                          </Fragment>
                        )
                      })}
                    </Fragment>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
