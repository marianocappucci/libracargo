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
  BarChart3, BookOpen, ClipboardList, LayoutDashboard, Receipt, ScrollText,
  Settings, UserCog, Wallet,
} from 'lucide-react'

import { useConfiguracion } from '@/api/configuracion'
import { LOGO, WORDMARK } from '@/branding'
import { useAuth } from '@/context/AuthContext'

type Usuario = { role?: string; name?: string; empresa?: string }

/** La sesion, mas el nombre de la empresa.
 *
 * `createLayout` recibe un `useAuth` y le pide el usuario: agregandole ahi la
 * empresa, el encabezado se actualiza solo cuando la configuracion carga o
 * cambia, sin que el Layout tenga que saber de donde salio.
 */
function useAuthConEmpresa() {
  const sesion = useAuth() as { user: Usuario | null; logout: () => Promise<void> }
  const empresa = useConfiguracion()
  return {
    ...sesion,
    user: sesion.user
      ? { ...sesion.user, empresa: empresa.nombre_fantasia || empresa.razon_social }
      : null,
  }
}

export const Layout = createLayout<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  // El fallback del motor, dos escalones abajo del logo: `logo` reemplaza el
  // hueco entero, `icon` incluido.
  icon: LayoutDashboard,
  // Las clases salen de `@/branding`, el mismo archivo que usa el login: es lo
  // que garantiza que las dos pantallas escriban "LibraCargo" igual.
  //
  // El override de colapsado NO es decorativo: con la sidebar en modo icono el
  // ancho util son 32 px y sin bajarlo el logo de 36 se sale de la barra.
  logo: {
    src: LOGO,
    className: 'h-9 w-9 group-data-[collapsible=icon]:h-8 group-data-[collapsible=icon]:w-8',
  },
  // 🔴 El interlineado va PEGADO al tamano (`/[21px]`) y no como `leading-*`
  // aparte: en Tailwind v4 una utilidad de tamano emite tambien `line-height`,
  // asi que el `leading-none` que libra-ui pone por defecto perderia contra
  // este `text-[15px]`. 21 = 36 (el alto del logo) menos los 15 de la empresa.
  wordmarkClassName: `${WORDMARK} text-[15px]/[21px]`,
  homeTo: '/',
  navSections: [
    {
      items: [
        { to: '/', label: 'Inicio', icon: LayoutDashboard },
        { to: '/ordenes', label: 'Órdenes de carga', icon: ClipboardList },
        { to: '/cuentas', label: 'Cuenta corriente', icon: BookOpen },
        { to: '/caja', label: 'Caja', icon: Wallet },
        { to: '/comprobantes', label: 'Comprobantes', icon: Receipt },
        { to: '/reportes', label: 'Reportes', icon: BarChart3 },
      ],
    },
    {
      // Una sola entrada, como en Contalibra: la rueda en la barra y las
      // opciones en pestañas del otro lado. Los maestros y los datos de la
      // empresa se cargan una vez y despues se los toca poco; como siete items
      // de menu tenian el mismo peso que las pantallas de todos los dias.
      items: [
        { to: '/configuracion', label: 'Configuración', icon: Settings },
      ],
    },
    {
      label: 'Administración',
      items: [
        // : el router del backend exige rol admin, asi que a un
        // operador el link le daria 403. Un menu que ofrece lo que no se puede
        // usar es peor que no ofrecerlo.
        { to: '/usuarios', label: 'Usuarios', icon: UserCog, adminOnly: true },
        // Junto a Usuarios: se mira para responder "quién hizo esto", que es
        // una pregunta de administración y no de operación.
        { to: '/logs', label: 'Log de actividad', icon: ScrollText, adminOnly: true },
      ],
    },
  ],
  getUserName: (u) => u.name ?? '',
  // El nombre de la empresa, debajo del producto. `libra-ui` lo dibuja con
  // `getUserSubtitle`; en el resto de la familia viene en el usuario, y acá sale
  // de la configuracion de la instancia — que es donde el cliente la edita.
  getUserSubtitle: (u) => u.empresa || undefined,
  useAuth: useAuthConEmpresa,
})

export default Layout
