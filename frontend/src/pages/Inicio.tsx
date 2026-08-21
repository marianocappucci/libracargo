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
import { DataTable } from 'libra-ui/data-table'
import {
  AlertTriangle, ArrowRight, BookOpen, ClipboardList, Receipt, Wallet,
} from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'

import type { FilaDeSaldo, Resumen } from '@/api/reportes'
import { reportes } from '@/api/reportes'
import type { Orden } from '@/api/ordenes'
import { ordenes as apiOrdenes, cargarOpciones } from '@/api/ordenes'
import type { Opciones } from '@/api/ordenes'
import { mensajeDeError } from '@/components/AbmMaestro'
import { irA } from '@/navegacion'
import { hoyEnArgentina, formatearImporte } from '@/components/esquema-orden'
import { sumarImportes } from '@/api/comprobantes'

/** El primer día del mes en curso, en hora de Argentina. */
function primerDiaDelMes(): string {
  return `${hoyEnArgentina().slice(0, 7)}-01`
}

function Tarjeta({ titulo, valor, detalle, a, icono: Icono }: {
  titulo: string; valor: string; detalle: string
  a?: string; icono: typeof Wallet
}) {
  const cuerpo = (
    <>
      <div className="text-muted-foreground flex items-center gap-2 text-xs">
        <Icono className="size-4" /> {titulo}
      </div>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{valor}</p>
      {/* El período va SIEMPRE: un número sin su universo no se puede leer. */}
      <p className="text-muted-foreground mt-1 text-xs">{detalle}</p>
    </>
  )
  return a
    ? <Link to={a} className="hover:bg-accent rounded border p-4 transition-colors">{cuerpo}</Link>
    : <div className="rounded border p-4">{cuerpo}</div>
}

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
    <div className="p-6">
      <h1 className="text-2xl font-semibold">LibraCargo</h1>
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
          <Tarjeta titulo="Órdenes del mes" icono={ClipboardList} a="/ordenes"
                   valor={String(mes.ordenes)}
                   detalle={`${historico.ordenes} en total`} />
          <Tarjeta titulo="Facturado en el mes" icono={Receipt} a="/comprobantes"
                   valor={formatearImporte(mes.facturado)}
                   detalle={`${mes.comprobantes} comprobante(s) en ${mesLegible}`} />
          <Tarjeta titulo="Cobrado en el mes" icono={Wallet} a="/caja"
                   valor={formatearImporte(mes.cobrado)}
                   detalle={`pagado ${formatearImporte(mes.pagado)}`} />
          <Tarjeta titulo="Pendientes de facturar" icono={AlertTriangle}
                   a="/reportes/pendientes-de-facturar"
                   valor={String(historico.ordenes_pendientes)}
                   detalle="órdenes sin comprobante, de todo el histórico" />
          <Tarjeta titulo="Saldo de clientes" icono={BookOpen} a="/reportes/saldos"
                   valor={formatearImporte(porRol('cliente'))}
                   detalle={`${saldos.filter((s) => s.rol === 'cliente').length} cuentas con saldo`} />
          <Tarjeta titulo="Saldo de fleteros" icono={BookOpen} a="/reportes/saldos"
                   valor={formatearImporte(porRol('fletero'))}
                   detalle={`${saldos.filter((s) => s.rol === 'fletero').length} cuentas con saldo`} />
          <Tarjeta titulo="Saldo de proveedores" icono={BookOpen} a="/reportes/saldos"
                   valor={formatearImporte(porRol('proveedor'))}
                   detalle={`${saldos.filter((s) => s.rol === 'proveedor').length} cuentas con saldo`} />
          <Tarjeta titulo="Comisión del mes" icono={ClipboardList} a="/reportes/por-fletero"
                   valor={formatearImporte(mes.comision)}
                   detalle="de las órdenes del mes" />
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
            { id: 'fecha', header: 'Fecha', accessorFn: (o: Orden) => o.fecha },
            { id: 'cliente', header: 'Cliente',
              accessorFn: (o: Orden) => nombre(opciones?.clientes, o.cliente_id) },
            { id: 'ruta', header: 'Ruta',
              accessorFn: (o: Orden) =>
                `${nombre(opciones?.localidades, o.origen_id)} → ${nombre(opciones?.localidades, o.destino_id)}` },
            { id: 'estado', header: 'Estado', accessorFn: (o: Orden) => o.estado },
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
