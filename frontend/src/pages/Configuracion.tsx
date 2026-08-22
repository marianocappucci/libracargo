/** Configuración: una sola entrada en el menú, y las opciones en pestañas.
 *
 * Mismo patrón que Contalibra —la rueda en la barra lateral y las pestañas del
 * otro lado—, y por el mismo motivo: los maestros y los datos de la empresa se
 * cargan una vez y después se los toca poco. Como siete ítems de menú tenían el
 * mismo peso que las pantallas de todos los días.
 *
 * ## 2026-08-22 — las pestañas son las de shadcn, iguales a las de Contalibra
 *
 * Hasta hoy eran botones a mano con un subrayado, y el motivo escrito acá era
 * *"el paquete `tabs` de shadcn no está instalado en este producto, y traerlo
 * para dibujar siete botones sería agregar una dependencia por una lista"*.
 *
 * Venció por los dos lados. El humano pidió que las pestañas se vean como las
 * de Contalibra —que son este primitivo— y además el paquete **hay que
 * instalarlo igual**: desde `libra-ui` v0.35.0, el módulo `Configuracion` del
 * kit importa `@/components/ui/tabs`, y este archivo consume `DatosBackupCard`
 * de ahí. Sin vendorizarlo, el build no compila.
 */
import { DatosBackupCard } from 'libra-ui/Configuracion'
import {
  Building2, Database, MapPin, Package, Settings, ShieldCheck, Truck, Users,
  UserSquare,
} from 'lucide-react'
import { useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { FacturacionArca } from '@/pages/Arca'
import { DatosDeLaEmpresa } from '@/pages/DatosDeLaEmpresa'
import {
  Choferes, Localidades, RazonesSociales, Terceros, TiposCarga, Vehiculos,
} from '@/pages/maestros'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TituloPantalla } from 'libra-ui/titulo-pantalla'

const PESTANAS = [
  { id: 'empresa', label: 'Empresa', icon: Settings, contenido: DatosDeLaEmpresa },
  { id: 'terceros', label: 'Terceros', icon: Users, contenido: Terceros },
  { id: 'choferes', label: 'Choferes', icon: UserSquare, contenido: Choferes },
  { id: 'vehiculos', label: 'Vehículos', icon: Truck, contenido: Vehiculos },
  { id: 'localidades', label: 'Localidades', icon: MapPin, contenido: Localidades },
  { id: 'tipos-carga', label: 'Tipos de carga', icon: Package, contenido: TiposCarga },
  { id: 'razones-sociales', label: 'Razones sociales', icon: Building2,
    contenido: RazonesSociales },
  // Va después de razones sociales y no antes: el certificado de ARCA es de
  // un CUIT, y el CUIT lo pone la razón social. Configurar ARCA sin razones
  // sociales cargadas no tiene por dónde empezar.
  { id: 'arca', label: 'Facturación (ARCA)', icon: ShieldCheck,
    contenido: FacturacionArca },
  // La pantalla es la compartida de `libra-ui`, la misma que ven los otros
  // seis productos. Lo único de este producto es el gate de rol, que lo pone
  // el backend.
  { id: 'datos', label: 'Datos / Backup', icon: Database,
    contenido: DatosBackupCard },
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
      <TituloPantalla icono={Settings} className="mb-4">Configuración</TituloPantalla>

      {/* La barra separada del contenido por una línea, igual que la
          Configuración de Contalibra. `value` y no `defaultValue`: la pestaña
          activa la manda `?seccion=`, así que el conmutador es controlado —
          con `defaultValue` entrar por un link a otra sección pintaría la
          primera y mostraría el contenido de otra. */}
      <div className="no-imprimir mb-6 border-b pb-2">
        <Tabs value={activa} onValueChange={elegir}>
          <TabsList>
            {PESTANAS.map(({ id, label, icon: Icono }) => (
              <TabsTrigger key={id} value={id}><Icono />{label}</TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      {/* Cada pestaña trae su propia pantalla, con su tabla y su alta. No se
          reimplementa nada: son las mismas que ya existían. */}
      <Contenido />
    </div>
  )
}
