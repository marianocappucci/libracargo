/** El catálogo de reportes: qué hay y qué contesta cada uno.
 *
 * 🔑 **La lista la manda el servidor.** Repetirla acá haría que un reporte nuevo
 * no aparezca hasta tocar el frontend, y que uno que cambió sus parámetros quede
 * ofreciendo un filtro que ya no existe.
 */
import { ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import type { Reporte } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import { mensajeDeError } from '@/components/AbmMaestro'

const NOMBRE_DE_PARAMETRO: Record<string, string> = {
  rango: 'fechas', cliente: 'cliente', fletero: 'fletero/transporte',
  tercero: 'tercero', razon_social: 'razón social', origen: 'origen',
  destino: 'destino', medio_pago: 'medio de pago', tipo_caja: 'ingreso/egreso',
  rol: 'tipo de cuenta', incluir_en_cero: 'cuentas en cero', limite: 'cuántas filas',
}

export default function ReportesIndice() {
  const [catalogo, setCatalogo] = useState<Reporte[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    reportes.catalogo().then(setCatalogo).catch((e) => setError(mensajeDeError(e)))
  }, [])

  return (
    <div className="p-6">
      <h1 className="text-2xl font-semibold">Reportes</h1>
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
        {catalogo.map((r) => (
          <Link
            key={r.slug} to={`/reportes/${r.slug}`}
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
        ))}
      </div>
    </div>
  )
}
