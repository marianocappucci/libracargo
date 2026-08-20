/** Las seis pantallas de maestros.
 *
 * Cada una es la misma `AbmMaestro` con sus columnas y sus campos. Lo que se
 * elige acá son las columnas: **la tabla no muestra todo lo que el formulario
 * edita**, porque una tabla de quince columnas no se lee.
 */
import { sortableHeader } from 'libra-ui/data-table'

import type { Maestro } from '@/api/maestros'
import { AbmMaestro } from '@/components/AbmMaestro'

import {
  CAMPOS_CHOFER, CAMPOS_LOCALIDAD, CAMPOS_RAZON_SOCIAL, CAMPOS_TERCERO,
  CAMPOS_TIPO_CARGA, CAMPOS_VEHICULO, CONDICIONES_IVA,
} from './definiciones'

const col = (nombre: string, etiqueta: string) => ({
  accessorKey: nombre,
  header: sortableHeader(etiqueta),
})

const etiquetaIva = (v: unknown) =>
  CONDICIONES_IVA.find((c) => c.valor === v)?.etiqueta ?? ''

export function Terceros() {
  return (
    <AbmMaestro<Maestro>
      recurso="terceros"
      titulo="Terceros"
      campos={CAMPOS_TERCERO}
      columnas={[
        col('razon_social', 'Razón social'),
        col('cuit', 'CUIT'),
        col('localidad', 'Localidad'),
        {
          id: 'roles',
          header: 'Roles',
          // Los tres roles en una sola columna: son tres booleanos y tres
          // columnas de tildes ocupan el ancho de la razón social sin decir
          // más que esto.
          accessorFn: (f: Maestro) => [
            f.es_cliente ? 'Cliente' : null,
            f.es_fletero ? 'Fletero' : null,
            f.es_proveedor ? 'Proveedor' : null,
          ].filter(Boolean).join(', '),
        },
      ]}
      buscarEn={(f) => [f.razon_social as string, f.cuit as string,
                        f.localidad as string, f.contacto as string]}
      defaults={{ condicion_iva: 'consumidor_final', es_cliente: true } as Partial<Maestro>}
    />
  )
}

export function Localidades() {
  return (
    <AbmMaestro<Maestro>
      recurso="localidades"
      titulo="Localidades"
      campos={CAMPOS_LOCALIDAD}
      columnas={[col('nombre', 'Nombre'), col('provincia', 'Provincia')]}
      buscarEn={(f) => [f.nombre as string, f.provincia as string]}
    />
  )
}

export function Choferes() {
  return (
    <AbmMaestro<Maestro>
      recurso="choferes"
      titulo="Choferes"
      campos={CAMPOS_CHOFER}
      columnas={[col('nombre', 'Nombre'), col('dni', 'DNI'),
                 col('telefono', 'Teléfono')]}
      buscarEn={(f) => [f.nombre as string, f.dni as string, f.telefono as string]}
    />
  )
}

export function Vehiculos() {
  return (
    <AbmMaestro<Maestro>
      recurso="vehiculos"
      titulo="Vehículos"
      campos={CAMPOS_VEHICULO}
      columnas={[col('patente_chasis', 'Chasis'),
                 col('patente_acoplado', 'Acoplado')]}
      buscarEn={(f) => [f.patente_chasis as string, f.patente_acoplado as string]}
    />
  )
}

export function RazonesSociales() {
  return (
    <AbmMaestro<Maestro>
      recurso="razones-sociales"
      titulo="Razones sociales"
      campos={CAMPOS_RAZON_SOCIAL}
      columnas={[
        col('nombre', 'Nombre'),
        col('cuit', 'CUIT'),
        { id: 'iva', header: 'Condición de IVA',
          accessorFn: (f: Maestro) => etiquetaIva(f.condicion_iva) },
        col('punto_venta', 'Punto de venta'),
      ]}
      buscarEn={(f) => [f.nombre as string, f.cuit as string]}
      defaults={{ condicion_iva: 'responsable_inscripto', punto_venta: 1 } as Partial<Maestro>}
    />
  )
}

export function TiposCarga() {
  return (
    <AbmMaestro<Maestro>
      recurso="tipos-carga"
      titulo="Tipos de carga"
      campos={CAMPOS_TIPO_CARGA}
      columnas={[col('nombre', 'Nombre'), col('unidad_default', 'Unidad')]}
      buscarEn={(f) => [f.nombre as string, f.unidad_default as string]}
    />
  )
}
