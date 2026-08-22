import { BookOpen } from 'lucide-react'
/** La cuenta corriente de un tercero, con saldo corrido.
 *
 * El tercero y el rol se eligen arriba: la cuenta es el **par**, porque un
 * mismo tercero puede ser cliente y fletero a la vez y son dos cuentas.
 */
import { DataTable } from 'libra-ui/data-table'
import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

import type { Opciones } from '@/api/ordenes'
import { cargarOpciones } from '@/api/ordenes'
import type { FilaDeCuenta, Rol, ResumenDeCuenta } from '@/api/cuentas'
import { cuentas } from '@/api/cuentas'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Elegir } from '@/components/Elegir'
import { formatearImporte } from '@/components/esquema-orden'
import type { Columna } from '@/components/impresion'
import { BotonImprimir } from '@/components/impresion'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { origenDelMovimiento } from '@/navegacion'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

const ROLES: { valor: Rol; etiqueta: string }[] = [
  { valor: 'cliente', etiqueta: 'Cliente' },
  { valor: 'fletero', etiqueta: 'Fletero' },
  { valor: 'proveedor', etiqueta: 'Proveedor' },
]

export default function CuentaCorriente() {
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const navegar = useNavigate()
  const [params] = useSearchParams()
  // La cuenta se puede abrir por URL: `/cuentas?rol=fletero&tercero=5`. Es a
  // donde llevan el tablero y los reportes de saldos. El `rol` puede venir
  // vacio -- desde caja, donde el movimiento guarda el tercero y no la cuenta --
  // y entonces se elige el primer rol que ese tercero tenga.
  const rolDeLaUrl = params.get('rol') as Rol | null
  const terceroDeLaUrl = params.get('tercero')
  const [rol, setRol] = useState<Rol>(rolDeLaUrl ?? 'cliente')
  const [terceroId, setTerceroId] = useState<number | undefined>()
  const [hasta, setHasta] = useState('')
  const [datos, setDatos] = useState<ResumenDeCuenta | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // Aplica lo que vino por URL. Espera a `opciones` porque sin las listas no se
  // puede saber qué roles tiene ese tercero — y desde caja el rol no viene.
  //
  // 🔑 Depende de los parámetros y no del estado de los selects: una vez
  // aplicado, cambiar la cuenta a mano no vuelve a dispararlo. Si dependiera de
  // `rol`, elegir otro rol lo devolvería al de la URL y el select quedaría
  // trabado.
  useEffect(() => {
    if (!terceroDeLaUrl || !opciones) return
    const id = Number(terceroDeLaUrl)
    if (!Number.isFinite(id)) return
    if (rolDeLaUrl) {
      setRol(rolDeLaUrl)
    } else {
      const tiene = (lista: { id: number }[]) => lista.some((t) => t.id === id)
      const primero: Rol | undefined =
        tiene(opciones.clientes) ? 'cliente'
        : tiene(opciones.fleteros) ? 'fletero'
        : tiene(opciones.proveedores) ? 'proveedor'
        : undefined
      if (primero) setRol(primero)
    }
    setTerceroId(id)
  }, [terceroDeLaUrl, rolDeLaUrl, opciones])

  useEffect(() => {
    if (!terceroId) { setDatos(null); return }
    setError(null)
    cuentas.ver(rol, terceroId, hasta || undefined)
      .then(setDatos)
      .catch((e) => setError(mensajeDeError(e)))
  }, [rol, terceroId, hasta])

  // 🔴 Decía `rol === 'fletero' ? fleteros : clientes`, así que con el rol
  // "Proveedor" elegido —que el desplegable de arriba ofrece— la lista de abajo
  // era la de CLIENTES. Los 15 proveedores de la instancia del cliente son
  // proveedor-puro: ninguno se podía elegir, y sus 3.347 movimientos de cuenta
  // no había forma de abrirlos. Un `switch` sobre el rol y no un ternario: con
  // tres valores, el ternario obliga a que uno de ellos sea "el resto".
  const listaDeTerceros = {
    cliente: opciones?.clientes ?? [],
    fletero: opciones?.fleteros ?? [],
    proveedor: opciones?.proveedores ?? [],
  }[rol]

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
        <TituloPantalla icono={BookOpen}>Cuenta corriente</TituloPantalla>
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
        <Elegir id="cc-tercero" etiqueta="Tercero" vacio="Elegir…"
                valor={terceroId === undefined ? '' : String(terceroId)}
                opciones={listaDeTerceros}
                alCambiar={(v) => setTerceroId(v ? Number(v) : undefined)} />
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

      {/* Es la pantalla donde mas se pedia poder clickear: cada linea sale de
          una orden, de un comprobante o de un movimiento de caja, y hasta ahora
          no habia forma de llegar al documento que la explica. Las lineas sin
          origen -- los asientos sueltos del historico migrado -- no son
          clickeables, y `origenDelMovimiento` devolviendo null es lo que se lo
          dice a la tabla. */}
      <DataTable
        columns={columnas}
        data={datos?.movimientos ?? []}
        onRowClick={(fila) => {
          const destino = origenDelMovimiento(fila)
          if (destino) navegar(destino)
        }}
        emptyMessage={terceroId ? 'Esta cuenta no tiene movimientos.'
                                : 'Elegí una cuenta y un tercero.'}
      />
    </div>
  )
}
