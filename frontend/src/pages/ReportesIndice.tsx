/** El catálogo de reportes: qué hay y qué contesta cada uno.
 *
 * 🔑 **La lista la manda el servidor.** Repetirla acá haría que un reporte nuevo
 * no aparezca hasta tocar el frontend, y que uno que cambió sus parámetros quede
 * ofreciendo un filtro que ya no existe.
 *
 * 🔑 **Y desde el 2026-08-22 acá también están los listados.** Cada pantalla
 * tenía su botón "Imprimir" arriba a la derecha y ninguno obligaba a poner
 * fechas: se apretaba con la pantalla recién abierta y salían noventa hojas. Los
 * listados viven acá, donde el rango es obligatorio.
 */
import { ArrowRight, BarChart3 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Reporte } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

const NOMBRE_DE_PARAMETRO: Record<string, string> = {
  rango: 'fechas', cliente: 'cliente', fletero: 'fletero/transporte',
  proveedor: 'proveedor', tercero: 'tercero', razon_social: 'razón social',
  origen: 'origen', destino: 'destino', medio_pago: 'medio de pago',
  tipo_caja: 'ingreso/egreso', rol: 'tipo de cuenta',
  incluir_en_cero: 'cuentas en cero', limite: 'cuántas filas',
  entidad: 'entidad', usuario: 'usuario', accion: 'alta/modificación/baja',
}

function Tarjeta({ r }: { r: Reporte }) {
  return (
    <Link
      to={`/reportes/${r.slug}`}
      className="hover:bg-accent group rounded border p-4 transition-colors"
    >
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{r.titulo}</h2>
        <ArrowRight className="text-muted-foreground size-4" />
      </div>
      <p className="text-muted-foreground mt-1 text-sm">{r.descripcion}</p>
      <p className="text-muted-foreground mt-2 text-xs">
        Se filtra por: {r.parametros.map((p) => NOMBRE_DE_PARAMETRO[p] ?? p).join(', ')}
      </p>
    </Link>
  )
}

export default function ReportesIndice() {
  const [catalogo, setCatalogo] = useState<Reporte[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    reportes.catalogo().then(setCatalogo).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // 🔑 **El catalogo ya viene filtrado por rol**: a un operador el backend no le
  // manda el listado del log, que es el unico de administracion. La regla vive
  // ahi y no aca, para que no haya dos copias de un permiso.
  const agregados = catalogo.filter((r) => !r.detalle)
  const listados = catalogo.filter((r) => r.detalle)

  return (
    <div className="p-6">
      <TituloPantalla icono={BarChart3}>Reportes</TituloPantalla>
      <p className="text-muted-foreground mt-1 text-sm">
        Cada uno se abre por separado y se parametriza por lo suyo. Todos se
        pueden imprimir.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      <div className="mt-6 grid gap-3 md:grid-cols-2">
        {agregados.map((r) => <Tarjeta key={r.slug} r={r} />)}
      </div>

      {listados.length > 0 && (
        <>
          <h2 className="mt-8 text-lg font-semibold">Listados para imprimir</h2>
          <p className="text-muted-foreground mt-1 text-sm">
            El detalle de cada pantalla, línea por línea. Piden un{' '}
            <strong>desde</strong> y un <strong>hasta</strong>: sin fechas es la
            tabla entera, y eso son noventa hojas.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-2">
            {listados.map((r) => <Tarjeta key={r.slug} r={r} />)}
          </div>
        </>
      )}
    </div>
  )
}
