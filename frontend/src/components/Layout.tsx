// Shim sobre libra-ui/Layout: branding y navegación propios de LibraCargo.
//
// El menú tiene un solo ítem a propósito. Maestros, órdenes, cuentas y
// comprobantes llegan con F2..F5; poner sus links ahora sería ofrecer rutas
// que no llevan a ninguna pantalla.
import { createLayout } from 'libra-ui/Layout'
import { LayoutDashboard } from 'lucide-react'

import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string }

export const Layout = createLayout<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  icon: LayoutDashboard,
  homeTo: '/',
  navSections: [{ items: [{ to: '/', label: 'Inicio', icon: LayoutDashboard }] }],
  getUserName: (u) => u.name ?? '',
  useAuth,
})

export default Layout
