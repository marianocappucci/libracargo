/** Reportes: los números del negocio, agregados en la base.
 *
 * Un solo rango de fechas arriba manda sobre todos: el caso real es "quiero ver
 * julio", no "quiero ver julio en este reporte y agosto en el de al lado".
 *
 * 🔑 **Cada reporte se puede imprimir por separado**, y el papel dice sobre qué
 * rango está calculado. Un total sin su universo es un número que nadie puede
 * verificar.
 */
import { DataTable } from 'libra-ui/data-table'
import { useCallback, useEffect, useState } from 'react'

import type {
  FilaDeCaja, FilaDeRazonSocial, FilaDeRuta, FilaDeSaldo, FilaDeTercero, Resumen,
} from '@/api/reportes'
import { reportes } from '@/api/reportes'
import { mensajeDeError } from '@/components/AbmMaestro'
import type { Columna } from '@/components/impresion'
import { BotonImprimir } from '@/components/impresion'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

function Tarjeta({ titulo, valor, detalle }: { titulo: string; valor: string; detalle?: string }) {
  return (
    <div className="rounded border p-4">
      <p className="text-muted-foreground text-xs">{titulo}</p>
      <p className="text-2xl font-semibold tabular-nums">{valor}</p>
      {detalle && <p className="text-muted-foreground text-xs">{detalle}</p>}
    </div>
  )
}

function Seccion<T>({ titulo, ayuda, filas, columnas, rango }: {
  titulo: string
  ayuda?: string
  filas: T[]
  columnas: Columna<T>[]
  rango: string
}) {
  return (
    <section className="mb-8">
      <div className="mb-2 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">{titulo}</h2>
          {ayuda && <p className="text-muted-foreground text-xs">{ayuda}</p>}
        </div>
        <BotonImprimir
          titulo={titulo} filtros={rango} columnas={columnas}
          traer={async () => ({ filas, truncado: false })}
        />
      </div>
      <DataTable
        columns={columnas.map((c) => ({
          id: c.encabezado, header: c.encabezado,
          accessorFn: (f: T) => c.valor(f) ?? '',
        }))}
        data={filas}
        emptyMessage="No hay datos en ese período."
      />
    </section>
  )
}

export default function Reportes() {
  const [desde, setDesde] = useState('')
  const [hasta, setHasta] = useState('')
  const [resumen, setResumen] = useState<Resumen | null>(null)
  const [clientes, setClientes] = useState<FilaDeTercero[]>([])
  const [fleteros, setFleteros] = useState<FilaDeTercero[]>([])
  const [saldos, setSaldos] = useState<FilaDeSaldo[]>([])
  const [caja, setCaja] = useState<FilaDeCaja[]>([])
  const [razones, setRazones] = useState<FilaDeRazonSocial[]>([])
  const [rutas, setRutas] = useState<FilaDeRuta[]>([])
  const [error, setError] = useState<string | null>(null)

  const recargar = useCallback(() => {
    const rango = { desde: desde || undefined, hasta: hasta || undefined }
    setError(null)
    Promise.all([
      reportes.resumen(rango), reportes.porCliente(rango), reportes.porFletero(rango),
      reportes.saldos(), reportes.caja(rango), reportes.porRazonSocial(rango),
      reportes.porRuta(rango),
    ])
      .then(([r, c, f, s, k, rs, ru]) => {
        setResumen(r); setClientes(c); setFleteros(f)
        setSaldos(s); setCaja(k); setRazones(rs); setRutas(ru)
      })
      .catch((e) => setError(mensajeDeError(e)))
  }, [desde, hasta])

  useEffect(recargar, [recargar])

  const rango = desde || hasta
    ? `${desde || 'el principio'} a ${hasta || 'hoy'}`
    : 'todo el período cargado'

  const deTercero: Columna<FilaDeTercero>[] = [
    { encabezado: 'Tercero', valor: (f) => f.tercero },
    { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
    { encabezado: 'Facturado', valor: (f) => f.facturado, numerica: true },
    { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true },
    { encabezado: 'Saldo hoy', valor: (f) => f.saldo, numerica: true },
  ]

  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-semibold">Reportes</h1>

      <div className="no-imprimir mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <div className="grid gap-1">
          <Label htmlFor="r-desde">Desde</Label>
          <Input id="r-desde" type="date" value={desde}
                 onChange={(e) => setDesde(e.target.value)} />
        </div>
        <div className="grid gap-1">
          <Label htmlFor="r-hasta">Hasta</Label>
          <Input id="r-hasta" type="date" value={hasta}
                 onChange={(e) => setHasta(e.target.value)} />
        </div>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {resumen && (
        <section className="mb-8">
          <div className="mb-2 flex items-center justify-between">
            <h2 className="text-lg font-semibold">Resumen — {rango}</h2>
            <BotonImprimir
              titulo="Resumen del período" filtros={rango}
              columnas={[
                { encabezado: 'Concepto', valor: (f: [string, string]) => f[0] },
                { encabezado: 'Valor', valor: (f: [string, string]) => f[1], numerica: true },
              ]}
              traer={async () => ({
                filas: [
                  ['Órdenes', String(resumen.ordenes)],
                  ['Órdenes pendientes de facturar', String(resumen.ordenes_pendientes)],
                  ['Órdenes anuladas', String(resumen.ordenes_anuladas)],
                  ['Tarifa', resumen.tarifa],
                  ['IVA', resumen.iva],
                  ['Total de las órdenes', resumen.total],
                  ['Comisión', resumen.comision],
                  ['Comprobantes', String(resumen.comprobantes)],
                  ['Facturado', resumen.facturado],
                  ['Cobrado', resumen.cobrado],
                  ['Pagado', resumen.pagado],
                ] as [string, string][],
                truncado: false,
              })}
            />
          </div>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tarjeta titulo="Órdenes" valor={String(resumen.ordenes)}
                     detalle={`${resumen.ordenes_pendientes} sin facturar · ${resumen.ordenes_anuladas} anuladas`} />
            <Tarjeta titulo="Total de las órdenes" valor={resumen.total}
                     detalle={`tarifa ${resumen.tarifa} + IVA ${resumen.iva}`} />
            <Tarjeta titulo="Comisión" valor={resumen.comision} />
            <Tarjeta titulo="Facturado" valor={resumen.facturado}
                     detalle={`${resumen.comprobantes} comprobante(s)`} />
            <Tarjeta titulo="Cobrado" valor={resumen.cobrado} />
            <Tarjeta titulo="Pagado" valor={resumen.pagado}
                     detalle={`${resumen.movimientos_caja} movimiento(s) de caja`} />
          </div>
        </section>
      )}

      <Seccion titulo="Clientes" rango={rango} filas={clientes} columnas={deTercero}
               ayuda="Ordenados por lo facturado en el período. El saldo es el de hoy, no el del período." />

      <Seccion titulo="Fleteros" rango={rango} filas={fleteros} columnas={deTercero}
               ayuda="La comisión es la de las órdenes que hizo en el período." />

      <Seccion
        titulo="Saldos de cuenta corriente" rango="todas las cuentas con saldo distinto de cero"
        ayuda="Las tres cuentas de una vez. En el sistema viejo había que abrirlas de a una."
        filas={saldos}
        columnas={[
          { encabezado: 'Tercero', valor: (f) => f.tercero },
          { encabezado: 'Cuenta', valor: (f) => f.rol },
          { encabezado: 'Movimientos', valor: (f) => f.movimientos, numerica: true },
          { encabezado: 'Último', valor: (f) => f.ultimo_movimiento },
          { encabezado: 'Saldo', valor: (f) => f.saldo, numerica: true },
        ]} />

      <Seccion
        titulo="Caja" rango={rango} filas={caja}
        ayuda="Abierta por tipo y medio de pago."
        columnas={[
          { encabezado: 'Tipo', valor: (f) => f.tipo },
          { encabezado: 'Medio de pago', valor: (f) => f.medio_pago },
          { encabezado: 'Movimientos', valor: (f) => f.movimientos, numerica: true },
          { encabezado: 'Importe', valor: (f) => f.importe, numerica: true },
        ]} />

      <Seccion
        titulo="Facturado por razón social" rango={rango} filas={razones}
        columnas={[
          { encabezado: 'Razón social', valor: (f) => f.razon_social },
          { encabezado: 'Comprobantes', valor: (f) => f.comprobantes, numerica: true },
          { encabezado: 'Neto', valor: (f) => f.neto, numerica: true },
          { encabezado: 'IVA', valor: (f) => f.iva, numerica: true },
          { encabezado: 'Total', valor: (f) => f.total, numerica: true },
        ]} />

      <Seccion
        titulo="Rutas más transitadas" rango={rango} filas={rutas}
        ayuda="Origen y destino como par: la ida y la vuelta son dos rutas distintas."
        columnas={[
          { encabezado: 'Origen', valor: (f) => f.origen },
          { encabezado: 'Destino', valor: (f) => f.destino },
          { encabezado: 'Órdenes', valor: (f) => f.ordenes, numerica: true },
          { encabezado: 'Cantidad', valor: (f) => f.cantidad, numerica: true },
          { encabezado: 'Total', valor: (f) => f.total, numerica: true },
          { encabezado: 'Comisión', valor: (f) => f.comision, numerica: true },
        ]} />
    </div>
  )
}
