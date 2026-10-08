/** Qué concepto del catálogo (`libra-ui/iconos-indicador`, ADR-038) lleva cada reporte del catálogo que manda el servidor.
 *
 *  🔑 **El catálogo de reportes lo manda el servidor** (`/api/reportes`), así que el ícono no puede ir en cada entrada: se resuelve acá, por
 *  `slug`, y a un tipo que el compilador revisa (`satisfies Record<string, ConceptoIndicador>`: un concepto que no existe en el kit no compila).
 *  Un reporte nuevo del servidor sin entrada acá cae en `reportes` (el ícono de la sección) en vez de quedar sin ícono: al sumar un reporte en
 *  `app/routers/reportes.py` hay que sumar su línea acá en la misma tanda.
 */
import type { ConceptoIndicador } from 'libra-ui/iconos-indicador'

export const CONCEPTO_DE_REPORTE = {
  // Los agregados
  resumen: 'dashboard',
  'por-cliente': 'clientes',
  'por-fletero': 'fleteros',
  'pendientes-de-facturar': 'comprobantesAFacturar',
  saldos: 'saldos',
  caja: 'caja',
  'por-ruta': 'rutas',
  // Los listados: el mismo concepto que la pantalla que listan
  'listado-ordenes': 'ordenesDeCarga',
  'listado-comprobantes': 'comprobantes',
  'listado-gastos': 'gastos',
  'listado-caja': 'caja',
  'listado-logs': 'auditoria',
  // El papel para el transportista
  'pre-liquidacion-transportistas': 'liquidaciones',
} as const satisfies Record<string, ConceptoIndicador>

/** El concepto de un reporte, por su slug. Uno que el servidor sumó y acá no se conoce es `reportes`. */
export function conceptoDelReporte(slug: string): ConceptoIndicador {
  return (CONCEPTO_DE_REPORTE as Record<string, ConceptoIndicador>)[slug] ?? 'reportes'
}
