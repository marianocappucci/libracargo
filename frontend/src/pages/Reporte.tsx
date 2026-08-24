/** Un reporte, con los parámetros que él acepta.
 *
 * La barra de filtros se dibuja a partir de `parametros` del catálogo, así que
 * **es el backend el que decide qué se puede filtrar**. Las columnas sí viven
 * acá: son presentación, no dominio.
 *
 * 🔑 **Acá también se imprimen los listados.** Hasta el 2026-08-22 cada pantalla
 * —órdenes, comprobantes, comprobantes de proveedores, caja, el log— tenía su
 * propio botón "Imprimir" arriba a la derecha, y ninguno obligaba a poner
 * fechas: se apretaba con la pantalla recién abierta y salían las 4.337 órdenes
 * en noventa hojas. Los listados se mudaron a reportes (`detalle: true` en el
 * catálogo) y acá **el rango es obligatorio**: sin desde y hasta el reporte no
 * corre y no hay botón que apretar.
 */
import { DataTable } from 'libra-ui/data-table'
import { ArrowLeft, BarChart3 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Parametro, Reporte as EntradaDeCatalogo, ValoresDeFiltro } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import type { Registro } from '@/api/auditoria'
import { auditoria, describirCambio } from '@/api/auditoria'
import type { Comprobante } from '@/api/comprobantes'
import { NOMBRE_DE_TIPO, numeroDe, sumarImportes } from '@/api/comprobantes'
import type { Opcion, Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir as ElegirCompartido } from '@/components/Elegir'
import { formatearImporte } from '@/components/esquema-orden'
import { destinoDeFilaDeReporte } from '@/navegacion'
import type { Columna, Total } from '@/components/impresion'
import { BotonImprimir, traerTodo } from '@/components/impresion'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { formatearFecha, formatearFechaHoraDeTexto } from '@/components/esquema-orden'

type Fila = Record<string, string | number | null>

/** Cuántas filas de un listado se dibujan en pantalla.
 *
 * 🔑 **La hoja trae todas; la grilla, las primeras.** Un listado de un año son
 * miles de filas y dibujarlas todas cuelga la pantalla para nada: nadie
 * scrollea 3.000 líneas, para eso está el papel. Lo que no se hace es callarlo
 * — abajo de la tabla dice cuántas hay y cuántas se están viendo. */
const EN_PANTALLA = 200

/** El tope de filas por pedido de cada listado, que es el de SU endpoint.
 *
 * 🔴 No es cosmético: `traerTodo` corta cuando una tanda viene más corta que lo
 * que pidió. Pedirle 1.000 a un endpoint que devuelve como mucho 500 hace que la
 * primera tanda parezca la última, y la hoja sale con 500 filas y sin aviso. */
const POR_PEDIDO: Record<string, number> = { 'listado-logs': 500 }

function nombre(lista: Opcion[] | undefined, id: string | number | null): string {
  return lista?.find((o) => o.id === id)?.etiqueta ?? ''
}

/** Las columnas de cada reporte. Es lo único que la pantalla sabe de más que el
 *  catálogo: qué mostrar y qué va alineado a la derecha.
 *
 *  Es una función y no una constante porque los listados traen **ids** —los
 *  mismos que devuelve el listado de la pantalla, sin una consulta nueva— y el
 *  nombre sale de las opciones que ya están cargadas. */
function columnasDe(slug: string, o: Opciones | null): Columna<Fila>[] {
  const COLUMNAS: Record<string, Columna<Fila>[]> = {
    'por-cliente': [
      { encabezado: 'Cliente', valor: (f) => f.tercero },
      { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
      { encabezado: 'Facturado', valor: (f) => f.facturado, numerica: true, moneda: true },
      { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true, moneda: true },
      { encabezado: 'Saldo hoy', valor: (f) => f.saldo, numerica: true, moneda: true },
    ],
    'por-fletero': [
      { encabezado: 'Fletero', valor: (f) => f.tercero },
      { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
      { encabezado: 'Facturado', valor: (f) => f.facturado, numerica: true, moneda: true },
      { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true, moneda: true },
      { encabezado: 'Saldo hoy', valor: (f) => f.saldo, numerica: true, moneda: true },
    ],
    'pendientes-de-facturar': [
      { encabezado: 'Cliente', valor: (f) => f.cliente },
      { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
      { encabezado: 'La más vieja', valor: (f) => f.desde },
      { encabezado: 'La más nueva', valor: (f) => f.hasta },
      { encabezado: 'Total', valor: (f) => f.total, numerica: true, moneda: true },
    ],
    saldos: [
      { encabezado: 'Tercero', valor: (f) => f.tercero },
      { encabezado: 'Cuenta', valor: (f) => f.rol },
      { encabezado: 'Movimientos', valor: (f) => f.movimientos, numerica: true },
      { encabezado: 'Último', valor: (f) => f.ultimo_movimiento },
      { encabezado: 'Saldo', valor: (f) => f.saldo, numerica: true, moneda: true },
    ],
    caja: [
      { encabezado: 'Tipo', valor: (f) => f.tipo },
      { encabezado: 'Medio de pago', valor: (f) => f.medio_pago },
      { encabezado: 'Movimientos', valor: (f) => f.movimientos, numerica: true },
      { encabezado: 'Importe', valor: (f) => f.importe, numerica: true, moneda: true },
    ],
    'por-razon-social': [
      { encabezado: 'Razón social', valor: (f) => f.razon_social },
      { encabezado: 'Comprobantes', valor: (f) => f.comprobantes, numerica: true },
      { encabezado: 'Neto', valor: (f) => f.neto, numerica: true, moneda: true },
      { encabezado: 'IVA', valor: (f) => f.iva, numerica: true, moneda: true },
      { encabezado: 'Total', valor: (f) => f.total, numerica: true, moneda: true },
    ],
    'por-ruta': [
      { encabezado: 'Origen', valor: (f) => f.origen },
      { encabezado: 'Destino', valor: (f) => f.destino },
      { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
      { encabezado: 'Cantidad', valor: (f) => f.cantidad, numerica: true },
      { encabezado: 'Total', valor: (f) => f.total, numerica: true, moneda: true },
      { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true, moneda: true },
    ],

    // ── Los listados ──────────────────────────────────────────────────────
    // Las mismas columnas que imprimía cada pantalla antes de que el botón se
    // mudara acá. Los anulados salen, marcados: un número que falta en la
    // secuencia impresa no tiene explicación en el papel.
    'listado-ordenes': [
      { encabezado: 'Fecha', valor: (f) => formatearFecha(String(f.fecha ?? '')) },
      { encabezado: 'Cliente', valor: (f) => nombre(o?.clientes, f.cliente_id) },
      { encabezado: 'Origen', valor: (f) => nombre(o?.localidades, f.origen_id) },
      { encabezado: 'Destino', valor: (f) => nombre(o?.localidades, f.destino_id) },
      { encabezado: 'Fletero', valor: (f) => nombre(o?.fleteros, f.fletero_id) },
      { encabezado: 'Remito', valor: (f) => f.remito },
      { encabezado: 'Estado', valor: (f) => f.estado },
      { encabezado: 'Tarifa', valor: (f) => f.tarifa, numerica: true, moneda: true },
      { encabezado: 'Total', valor: (f) => f.total, numerica: true, moneda: true },
      { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true, moneda: true },
    ],
    'listado-comprobantes': [
      { encabezado: 'Fecha', valor: (f) => formatearFecha(String(f.fecha ?? '')) },
      { encabezado: 'Comprobante',
        valor: (f) => {
          const c = f as unknown as Comprobante
          return `${NOMBRE_DE_TIPO[c.tipo] ?? c.tipo} ${numeroDe(c)}`
        } },
      { encabezado: 'Razón social', valor: (f) => nombre(o?.razones, f.razon_social_id) },
      { encabezado: 'Cliente', valor: (f) => nombre(o?.clientes, f.cliente_id) },
      { encabezado: 'Estado', valor: (f) => (f.anulado ? 'anulado' : 'vigente') },
      { encabezado: 'Neto', valor: (f) => f.neto, numerica: true, moneda: true },
      { encabezado: 'IVA', valor: (f) => f.iva, numerica: true, moneda: true },
      { encabezado: 'Total', valor: (f) => f.total, numerica: true, moneda: true },
    ],
    'listado-gastos': [
      { encabezado: 'Fecha', valor: (f) => formatearFecha(String(f.fecha ?? '')) },
      { encabezado: 'Proveedor', valor: (f) => nombre(o?.proveedores, f.proveedor_id) },
      { encabezado: 'Fletero', valor: (f) => nombre(o?.fleteros, f.fletero_id) },
      { encabezado: 'Comprobante', valor: (f) => f.comprobante },
      { encabezado: 'Detalle', valor: (f) => f.descripcion },
      { encabezado: 'Importe', valor: (f) => f.importe, numerica: true, moneda: true },
      { encabezado: 'Estado', valor: (f) => (f.anulado ? 'anulado' : 'vigente') },
    ],
    'listado-caja': [
      { encabezado: 'Fecha', valor: (f) => formatearFecha(String(f.fecha ?? '')) },
      { encabezado: 'Tipo', valor: (f) => f.tipo },
      { encabezado: 'Concepto', valor: (f) => f.concepto },
      // Todos los terceros y no clientes + fleteros: un pago a proveedor salía
      // con el nombre en blanco porque la búsqueda por id no lo encontraba.
      { encabezado: 'Tercero', valor: (f) => nombre(o?.terceros, f.tercero_id) },
      { encabezado: 'Medio', valor: (f) => f.medio_pago },
      { encabezado: 'Recibo', valor: (f) => f.recibo },
      { encabezado: 'Importe', valor: (f) => f.importe, numerica: true, moneda: true },
      { encabezado: 'Estado', valor: (f) => (f.anulado ? 'anulado' : 'vigente') },
    ],
    'listado-logs': [
      { encabezado: 'Cuándo', valor: (f) => formatearFechaHoraDeTexto(String(f.ts ?? '')) },
      { encabezado: 'Usuario', valor: (f) => f.usuario_nombre ?? '' },
      { encabezado: 'Acción', valor: (f) => f.accion },
      { encabezado: 'Entidad', valor: (f) => f.entidad },
      { encabezado: 'Id', valor: (f) => f.entidad_id, numerica: true },
      // Los migrados del sistema viejo traen quién y cuándo pero no el detalle:
      // salen con esta columna vacía, y eso es un dato, no un error.
      { encabezado: 'Qué cambió', valor: (f) => describirCambio(f as unknown as Registro) },
    ],
  }
  return COLUMNAS[slug] ?? []
}

/** Los totales al pie de la hoja. Son los mismos que llevaba cada listado
 *  cuando se imprimía desde su pantalla: sacarlos al mudar el botón habría sido
 *  perder el número por el que se imprime el papel. */
function totalesDe(slug: string): ((filas: Fila[]) => Total[]) | undefined {
  const importes = (filas: Fila[], campo: string) =>
    sumarImportes(filas.map((f) => String(f[campo] ?? '0')))
  const TOTALES: Record<string, (filas: Fila[]) => Total[]> = {
    'listado-ordenes': (filas) => [
      { etiqueta: 'Órdenes', valor: String(filas.length) },
      { etiqueta: 'Total', valor: importes(filas, 'total') },
      { etiqueta: 'Comisión', valor: importes(filas, 'comision') },
    ],
    'listado-comprobantes': (filas) => [
      { etiqueta: 'Comprobantes', valor: String(filas.length) },
      { etiqueta: 'Total', valor: importes(filas, 'total') },
    ],
    'listado-gastos': (filas) => [
      { etiqueta: 'Comprobantes', valor: String(filas.length) },
      { etiqueta: 'Importe', valor: importes(filas, 'importe') },
    ],
    'listado-caja': (filas) => [
      { etiqueta: 'Ingresos',
        valor: importes(filas.filter((f) => f.tipo === 'ingreso'), 'importe') },
      { etiqueta: 'Egresos',
        valor: importes(filas.filter((f) => f.tipo === 'egreso'), 'importe') },
    ],
  }
  return TOTALES[slug]
}

/** El resumen no es una tabla: es una lista de conceptos. Se arma igual para que
 *  se pueda imprimir con la misma hoja que los demás. */
//: Cuáles de los conceptos del resumen son plata. Los otros son cantidades:
//: "12 órdenes" no lleva signo pesos.
const CONCEPTOS_EN_PESOS = new Set([
  'tarifa', 'iva', 'total', 'comision', 'facturado', 'cobrado', 'pagado',
])

const CONCEPTOS_DEL_RESUMEN: [string, string][] = [
  ['Órdenes', 'ordenes'],
  ['Órdenes pendientes de facturar', 'ordenes_pendientes'],
  ['Órdenes anuladas', 'ordenes_anuladas'],
  ['Tarifa', 'tarifa'],
  ['IVA', 'iva'],
  ['Total de las órdenes', 'total'],
  ['Comisión', 'comision'],
  ['Comprobantes', 'comprobantes'],
  ['Facturado', 'facturado'],
  ['Movimientos de caja', 'movimientos_caja'],
  ['Cobrado', 'cobrado'],
  ['Pagado', 'pagado'],
]

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

// El mismo componente que el resto del producto: con buscador cuando la lista
// lo amerita, sin el cuando son tres valores fijos. La decision no se repite
// pantalla por pantalla.
const Elegir = ElegirCompartido

export default function Reporte() {
  const navegar = useNavigate()
  const { slug = '' } = useParams()
  // El catálogo entero y no sólo la entrada: `null` es "todavía no cargó", que
  // es distinto de "ese slug no existe". Sin la diferencia, un slug inventado y
  // uno que aún no llegó se ven igual y el reporte no corre nunca.
  const [catalogo, setCatalogo] = useState<EntradaDeCatalogo[] | null>(null)
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [valores, setValores] = useState<ValoresDeFiltro>({})
  const [filas, setFilas] = useState<Fila[]>([])
  const [truncado, setTruncado] = useState(false)
  const [resumen, setResumen] = useState<Record<string, string | number | null> | null>(null)
  const [delLog, setDelLog] = useState<{ entidades: string[]; usuarios: string[] }>(
    { entidades: [], usuarios: [] })
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  const entrada = catalogo?.find((r) => r.slug === slug) ?? null
  const detalle = entrada?.detalle ?? false
  const hayRango = Boolean(valores.desde) && Boolean(valores.hasta)
  const falta = detalle && !hayRango

  useEffect(() => {
    Promise.all([reportes.catalogo(), cargarOpciones()])
      .then(([c, o]) => { setCatalogo(c); setOpciones(o) })
      .catch((e) => setError(mensajeDeError(e)))
  }, [])

  // Las listas del log salen de su propio endpoint y sólo hacen falta para su
  // reporte. Se piden cuando el catálogo dice que ese filtro existe, no siempre.
  const pideEntidad = entrada?.parametros.includes('entidad') ?? false
  useEffect(() => {
    if (!pideEntidad) return
    Promise.all([auditoria.entidades(), auditoria.usuarios()])
      .then(([entidades, usuarios]) => setDelLog({ entidades, usuarios }))
      .catch((e) => setError(mensajeDeError(e)))
  }, [pideEntidad])

  const correr = useCallback(() => {
    if (!slug || catalogo === null) return
    // Sin rango el listado no se pide. La guarda de verdad está en el backend
    // —contesta 422— pero pedirlo igual para mostrar el error sería ruido: acá
    // se sabe que falta un filtro, no que algo salió mal.
    if (falta) { setFilas([]); setResumen(null); setTruncado(false); setCargando(false); return }
    setCargando(true)
    setError(null)
    if (detalle) {
      traerTodo<Fila>(
        (desplazamiento, limite) =>
          reportes.correr<Fila[]>(slug, { ...valores, desplazamiento, limite }),
        POR_PEDIDO[slug],
      )
        .then((hoja) => { setFilas(hoja.filas); setTruncado(hoja.truncado); setResumen(null) })
        .catch((e) => setError(mensajeDeError(e)))
        .finally(() => setCargando(false))
      return
    }
    reportes.correr<Fila[] | Record<string, string | number | null>>(slug, valores)
      .then((datos) => {
        setTruncado(false)
        if (Array.isArray(datos)) { setFilas(datos); setResumen(null) }
        else { setResumen(datos); setFilas([]) }
      })
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [slug, catalogo, detalle, falta, valores])

  useEffect(correr, [correr])

  const set = (c: ValoresDeFiltro) => setValores((v) => ({ ...v, ...c }))
  const tiene = (p: Parametro) => entrada?.parametros.includes(p) ?? false
  const texto = (clave: string) => String(valores[clave] ?? '')

  const columnas = columnasDe(slug, opciones)
  const filasDelResumen: Fila[] = resumen
    ? CONCEPTOS_DEL_RESUMEN.map(([etiqueta, clave]) => ({
        concepto: etiqueta,
        valor: CONCEPTOS_EN_PESOS.has(clave)
          ? formatearImporte(resumen[clave]) : (resumen[clave] ?? ''),
      }))
    : []

  // Qué se filtró, en texto, para el encabezado del papel.
  const descripcion = Object.entries(valores)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k}: ${v}`).join(' · ') || 'sin filtros'

  return (
    <div className="p-6">
      <Link to="/reportes"
            className="text-muted-foreground no-imprimir mb-2 inline-flex items-center gap-1 text-sm hover:underline">
        <ArrowLeft className="size-3" /> Todos los reportes
      </Link>

      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <TituloPantalla icono={BarChart3}>{entrada?.titulo ?? slug}</TituloPantalla>
          {entrada && (
            <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
              {entrada.descripcion}
            </p>
          )}
        </div>
        {/* Sin rango no hay hoja que imprimir: el botón no está, en vez de estar
            y fallar. Es la mitad del cambio — la otra es el 422 del backend. */}
        {!falta && (
          <BotonImprimir
            titulo={entrada?.titulo ?? slug}
            filtros={descripcion}
            columnas={resumen
              ? [{ encabezado: 'Concepto', valor: (f: Fila) => f.concepto },
                 { encabezado: 'Valor', valor: (f: Fila) => f.valor, numerica: true }]
              : columnas}
            traer={async () => ({ filas: resumen ? filasDelResumen : filas, truncado })}
            totales={resumen ? undefined : totalesDe(slug)}
          />
        )}
      </div>

      <div className="no-imprimir mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        {tiene('rango') && (
          <>
            <Campo id="f-desde" etiqueta="Desde">
              <Input id="f-desde" type="date" value={texto('desde')}
                     onChange={(e) => set({ desde: e.target.value })} />
            </Campo>
            <Campo id="f-hasta" etiqueta="Hasta">
              <Input id="f-hasta" type="date" value={texto('hasta')}
                     onChange={(e) => set({ hasta: e.target.value })} />
            </Campo>
          </>
        )}
        {tiene('cliente') && (
          <Elegir id="f-cliente" etiqueta="Cliente" vacio="Todos"
                  valor={texto('cliente_id')} opciones={opciones?.clientes ?? []}
                  alCambiar={(v) => set({ cliente_id: v })} />
        )}
        {tiene('fletero') && (
          <Elegir id="f-fletero" etiqueta="Fletero" vacio="Todos"
                  valor={texto('fletero_id')} opciones={opciones?.fleteros ?? []}
                  alCambiar={(v) => set({ fletero_id: v })} />
        )}
        {tiene('proveedor') && (
          <Elegir id="f-proveedor" etiqueta="Proveedor" vacio="Todos"
                  valor={texto('proveedor_id')} opciones={opciones?.proveedores ?? []}
                  alCambiar={(v) => set({ proveedor_id: v })} />
        )}
        {tiene('tercero') && (
          <Elegir id="f-tercero" etiqueta="Tercero" vacio="Todos"
                  valor={texto('tercero_id')}
                  opciones={opciones?.terceros ?? []}
                  alCambiar={(v) => set({ tercero_id: v })} />
        )}
        {tiene('razon_social') && (
          <Elegir id="f-razon" etiqueta="Razón social" vacio="Todas"
                  valor={texto('razon_social_id')} opciones={opciones?.razones ?? []}
                  alCambiar={(v) => set({ razon_social_id: v })} />
        )}
        {tiene('origen') && (
          <Elegir id="f-origen" etiqueta="Origen" vacio="Todos"
                  valor={texto('origen_id')} opciones={opciones?.localidades ?? []}
                  alCambiar={(v) => set({ origen_id: v })} />
        )}
        {tiene('destino') && (
          <Elegir id="f-destino" etiqueta="Destino" vacio="Todos"
                  valor={texto('destino_id')} opciones={opciones?.localidades ?? []}
                  alCambiar={(v) => set({ destino_id: v })} />
        )}
        {tiene('medio_pago') && (
          <Elegir id="f-medio" etiqueta="Medio de pago" vacio="Todos"
                  valor={texto('medio_pago')}
                  opciones={[{ id: 'efectivo', etiqueta: 'Efectivo' },
                             { id: 'transferencia', etiqueta: 'Transferencia' },
                             { id: 'cheque', etiqueta: 'Cheque' },
                             { id: 'otro', etiqueta: 'Otro' }]}
                  alCambiar={(v) => set({ medio_pago: v })} />
        )}
        {tiene('tipo_caja') && (
          <Elegir id="f-tipo" etiqueta="Tipo" vacio="Todos"
                  valor={texto('tipo')}
                  opciones={[{ id: 'ingreso', etiqueta: 'Ingresos' },
                             { id: 'egreso', etiqueta: 'Egresos' }]}
                  alCambiar={(v) => set({ tipo: v })} />
        )}
        {tiene('rol') && (
          <Elegir id="f-rol" etiqueta="Tipo de cuenta" vacio="Todas"
                  valor={texto('rol')}
                  opciones={[{ id: 'cliente', etiqueta: 'Clientes' },
                             { id: 'fletero', etiqueta: 'Fleteros' },
                             { id: 'proveedor', etiqueta: 'Proveedores' }]}
                  alCambiar={(v) => set({ rol: v })} />
        )}
        {tiene('entidad') && (
          <Elegir id="f-entidad" etiqueta="Entidad" vacio="Todas"
                  valor={texto('entidad')}
                  opciones={delLog.entidades.map((e) => ({ id: e, etiqueta: e }))}
                  alCambiar={(v) => set({ entidad: v })} />
        )}
        {tiene('usuario') && (
          <Elegir id="f-usuario" etiqueta="Usuario" vacio="Todos"
                  valor={texto('usuario')}
                  opciones={delLog.usuarios.map((u) => ({ id: u, etiqueta: u }))}
                  alCambiar={(v) => set({ usuario: v })} />
        )}
        {tiene('accion') && (
          <Elegir id="f-accion" etiqueta="Acción" vacio="Todas"
                  valor={texto('accion')}
                  opciones={[{ id: 'alta', etiqueta: 'Alta' },
                             { id: 'modificacion', etiqueta: 'Modificación' },
                             { id: 'baja', etiqueta: 'Baja' }]}
                  alCambiar={(v) => set({ accion: v })} />
        )}
        {tiene('incluir_en_cero') && (
          <Campo id="f-cero" etiqueta="Cuentas en cero">
            <label className="flex h-9 items-center gap-2 text-sm">
              <input id="f-cero" type="checkbox" checked={valores.incluir_en_cero === true}
                     onChange={(e) => set({ incluir_en_cero: e.target.checked || undefined })} />
              Mostrar las saldadas
            </label>
          </Campo>
        )}
        {tiene('limite') && (
          <Campo id="f-limite" etiqueta="Cuántas filas">
            <Input id="f-limite" type="number" min={1} value={texto('limite')}
                   placeholder="100"
                   onChange={(e) => set({ limite: e.target.value })} />
          </Campo>
        )}
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {falta ? (
        <p className="text-muted-foreground rounded border border-dashed p-8 text-center text-sm">
          Elegí un <strong>desde</strong> y un <strong>hasta</strong>. Un listado
          sin fechas es la tabla entera: son las noventa hojas que este reporte
          existe para no imprimir.
        </p>
      ) : resumen ? (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          {CONCEPTOS_DEL_RESUMEN.map(([etiqueta, clave]) => (
            <div key={clave} className="rounded border p-4">
              <p className="text-muted-foreground text-xs">{etiqueta}</p>
              <p className="text-xl font-semibold tabular-nums">
                {CONCEPTOS_EN_PESOS.has(clave)
                  ? formatearImporte(resumen[clave])
                  : (resumen[clave] ?? '—')}
              </p>
            </div>
          ))}
        </div>
      ) : (
        <>
          <DataTable
            columns={columnas.map((c) => ({
              id: c.encabezado, header: c.encabezado,
              accessorFn: (f: Fila) =>
                c.moneda ? formatearImporte(c.valor(f)) : (c.valor(f) ?? ''),
            }))}
            data={detalle ? filas.slice(0, EN_PANTALLA) : filas}
            onRowClick={(f: Fila) => {
              const destino = destinoDeFilaDeReporte(slug, f)
              if (destino) navegar(destino)
            }}
            emptyMessage={cargando ? 'Calculando…' : 'No hay datos con esos filtros.'}
          />
          {/* Lo que la grilla no dibuja se dice, no se esconde. Una tabla
              cortada en 200 sin una línea que lo aclare se lee como el listado
              completo — y ahí el papel y la pantalla dicen cosas distintas. */}
          {detalle && !cargando && filas.length > 0 && (
            <p className="text-muted-foreground no-imprimir mt-3 text-sm">
              {filas.length > EN_PANTALLA
                ? `Se ven las primeras ${EN_PANTALLA} de ${filas.length}. La hoja trae las ${filas.length}.`
                : `${filas.length} registro${filas.length === 1 ? '' : 's'}.`}
              {truncado && (
                <span className="text-destructive font-semibold">
                  {' '}⚠️ El listado corta en el tope: acotá el rango para traer el resto.
                </span>
              )}
            </p>
          )}
        </>
      )}
    </div>
  )
}
