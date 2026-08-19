/** La cuenta corriente de un tercero, con saldo corrido.
 *
 * El tercero y el rol se eligen arriba: la cuenta es el **par**, porque un
 * mismo tercero puede ser cliente y fletero a la vez y son dos cuentas.
 */
import { DataTable } from 'libra-ui/data-table'
import { useEffect, useState } from 'react'

import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import type { FilaDeCuenta, Rol, ResumenDeCuenta } from '@/api/cuentas'
import { cuentas } from '@/api/cuentas'
import { mensajeDeError } from '@/components/AbmMaestro'
import { formatearImporte } from '@/components/esquema-orden'
import type { Columna } from '@/components/impresion'
import { BotonImprimir } from '@/components/impresion'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const ROLES: { valor: Rol; etiqueta: string }[] = [
  { valor: 'cliente', etiqueta: 'Cliente' },
  { valor: 'fletero', etiqueta: 'Fletero' },
  { valor: 'proveedor', etiqueta: 'Proveedor' },
]

export default function CuentaCorriente() {
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const [rol, setRol] = useState<Rol>('cliente')
  const [terceroId, setTerceroId] = useState<number | undefined>()
  const [hasta, setHasta] = useState('')
  const [datos, setDatos] = useState<ResumenDeCuenta | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  useEffect(() => {
    if (!terceroId) { setDatos(null); return }
    setError(null)
    cuentas.ver(rol, terceroId, hasta || undefined)
      .then(setDatos)
      .catch((e) => setError(mensajeDeError(e)))
  }, [rol, terceroId, hasta])

  const listaDeTerceros =
    rol === 'fletero' ? (opciones?.fleteros ?? []) : (opciones?.clientes ?? [])

  const COLUMNAS_IMPRESAS: Columna<FilaDeCuenta>[] = [
    { encabezado: 'Fecha', valor: (f) => f.movimiento.fecha },
    { encabezado: 'Concepto', valor: (f) => f.movimiento.concepto },
    { encabezado: 'Detalle', valor: (f) => f.movimiento.descripcion },
    { encabezado: 'Debe', valor: (f) => f.movimiento.debe, numerica: true, moneda: true },
    { encabezado: 'Haber', valor: (f) => f.movimiento.haber, numerica: true, moneda: true },
    { encabezado: 'Saldo', valor: (f) => f.saldo, numerica: true, moneda: true },
  ]

  const columnas = [
    { accessorKey: 'movimiento.fecha', header: 'Fecha',
      accessorFn: (f: FilaDeCuenta) => f.movimiento.fecha },
    { id: 'concepto', header: 'Concepto',
      accessorFn: (f: FilaDeCuenta) => f.movimiento.concepto },
    { id: 'descripcion', header: 'Detalle',
      accessorFn: (f: FilaDeCuenta) => f.movimiento.descripcion ?? '' },
    { id: 'debe', header: 'Debe',
      accessorFn: (f: FilaDeCuenta) => formatearImporte(f.movimiento.debe) },
    { id: 'haber', header: 'Haber',
      accessorFn: (f: FilaDeCuenta) => formatearImporte(f.movimiento.haber) },
    { id: 'saldo', header: 'Saldo',
      accessorFn: (f: FilaDeCuenta) => formatearImporte(f.saldo) },
  ]

  return (
    <div className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-semibold">Cuenta corriente</h1>
        {datos && (
          <BotonImprimir
            titulo="Cuenta corriente"
            filtros={`${listaDeTerceros.find((o) => o.id === terceroId)?.etiqueta ?? ''} · cuenta ${rol}`
                     + (hasta ? ` · al ${hasta}` : '')}
            columnas={COLUMNAS_IMPRESAS}
            traer={async () => ({ filas: datos.movimientos, truncado: false })}
            totales={() => [
              { etiqueta: 'Saldo', valor: datos.saldo },
              // Los dos saldos tambien en el papel: si no coinciden, el que
              // mira la hoja impresa tiene que poder verlo igual que en pantalla.
              { etiqueta: 'Saldo recorriendo los movimientos',
                valor: datos.saldo_recorriendo },
              { etiqueta: 'Coinciden', valor: datos.coinciden ? 'sí' : '🔴 NO' },
            ]}
          />
        )}
      </div>

      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="grid gap-1">
          <Label htmlFor="cc-rol">Cuenta</Label>
          <select id="cc-rol" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
                  value={rol}
                  onChange={(e) => { setRol(e.target.value as Rol); setTerceroId(undefined) }}>
            {ROLES.map((r) => <option key={r.valor} value={r.valor}>{r.etiqueta}</option>)}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cc-tercero">Tercero</Label>
          <select id="cc-tercero" className="h-9 w-full min-w-0 rounded-md border px-2 text-sm"
                  value={terceroId ?? ''}
                  onChange={(e) => setTerceroId(e.target.value ? Number(e.target.value) : undefined)}>
            <option value="">Elegir…</option>
            {listaDeTerceros.map((o) => (
              <option key={o.id} value={o.id}>{o.etiqueta}</option>
            ))}
          </select>
        </div>
        <div className="grid gap-1">
          <Label htmlFor="cc-hasta">Saldo al</Label>
          <Input id="cc-hasta" type="date" value={hasta}
                 onChange={(e) => setHasta(e.target.value)} />
        </div>
      </div>

      {error && (
        <p role="alert" className="mb-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}

      {datos && (
        <div className="mb-4 flex flex-wrap items-center gap-6 rounded border p-4">
          <div>
            <p className="text-muted-foreground text-xs">Saldo</p>
            <p className="text-xl font-semibold">{formatearImporte(datos.saldo)}</p>
          </div>
          {/* Los dos numeros a la vista, y no solo uno. El criterio de F4 es que
              coincidan; esconder el segundo dejaria el control sin testigo. */}
          <div>
            <p className="text-muted-foreground text-xs">Recorriendo los movimientos</p>
            <p className="text-xl font-semibold">
              {formatearImporte(datos.saldo_recorriendo)}
            </p>
          </div>
          {!datos.coinciden && (
            <p role="alert" className="text-destructive text-sm font-semibold">
              🔴 Los dos caminos NO coinciden. No usar este saldo: hay un
              movimiento que una de las dos cuentas ve y la otra no.
            </p>
          )}
        </div>
      )}

      <DataTable
        columns={columnas}
        data={datos?.movimientos ?? []}
        emptyMessage={terceroId ? 'Esta cuenta no tiene movimientos.'
                                : 'Elegí una cuenta y un tercero.'}
      />
    </div>
  )
}
