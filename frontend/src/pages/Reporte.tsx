/** Un reporte, con los parámetros que él acepta.
 *
 * La barra de filtros se dibuja a partir de `parametros` del catálogo, así que
 * **es el backend el que decide qué se puede filtrar**. Las columnas sí viven
 * acá: son presentación, no dominio.
 */
import { DataTable } from 'libra-ui/data-table'
import { ArrowLeft, BarChart3 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'

import type { Parametro, Reporte as EntradaDeCatalogo, ValoresDeFiltro } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir as ElegirCompartido } from '@/components/Elegir'
import { formatearImporte } from '@/components/esquema-orden'
import { destinoDeFilaDeReporte } from '@/navegacion'
import type { Columna } from '@/components/impresion'
import { BotonImprimir } from '@/components/impresion'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

type Fila = Record<string, string | number | null>

/** Las columnas de cada reporte. Es lo único que la pantalla sabe de más que el
 *  catálogo: qué mostrar y qué va alineado a la derecha. */
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
  const [entrada, setEntrada] = useState<EntradaDeCatalogo | null>(null)
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [valores, setValores] = useState<ValoresDeFiltro>({})
  const [filas, setFilas] = useState<Fila[]>([])
  const [resumen, setResumen] = useState<Record<string, string | number | null> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    Promise.all([reportes.catalogo(), cargarOpciones()])
      .then(([catalogo, o]) => {
        setEntrada(catalogo.find((r) => r.slug === slug) ?? null)
        setOpciones(o)
      })
      .catch((e) => setError(mensajeDeError(e)))
  }, [slug])

  const correr = useCallback(() => {
    if (!slug) return
    setCargando(true)
    setError(null)
    reportes.correr<Fila[] | Record<string, string | number | null>>(slug, valores)
      .then((datos) => {
        if (Array.isArray(datos)) { setFilas(datos); setResumen(null) }
        else { setResumen(datos); setFilas([]) }
      })
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [slug, valores])

  useEffect(correr, [correr])

  const set = (c: ValoresDeFiltro) => setValores((v) => ({ ...v, ...c }))
  const tiene = (p: Parametro) => entrada?.parametros.includes(p) ?? false
  const texto = (clave: string) => String(valores[clave] ?? '')

  const columnas = COLUMNAS[slug] ?? []
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
        <BotonImprimir
          titulo={entrada?.titulo ?? slug}
          filtros={descripcion}
          columnas={resumen
            ? [{ encabezado: 'Concepto', valor: (f: Fila) => f.concepto },
               { encabezado: 'Valor', valor: (f: Fila) => f.valor, numerica: true }]
            : columnas}
          traer={async () => ({ filas: resumen ? filasDelResumen : filas, truncado: false })}
        />
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

      {resumen ? (
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
        <DataTable
          columns={columnas.map((c) => ({
            id: c.encabezado, header: c.encabezado,
            accessorFn: (f: Fila) =>
              c.moneda ? formatearImporte(c.valor(f)) : (c.valor(f) ?? ''),
          }))}
          data={filas}
          onRowClick={(f: Fila) => {
            const destino = destinoDeFilaDeReporte(slug, f)
            if (destino) navegar(destino)
          }}
          emptyMessage={cargando ? 'Calculando…' : 'No hay datos con esos filtros.'}
        />
      )}
    </div>
  )
}
