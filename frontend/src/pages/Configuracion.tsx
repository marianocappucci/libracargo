/** Configuración: una sola entrada en el menú, y las opciones en pestañas.
 *
 * Mismo patrón que Contalibra —la rueda en la barra lateral y las pestañas del
 * otro lado—, y por el mismo motivo: los maestros y los datos de la empresa se
 * cargan una vez y después se los toca poco. Como siete ítems de menú tenían el
 * mismo peso que las pantallas de todos los días.
 *
 * Las pestañas no son componentes de Radix: son botones. El paquete `tabs` de
 * shadcn no está instalado en este producto, y traerlo para dibujar siete
 * botones sería agregar una dependencia por una lista.
 */
import {
  Building2, MapPin, Package, Settings, Truck, Users, UserSquare,
} from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { DatosDeLaEmpresa } from '@/pages/DatosDeLaEmpresa'
import {
  Choferes, Localidades, RazonesSociales, Terceros, TiposCarga, Vehiculos,
} from '@/pages/maestros'
import { cn } from '@/lib/utils'

const PESTANAS = [
  { id: 'empresa', label: 'Empresa', icon: Settings, contenido: DatosDeLaEmpresa },
  { id: 'terceros', label: 'Terceros', icon: Users, contenido: Terceros },
  { id: 'choferes', label: 'Choferes', icon: UserSquare, contenido: Choferes },
  { id: 'vehiculos', label: 'Vehículos', icon: Truck, contenido: Vehiculos },
  { id: 'localidades', label: 'Localidades', icon: MapPin, contenido: Localidades },
  { id: 'tipos-carga', label: 'Tipos de carga', icon: Package, contenido: TiposCarga },
  { id: 'razones-sociales', label: 'Razones sociales', icon: Building2,
    contenido: RazonesSociales },
] as const

export default function Configuracion() {
  // La pestaña va en la URL: así se puede mandar el link de "cargá los
  // vehículos acá" y cae en la pestaña, no en la primera.
  const [parametros, setParametros] = useSearchParams()
  const inicial = parametros.get('seccion') ?? 'empresa'
  const [activa, setActiva] = useState(
    PESTANAS.some((p) => p.id === inicial) ? inicial : 'empresa')

  const elegir = (id: string) => {
    setActiva(id)
    setParametros(id === 'empresa' ? {} : { seccion: id }, { replace: true })
  }

  const Contenido = (PESTANAS.find((p) => p.id === activa) ?? PESTANAS[0]).contenido

  return (
    <div className="p-6">
      <h1 className="mb-4 text-2xl font-semibold">Configuración</h1>

      <div className="no-imprimir mb-6 flex flex-wrap gap-1 border-b">
        {PESTANAS.map(({ id, label, icon: Icono }) => (
          <button
            key={id} type="button" onClick={() => elegir(id)}
            aria-current={activa === id ? 'page' : undefined}
            className={cn(
              'flex items-center gap-2 rounded-t-md border-b-2 px-3 py-2 text-sm transition-colors',
              activa === id
                ? 'border-primary font-medium'
                : 'text-muted-foreground hover:text-foreground border-transparent',
            )}
          >
            <Icono className="size-4" /> {label}
          </button>
        ))}
      </div>

      {/* Cada pestaña trae su propia pantalla, con su tabla y su alta. No se
          reimplementa nada: son las mismas que ya existían. */}
      <Contenido />
    </div>
  )
}
