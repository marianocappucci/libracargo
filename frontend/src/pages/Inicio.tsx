/** El tablero: cómo viene el negocio hoy, sin abrir nada.
 *
 * 🔑 **Cada número dice de qué período es.** Un tablero con "Facturado
 * $4.017.962.714" sin decir que son tres años de historia migrada invita a
 * leerlo como si fuera del mes. Los del mes dicen el mes, y los saldos dicen que
 * no tienen período.
 *
 * Todo sale de los reportes que ya existen: el tablero no calcula nada por su
 * cuenta, así que no puede decir un número distinto del de su reporte.
 */
import { EstadoDeOrden } from '@/components/EstadoDeOrden'
import { DataTable } from 'libra-ui/data-table'
import { ArrowRight } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import type { FilaDeSaldo, Resumen } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import type { Orden } from '@/api/ordenes'
import { ordenes as apiOrdenes, cargarOpciones } from '@/api/ordenes'
import type { Opciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { irA } from '@/navegacion'
import { formatearImporte } from '@/components/esquema-orden'
import { sumarImportes } from '@/api/comprobantes'
import { TarjetaIndicador } from 'libra-ui/TarjetaIndicador'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { formatearFecha } from '@/components/esquema-orden'
import { primerDiaDelMesISO } from 'libra-ui/fechas'
import { ICONOS_LC } from '@/iconos'

/** El primer día del mes en curso, en hora de Argentina. */
const primerDiaDelMes = primerDiaDelMesISO

export default function Inicio() {
  const navegar = useNavigate()
  const [mes, setMes] = useState<Resumen | null>(null)
  const [historico, setHistorico] = useState<Resumen | null>(null)
  const [saldos, setSaldos] = useState<FilaDeSaldo[]>([])
  const [ultimas, setUltimas] = useState<Orden[]>([])
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const desde = primerDiaDelMes()
    Promise.all([
      reportes.resumen({ desde }),
      reportes.resumen(),
      reportes.saldos(),
      apiOrdenes.listar({ limite: 8 }),
      cargarOpciones(),
    ])
      .then(([m, h, s, o, op]) => {
        setMes(m); setHistorico(h); setSaldos(s); setUltimas(o); setOpciones(op)
      })
      .catch((e) => setError(mensajeDeError(e)))
  }, [])

  const porRol = (rol: string) =>
    sumarImportes(saldos.filter((s) => s.rol === rol).map((s) => s.saldo))

  const nombre = (lista: { id: number; etiqueta: string }[] | undefined, id: number | null) =>
    lista?.find((o) => o.id === id)?.etiqueta ?? ''

  const mesLegible = new Intl.DateTimeFormat('es-AR', {
    month: 'long', year: 'numeric', timeZone: 'America/Argentina/Buenos_Aires',
  }).format(new Date())

  return (
    <div>
      <TituloPantalla icono={ICONOS_LC.dashboard}>LibraCargo</TituloPantalla>
      <p className="text-muted-foreground mt-1 text-sm">
        Cómo viene {mesLegible}. Los saldos son de hoy y no tienen período.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {mes && historico && (
        <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
          <TarjetaIndicador etiqueta="Órdenes del mes" concepto="ordenesDeCarga" a="/ordenes"
                            valor={String(mes.ordenes)}
                            ayuda={`${historico.ordenes} en total`} />
          <TarjetaIndicador etiqueta="Facturado en el mes" concepto="facturado" a="/comprobantes"
                            valor={formatearImporte(mes.facturado)}
                            ayuda={`${mes.comprobantes} comprobante(s) en ${mesLegible}`} />
          <TarjetaIndicador etiqueta="Cobrado en el mes" concepto="cobros" a="/caja"
                            valor={formatearImporte(mes.cobrado)}
                            ayuda={`pagado ${formatearImporte(mes.pagado)}`} />
          <TarjetaIndicador etiqueta="Pendientes de facturar" concepto="comprobantesAFacturar"
                            a="/reportes/pendientes-de-facturar"
                            valor={String(historico.ordenes_pendientes)}
                            ayuda="órdenes sin comprobante, de todo el histórico" />
          <TarjetaIndicador etiqueta="Saldo de clientes" concepto="clientes" a="/reportes/saldos"
                            valor={formatearImporte(porRol('cliente'))}
                            ayuda={`${saldos.filter((s) => s.rol === 'cliente').length} cuentas con saldo`} />
          <TarjetaIndicador etiqueta="Saldo de fleteros" concepto="fleteros" a="/reportes/saldos"
                            valor={formatearImporte(porRol('fletero'))}
                            ayuda={`${saldos.filter((s) => s.rol === 'fletero').length} cuentas con saldo`} />
          {/* `producto`: en LibraCargo el camión es de los fleteros y Proveedores lleva `Store` (ADR-035). */}
          <TarjetaIndicador etiqueta="Saldo de proveedores" concepto="proveedores" producto="libracargo"
                            a="/reportes/saldos"
                            valor={formatearImporte(porRol('proveedor'))}
                            ayuda={`${saldos.filter((s) => s.rol === 'proveedor').length} cuentas con saldo`} />
          <TarjetaIndicador etiqueta="Comisión del mes" concepto="comisiones" a="/reportes/por-fletero"
                            valor={formatearImporte(mes.comision)}
                            ayuda="de las órdenes del mes" />
        </div>
      )}

      <section className="mt-8">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Últimas órdenes</h2>
          <Link to="/ordenes"
                className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
            Ver todas <ArrowRight className="size-3" />
          </Link>
        </div>
        <DataTable
          columns={[
            { id: 'fecha', header: 'Fecha', accessorFn: (o: Orden) => o.fecha,
              cell: ({ row }: { row: { original: Orden } }) => formatearFecha(row.original.fecha) },
            { id: 'cliente', header: 'Cliente',
              accessorFn: (o: Orden) => nombre(opciones?.clientes, o.cliente_id) },
            { id: 'ruta', header: 'Ruta',
              accessorFn: (o: Orden) =>
                `${nombre(opciones?.localidades, o.origen_id)} → ${nombre(opciones?.localidades, o.destino_id)}` },
            { id: 'estado', header: 'Estado',
              accessorFn: (o: Orden) => o.estado,
              cell: ({ row }: { row: { original: Orden } }) => (
                <EstadoDeOrden estado={row.original.estado} />
              ) },
            { id: 'total', header: 'Total',
              accessorFn: (o: Orden) => formatearImporte(o.total) },
          ]}
          data={ultimas}
          onRowClick={(o: Orden) => navegar(irA.orden(o.id))}
          emptyMessage="Todavía no hay órdenes cargadas."
        />
      </section>

      <section className="mt-8">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-lg font-semibold">Las cuentas más grandes</h2>
          <Link to="/reportes/saldos"
                className="text-muted-foreground inline-flex items-center gap-1 text-sm hover:underline">
            Ver todas <ArrowRight className="size-3" />
          </Link>
        </div>
        <DataTable
          columns={[
            { id: 'tercero', header: 'Tercero', accessorFn: (s: FilaDeSaldo) => s.tercero },
            { id: 'rol', header: 'Cuenta', accessorFn: (s: FilaDeSaldo) => s.rol },
            { id: 'ultimo', header: 'Último movimiento',
              accessorFn: (s: FilaDeSaldo) => s.ultimo_movimiento ?? '' },
            { id: 'saldo', header: 'Saldo',
              accessorFn: (s: FilaDeSaldo) => formatearImporte(s.saldo) },
          ]}
          data={saldos.slice(0, 8)}
          onRowClick={(s: FilaDeSaldo) => navegar(irA.cuenta(s.rol, s.tercero_id))}
          emptyMessage="Ninguna cuenta tiene saldo."
        />
      </section>
    </div>
  )
}
