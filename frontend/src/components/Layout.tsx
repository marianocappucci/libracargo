// Shim sobre libra-ui/Layout: branding y navegación propios de LibraCargo.
//
// Los maestros llegaron con F2. Órdenes, cuentas y comprobantes son F3..F5 y
// **no están en el menú**: un link a una pantalla que no existe es peor que la
// ausencia del link.
//
// Dos ítems del mismo menú no comparten dibujo — si no, el icono deja de
// distinguir y hay que leer el texto igual.
import { createLayout } from 'libra-ui/Layout'
import {
  Building2, LayoutDashboard, MapPin, Package, Truck, Users, UserSquare,
} from 'lucide-react'

import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string }

export const Layout = createLayout<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  icon: LayoutDashboard,
  homeTo: '/',
  navSections: [
    { items: [{ to: '/', label: 'Inicio', icon: LayoutDashboard }] },
    {
      label: 'Maestros',
      items: [
        { to: '/terceros', label: 'Terceros', icon: Users },
        { to: '/choferes', label: 'Choferes', icon: UserSquare },
        { to: '/vehiculos', label: 'Vehículos', icon: Truck },
        { to: '/localidades', label: 'Localidades', icon: MapPin },
        { to: '/tipos-carga', label: 'Tipos de carga', icon: Package },
        { to: '/razones-sociales', label: 'Razones sociales', icon: Building2 },
      ],
    },
  ],
  getUserName: (u) => u.name ?? '',
  useAuth,
})

export default Layout
