/** Las pantallas de maestros que no son terceros.
 *
 * Los terceros (clientes, fleteros y proveedores) viven en «Clientes», «Proveedores» y «Transporte» (`TercerosPorRol`, ADR-040 y ADR-045), y los
 * choferes son una pestaña de «Transporte». Los vehículos son otra pestaña de «Transporte»; las localidades y los tipos de
 * carga quedan en Configuración.
 *
 * Cada una es la misma `AbmMaestro` con sus columnas y sus campos. Lo que se
 * elige acá son las columnas: **la tabla no muestra todo lo que el formulario
 * edita**, porque una tabla de quince columnas no se lee.
 */
import { sortableHeader } from 'libra-ui/data-table'

import { formatearCuit } from '@/api/cartas-porte'
import type { Maestro } from '@/api/maestros'
import { AbmMaestro } from '@/components/AbmMaestro'

import {
  CAMPOS_CHOFER, CAMPOS_TIPO_CARGA, CAMPOS_VEHICULO, conFleteros,
} from './definiciones'
import { useFichaEnLaUrl, useFleteros } from './hooks'

const col = (nombre: string, etiqueta: string) => ({
  accessorKey: nombre,
  header: sortableHeader(etiqueta),
})

// Configuración → Localidades vive aparte: es la única con catálogo, parajes y acciones propias (ADR-041).
export { Localidades } from './Localidades'

export function Choferes({ encabezado = true }: { encabezado?: boolean }) {
  const fleteros = useFleteros()
  const ficha = useFichaEnLaUrl()
  const fletero = (id: unknown) => fleteros.find((f) => f.id === id)?.razon_social ?? ''
  return (
    <AbmMaestro<Maestro>
      recurso="choferes"
      titulo="Choferes"
      singular="chofer"
      encabezado={encabezado}
      campos={conFleteros(CAMPOS_CHOFER, fleteros)}
      columnas={[col('nombre', 'Nombre'),
                 // Se guarda en once dígitos; en la tabla se lee con guiones.
                 { id: 'cuit', header: sortableHeader('CUIT'),
                   accessorFn: (f: Maestro) => formatearCuit(f.cuit as string | null) },
                 col('dni', 'DNI'),
                 col('telefono', 'Teléfono'),
                 // El fletero para el que maneja: sale del listado de fleteros, no de la fila.
                 { id: 'fletero', header: sortableHeader('Fletero'),
                   accessorFn: (f: Maestro) => fletero(f.fletero_id) }]}
      buscarEn={(f) => [f.nombre as string, f.dni as string, f.cuit as string,
                        formatearCuit(f.cuit as string | null), f.telefono as string,
                        fletero(f.fletero_id)]}
      {...ficha}
    />
  )
}

export function Vehiculos({ encabezado = true }: { encabezado?: boolean }) {
  const fleteros = useFleteros()
  const ficha = useFichaEnLaUrl()
  const fletero = (id: unknown) => fleteros.find((f) => f.id === id)?.razon_social ?? ''
  return (
    <AbmMaestro<Maestro>
      recurso="vehiculos"
      titulo="Vehículos"
      encabezado={encabezado}
      campos={conFleteros(CAMPOS_VEHICULO, fleteros)}
      columnas={[col('patente_chasis', 'Chasis'),
                 col('patente_acoplado', 'Acoplado'),
                 { id: 'fletero', header: sortableHeader('Fletero'),
                   accessorFn: (f: Maestro) => fletero(f.fletero_id) }]}
      buscarEn={(f) => [f.patente_chasis as string, f.patente_acoplado as string,
                        fletero(f.fletero_id)]}
      {...ficha}
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
