// Shim sobre libra-ui/Layout: branding y navegación propios de LibraCargo.
//
// Maestros llegó con F2, las órdenes con F3, cuentas y caja con F4, y los
// comprobantes con F5. Cada pantalla entra al menú cuando existe: un link a una
// que no está es peor que la ausencia del link.
//
// Dos ítems del mismo menú no comparten dibujo — si no, el icono deja de
// distinguir y hay que leer el texto igual.
import { createLayout } from 'libra-ui/Layout'
import {
  Building2, ClipboardList, LayoutDashboard, MapPin, Package, Truck, Users,
  UserSquare, Wallet, BookOpen, Receipt, UserCog,
} from 'lucide-react'

import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string }

export const Layout = createLayout<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  icon: LayoutDashboard,
  homeTo: '/',
  navSections: [
    {
      items: [
        { to: '/', label: 'Inicio', icon: LayoutDashboard },
        { to: '/ordenes', label: 'Órdenes de carga', icon: ClipboardList },
        { to: '/cuentas', label: 'Cuenta corriente', icon: BookOpen },
        { to: '/caja', label: 'Caja', icon: Wallet },
        { to: '/comprobantes', label: 'Comprobantes', icon: Receipt },
      ],
    },
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
    {
      label: 'Administración',
      items: [
        // : el router del backend exige rol admin, asi que a un
        // operador el link le daria 403. Un menu que ofrece lo que no se puede
        // usar es peor que no ofrecerlo.
        { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
      ],
    },
  ],
  getUserName: (u) => u.name ?? '',
  useAuth,
})

export default Layout
