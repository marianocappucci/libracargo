/** Una pestaña de «Entidades» que es un rol: Clientes, Fleteros o Proveedores (ADR-040).
 *
 *  Es la misma tabla `terceros` vista por rol: una persona o empresa que es fletero y proveedor está en las dos
 *  pestañas, es **una** fila, y en cada una se ven los otros roles que tiene como pastillas.
 *
 *  - **El alta marca el rol de la pestaña** de entrada (`defaults`). Los otros dos se tildan en la ficha.
 *  - **CUIT repetido (409):** en vez del error pelado, el diálogo dice de quién es y ofrece sumarle el rol a la que
 *    ya existe (`POST /api/terceros/{id}/roles/{rol}`) o ir a verla. Cargarla de nuevo es lo que el modelo evita.
 *  - **La ficha del fletero** muestra sus choferes y sus vehículos (sólo lectura, con enlace).
 */
import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { BadgeEstado } from 'libra-ui/badge-estado'
import { sortableHeader } from 'libra-ui/data-table'

import { choferesDe, cuitRepetido, listarPorRol, sumarRol, vehiculosDe } from '@/api/maestros'
import type { Maestro, RolDeEntidad } from '@/api/maestros'
import { formatearCuit } from '@/api/cartas-porte'
import { AbmMaestro, mensajeDeError } from '@/components/AbmMaestro'
import type { ContextoDeConflicto } from '@/components/AbmMaestro'
import { LineaDeCartaDePorte } from '@/components/LineaDeCartaDePorte'
import { Button } from '@/components/ui/button'
import { irA, type PestanaDeEntidades } from '@/navegacion'

import { CAMPOS_TERCERO } from './definiciones'
import { useFichaEnLaUrl } from './hooks'

const ROLES: { rol: RolDeEntidad; columna: string; singular: string; pestana: PestanaDeEntidades }[] = [
  { rol: 'cliente', columna: 'es_cliente', singular: 'Cliente', pestana: 'clientes' },
  { rol: 'fletero', columna: 'es_fletero', singular: 'Fletero', pestana: 'fleteros' },
  { rol: 'proveedor', columna: 'es_proveedor', singular: 'Proveedor', pestana: 'proveedores' },
]

const PLURAL: Record<RolDeEntidad, string> = { cliente: 'Clientes', fletero: 'Fleteros', proveedor: 'Proveedores' }

/** Los otros roles de una fila, es decir los que NO son el de la pestaña. */
const otrosRoles = (f: Maestro, rol: RolDeEntidad) =>
  ROLES.filter((r) => r.rol !== rol && f[r.columna])

export function TercerosPorRol({ rol }: { rol: RolDeEntidad }) {
  const navegar = useNavigate()
  const { abrirId, alCerrarFicha } = useFichaEnLaUrl()
  const propio = ROLES.find((r) => r.rol === rol)!

  return (
    // `key`: al cambiar de pestaña es otra tabla, con otro listado y otros valores de alta.
    <AbmMaestro<Maestro>
      key={rol}
      recurso="terceros"
      titulo={PLURAL[rol]}
      singular={propio.singular.toLowerCase()}
      encabezado={false}
      campos={CAMPOS_TERCERO}
      cargar={() => listarPorRol<Maestro>(rol)}
      columnas={[
        { accessorKey: 'razon_social', header: sortableHeader('Razón social') },
        { id: 'cuit', header: sortableHeader('CUIT'),
          accessorFn: (f: Maestro) => formatearCuit(f.cuit as string | null) },
        { accessorKey: 'localidad', header: sortableHeader('Localidad') },
        {
          id: 'roles',
          header: 'Roles',
          // Sólo los OTROS: el de la pestaña ya se sabe, y repetirlo en todas las filas es ruido. El texto plano es
          // para ordenar y buscar; lo que se ve son las pastillas.
          accessorFn: (f: Maestro) => otrosRoles(f, rol).map((r) => r.singular).join(', '),
          cell: ({ row }: { row: { original: Maestro } }) => (
            <div className="flex flex-wrap gap-1">
              {otrosRoles(row.original, rol).map((r) => (
                <BadgeEstado key={r.rol} tono="neutro">{r.singular}</BadgeEstado>
              ))}
            </div>
          ),
        },
      ]}
      buscarEn={(f) => [f.razon_social as string, f.cuit as string,
                        formatearCuit(f.cuit as string | null),
                        f.localidad as string, f.contacto as string]}
      // El alta ya trae el rol de la pestaña tildado. Cliente era el único antes; ahora es el de donde se está.
      defaults={{ condicion_iva: 'consumidor_final', [propio.columna]: true } as Partial<Maestro>}
      abrirId={abrirId}
      alCerrarFicha={alCerrarFicha}
      // Al fletero, sus choferes y vehículos; al cliente, si es titular de cartas de porte (ADR-044).
      fichaExtra={rol === 'fletero' ? (f) => <FichaDelFletero fleteroId={f.id} />
        : rol === 'cliente' ? (f) => <LineaDeCartaDePorte terceroId={f.id} /> : undefined}
      conflicto={(error, ctx) => {
        const repetido = cuitRepetido(error)
        return repetido ? (
          <ConflictoDeCuit repetido={repetido} rol={rol} ctx={ctx}
                           alVer={(pestana, id) => { ctx.cerrar(); navegar(irA.entidades(pestana, id)) }} />
        ) : null
      }}
    />
  )
}

/** El CUIT ya es de otra entidad: se dice de quién y se ofrece sumarle el rol en vez de cargarla de nuevo. */
function ConflictoDeCuit({ repetido, rol, ctx, alVer }: {
  repetido: NonNullable<ReturnType<typeof cuitRepetido>>
  rol: RolDeEntidad
  ctx: ContextoDeConflicto<Maestro>
  alVer: (pestana: PestanaDeEntidades, id: number) => void
}) {
  const [error, setError] = useState<string | null>(null)
  const { existente } = repetido
  const [ocupado, setOcupado] = useState(false)
  // Sumar el rol sólo tiene sentido en un alta —en una edición el CUIT choca con OTRA fila y lo que corresponde es
  // corregirlo— y si la existente todavía no lo tiene.
  const puedeSumar = !ctx.editando && !existente.roles.includes(rol)
  // La ficha se abre en una pestaña donde esa entidad esté: la de este rol si lo tiene, o la de su primer rol.
  const pestanaDe = ROLES.find((r) => existente.roles.includes(r.rol) && r.rol === rol)
    ?? ROLES.find((r) => existente.roles.includes(r.rol))
    ?? ROLES.find((r) => r.rol === rol)!

  async function sumar() {
    setError(null)
    setOcupado(true)
    try {
      await sumarRol(existente.id, rol)
      ctx.cerrar()
      ctx.destacar(existente.id)
      ctx.recargar()
    } catch (e) {
      setError(mensajeDeError(e))
      setOcupado(false)
    }
  }

  return (
    <div role="alert" className="grid gap-3 rounded border border-destructive/40 p-3 text-sm">
      <p>{repetido.mensaje}</p>
      {error && <p>{error}</p>}
      <div className="flex flex-wrap gap-2">
        {puedeSumar && (
          <Button size="sm" disabled={ocupado} onClick={sumar}>
            Sumarle el rol de {rol}
          </Button>
        )}
        <Button size="sm" variant="outline" onClick={() => alVer(pestanaDe.pestana, existente.id)}>
          Ver {existente.razon_social}
        </Button>
      </div>
    </div>
  )
}

/** Lo que cuelga de un fletero: sus choferes y sus vehículos, de sólo lectura. Se carga y se edita en su lugar
 *  (pestaña Choferes; menú Vehículos), a donde llevan los enlaces. */
function FichaDelFletero({ fleteroId }: { fleteroId: number }) {
  const [choferes, setChoferes] = useState<Maestro[] | null>(null)
  const [vehiculos, setVehiculos] = useState<Maestro[] | null>(null)
  const [falla, setFalla] = useState<string | null>(null)

  useEffect(() => {
    let vigente = true
    setChoferes(null); setVehiculos(null); setFalla(null)
    choferesDe(fleteroId).then((f) => { if (vigente) setChoferes(f) })
      .catch((e) => { if (vigente) setFalla(mensajeDeError(e)) })
    vehiculosDe(fleteroId).then((f) => { if (vigente) setVehiculos(f) })
      .catch((e) => { if (vigente) setFalla(mensajeDeError(e)) })
    return () => { vigente = false }
  }, [fleteroId])

  return (
    <section aria-label="Ficha del fletero" className="grid gap-3 rounded-md border p-3 text-sm">
      {falla && <p role="alert">{falla}</p>}
      <div>
        <h3 className="mb-1 font-medium">Choferes</h3>
        {choferes === null ? <p className="text-muted-foreground">Cargando…</p>
          : choferes.length === 0 ? <p className="text-muted-foreground">Todavía no tiene choferes.</p>
          : (
            <ul className="grid gap-1">
              {choferes.map((c) => (
                <li key={c.id} className="flex flex-wrap items-center justify-between gap-2">
                  <Link className="underline underline-offset-2"
                        to={irA.entidades('choferes', c.id)}>{String(c.nombre)}</Link>
                  <span className="text-muted-foreground">
                    {[formatearCuit(c.cuit as string | null), c.dni ? `DNI ${c.dni}` : null,
                      c.activo ? null : 'Baja'].filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
      </div>
      <div>
        <h3 className="mb-1 font-medium">Vehículos</h3>
        {vehiculos === null ? <p className="text-muted-foreground">Cargando…</p>
          : vehiculos.length === 0 ? <p className="text-muted-foreground">Todavía no tiene vehículos.</p>
          : (
            <ul className="grid gap-1">
              {vehiculos.map((v) => (
                <li key={v.id} className="flex flex-wrap items-center justify-between gap-2">
                  <Link className="underline underline-offset-2"
                        to={irA.vehiculos(v.id)}>
                    {String(v.patente_chasis ?? `Vehículo ${v.id}`)}
                  </Link>
                  <span className="text-muted-foreground">
                    {[v.patente_acoplado ? `Acoplado ${v.patente_acoplado}` : null,
                      v.activo ? null : 'Baja'].filter(Boolean).join(' · ')}
                  </span>
                </li>
              ))}
            </ul>
          )}
      </div>
    </section>
  )
}
