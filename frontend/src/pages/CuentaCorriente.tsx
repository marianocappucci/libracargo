import type { LucideIcon } from 'lucide-react'
/** La cuenta corriente de un tercero, con saldo corrido.
 *
 * La cuenta es el **par** (tercero, rol): un mismo tercero puede ser cliente y
 * fletero a la vez y son dos cuentas. El rol son **tres pestañas** —Clientes,
 * Fleteros, Proveedores— y, adentro, un campo donde se **escribe** para buscar
 * el tercero por nombre o por CUIT (antes era un `<select>` «Cuenta» y una
 * lista que sólo tenía buscador a partir de 12 terceros; pedido del humano,
 * 2026-10-07).
 *
 * ## La pestaña y el tercero van en la URL
 *
 * `/cuentas?rol=fletero&tercero=5`: la URL es la única fuente de verdad, y por
 * eso los enlaces del tablero, de los reportes de saldos y de caja siguen
 * andando. Cambiar de pestaña **empuja** una entrada al historial (atrás vuelve
 * a la pestaña anterior) y **descarta el tercero**, que es de un rol y no del
 * otro. Elegir un tercero **reemplaza** la entrada: es afinar la búsqueda, no
 * navegar. Sin `rol` en la URL —desde caja, que guarda el tercero y no la
 * cuenta— se abre la primera cuenta que ese tercero tenga.
 */
import { DataTable } from 'libra-ui/data-table'
import { SelectBuscable } from 'libra-ui/SelectBuscable'
import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { ICONOS_LC } from '@/iconos'
import { origenDelMovimiento } from '@/navegacion'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'
import { formatearFecha } from '@/components/esquema-orden'

/** Las tres cuentas. `etiqueta` es la del campo (singular); `pestana`, la de la pestaña. */
const ROLES: { valor: Rol; pestana: string; etiqueta: string; icono: LucideIcon }[] = [
  { valor: 'cliente', pestana: 'Clientes', etiqueta: 'Cliente', icono: ICONOS_LC.clientes },
  { valor: 'fletero', pestana: 'Fleteros', etiqueta: 'Fletero', icono: ICONOS_LC.fleteros },
  { valor: 'proveedor', pestana: 'Proveedores', etiqueta: 'Proveedor', icono: ICONOS_LC.proveedores },
]

/** El rol que pide un query, o `null` si falta o no es uno de los tres. */
function rolDe(valor: string | null): Rol | null {
  return ROLES.find((r) => r.valor === valor)?.valor ?? null
}

export default function CuentaCorriente() {
  const [opciones, setOpciones] = useState<Opciones | null>(null)
  const navegar = useNavigate()
  const [params, setParams] = useSearchParams()
  const rolDeLaUrl = rolDe(params.get('rol'))
  const terceroDeLaUrl = Number(params.get('tercero'))
  const terceroId = params.get('tercero') && Number.isFinite(terceroDeLaUrl) ? terceroDeLaUrl : undefined
  const [hasta, setHasta] = useState('')
  const [datos, setDatos] = useState<ResumenDeCuenta | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    cargarOpciones().then(setOpciones).catch((e) => setError(mensajeDeError(e)))
  }, [])

  // El rol de la pestaña activa. Sin `rol` en la URL y con un tercero —el caso
  // de caja— es el primero que ese tercero tenga, y para saberlo hacen falta
  // las listas: hasta que llegan es Clientes, y la cuenta no se pide todavía.
  const rol: Rol = useMemo(() => {
    if (rolDeLaUrl) return rolDeLaUrl
    if (terceroId === undefined || !opciones) return 'cliente'
    const tiene = (lista: { id: number | string }[]) => lista.some((t) => t.id === terceroId)
    return tiene(opciones.clientes) ? 'cliente'
      : tiene(opciones.fleteros) ? 'fletero'
      : tiene(opciones.proveedores) ? 'proveedor'
      : 'cliente'
  }, [rolDeLaUrl, terceroId, opciones])
  const esperandoElRol = !rolDeLaUrl && terceroId !== undefined && !opciones

  useEffect(() => {
    if (!terceroId || esperandoElRol) { setDatos(null); return }
    setError(null)
    // Si se cambia de pestaña o de tercero antes de que llegue, la respuesta
    // vieja se descarta: pintaría la cuenta de otro.
    let vigente = true
    cuentas.ver(rol, terceroId, hasta || undefined)
      .then((d) => { if (vigente) setDatos(d) })
      .catch((e) => { if (vigente) setError(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [rol, terceroId, hasta, esperandoElRol])

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
  const opcionesDelCampo = useMemo(
    () => listaDeTerceros.map((t) => ({ value: String(t.id), label: t.etiqueta, hint: t.detalle })),
    [listaDeTerceros],
  )

  // Cambiar de pestaña empuja una entrada y deja el tercero afuera.
  function elegirPestana(valor: string) {
    const nuevo = rolDe(valor)
    if (nuevo && nuevo !== rol) setParams({ rol: nuevo })
  }

  // Elegir (o quitar) el tercero reemplaza la entrada, y fija el rol en la URL.
  function elegirTercero(valor: string) {
    setParams(valor ? { rol, tercero: valor } : { rol }, { replace: true })
  }

  const COLUMNAS_IMPRESAS: Columna<FilaDeCuenta>[] = [
    { encabezado: 'Fecha', valor: (f) => formatearFecha(f.movimiento.fecha) },
    { encabezado: 'Concepto', valor: (f) => f.movimiento.concepto },
    { encabezado: 'Detalle', valor: (f) => f.movimiento.descripcion },
    { encabezado: 'Debe', valor: (f) => f.movimiento.debe, numerica: true, moneda: true },
    { encabezado: 'Haber', valor: (f) => f.movimiento.haber, numerica: true, moneda: true },
    { encabezado: 'Saldo', valor: (f) => f.saldo, numerica: true, moneda: true },
  ]

  const columnas = [
    { accessorKey: 'movimiento.fecha', header: 'Fecha',
      accessorFn: (f: FilaDeCuenta) => f.movimiento.fecha,
      cell: ({ row }: { row: { original: FilaDeCuenta } }) =>
        formatearFecha(row.original.movimiento.fecha) },
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

  // Lo de adentro de cada pestaña es lo mismo con otro rol, y sólo la pestaña
  // activa se monta (`TabsContent` desmonta las otras): se arma una vez.
  const etiquetaDelRol = ROLES.find((r) => r.valor === rol)!.etiqueta
  const cuerpo = (
    <>
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
        <div className="grid min-w-0 gap-1 md:col-span-2">
          <Label htmlFor="cc-tercero">{etiquetaDelRol}</Label>
          {/* Siempre el campo donde se escribe, sea cual sea el largo de la lista:
              con diez fleteros también se busca por letras. */}
          <SelectBuscable
            buscarEscribiendo
            id="cc-tercero"
            value={terceroId === undefined ? '' : String(terceroId)}
            onChange={elegirTercero}
            opciones={opcionesDelCampo}
            placeholder={`Buscar ${etiquetaDelRol.toLowerCase()} por nombre o CUIT…`}
            emptyMessage="No hay ninguno con ese nombre o CUIT."
            className="w-full min-w-0"
            limpiable
          />
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
                                : `Buscá y elegí un ${etiquetaDelRol.toLowerCase()}.`}
      />
    </>
  )

  return (
    <div>
      <div className="mb-4">
        <TituloPantalla
          icono={ICONOS_LC.cuentaCorriente}
          acciones={datos && (
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
        >
          Cuenta corriente
        </TituloPantalla>
      </div>

      <Tabs value={rol} onValueChange={elegirPestana} className="gap-4">
        <TabsList className="no-imprimir">
          {ROLES.map((r) => (
            <TabsTrigger key={r.valor} value={r.valor}>
              <r.icono className="size-4" />{r.pestana}
            </TabsTrigger>
          ))}
        </TabsList>
        {ROLES.map((r) => <TabsContent key={r.valor} value={r.valor}>{cuerpo}</TabsContent>)}
      </Tabs>
    </div>
  )
}
