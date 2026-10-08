// Shim sobre libra-ui/Layout: branding y navegación propios de LibraCargo.
//
// Maestros llegó con F2, las órdenes con F3, cuentas y caja con F4, y los
// comprobantes con F5. Cada pantalla entra al menú cuando existe: un link a una
// que no está es peor que la ausencia del link.
//
// Dos ítems del mismo menú no comparten dibujo — si no, el icono deja de
// distinguir y hay que leer el texto igual.
import { createLayout, type NavSection } from 'libra-ui/Layout'
import { INDICADORES } from 'libra-ui/iconos-indicador'
import { Building2, ClipboardList } from 'lucide-react'

import { useConfiguracion } from '@/api/configuracion'
import { WORDMARK } from '@/branding'
import { useAuth } from '@/context/AuthContext'
import { ICONOS_LC } from '@/iconos'
import { RUTAS_DE_COMPROBANTES } from '@/navegacion'

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

/** Las secciones del menu, afuera para que un test pueda afirmarlas sin
 *  montar el layout entero. */
export const NAV_SECCIONES: NavSection<Usuario>[] = [
    {
      items: [
        // 'Dashboard' y no 'Inicio': es como se llama en Gestiolibra,
        // Contalibra, Restolibra, MedLibra y LibraDesk. Este producto era
        // el unico de la familia que le decia distinto.
        { to: '/', label: 'Dashboard', icon: ICONOS_LC.dashboard },
        { to: '/ordenes', label: 'Órdenes de carga', icon: ClipboardList },
        // Ahora sale del catálogo de íconos de indicadores del kit (`libra-ui/iconos-indicador`, ADR-038): `cartasDePorte` es `FileBadge`,
        // el mismo dibujo que lleva en los reportes y en el título de su pantalla. Se escribe `INDICADORES.cartasDePorte` y no
        // `iconoDelIndicador(…)` porque es la forma que lee el guard de títulos (`auditarTitulos`).
        { to: '/cartas-porte', label: 'Cartas de porte', icon: INDICADORES.cartasDePorte },
        // Clientes, Fleteros, Choferes y Proveedores en una entrada con pestañas (ADR-040). Propia de este producto, como Órdenes:
        // «Entidades» no es un concepto del catálogo de la familia, y `Building2` es un dibujo que ningún concepto usa.
        { to: '/entidades', label: 'Entidades', icon: Building2 },
        { to: '/cuentas', label: 'Cuenta corriente', icon: ICONOS_LC.cuentaCorriente },
        { to: '/caja', label: 'Caja', icon: ICONOS_LC.caja },
        // Una sola entrada para todo lo que es un comprobante, con dos pestañas
        // (Clientes y Proveedores). «Pre facturas» y «Comprobantes de
        // proveedores» eran dos entradas sueltas; ahora son accesos y una
        // pestaña de ésta. `activoEn` (libra-ui 0.119.0) la marca en esas rutas.
        { to: '/comprobantes', label: 'Comprobantes', icon: ICONOS_LC.comprobantes, activoEn: RUTAS_DE_COMPROBANTES },
        { to: '/reportes', label: 'Reportes', icon: ICONOS_LC.reportes },
      ],
    },
    {
      // Una sola entrada, como en Contalibra: la rueda en la barra y las
      // opciones en pestañas del otro lado. Los maestros y los datos de la
      // empresa se cargan una vez y despues se los toca poco; como siete items
      // de menu tenian el mismo peso que las pantallas de todos los dias.
      items: [
        { to: '/configuracion', label: 'Configuración', icon: ICONOS_LC.configuracion },
      ],
    },
    {
      label: 'Administración',
      items: [
        // : el router del backend exige rol admin, asi que a un
        // operador el link le daria 403. Un menu que ofrece lo que no se puede
        // usar es peor que no ofrecerlo.
        { to: '/usuarios', label: 'Usuarios', icon: ICONOS_LC.usuarios, adminOnly: true },
        // Junto a Usuarios: se mira para responder "quién hizo esto", que es
        // una pregunta de administración y no de operación.
        { to: '/logs', label: 'Log de actividad', icon: ICONOS_LC.logDeActividad, adminOnly: true },
      ],
    },
]

export const Layout = createLayout<Usuario>({
  productName: 'LibraCargo',
  productInitial: 'C',
  // El fallback del motor, tres escalones abajo de `producto`: la marca de
  // `producto` reemplaza el hueco entero, `icon` incluido.
  icon: ICONOS_LC.dashboard,
  // La marca (el icono de LibraCargo sobre un cuadrado de su color, libra-ui ADR-033). Las clases del nombre salen de `@/branding`, el mismo
  // archivo que usa el login: es lo que garantiza que las dos pantallas escriban "LibraCargo" igual.
  // `MarcaProducto` ya viene con `h-8 w-8 shrink-0`, que es lo que cabe en la sidebar colapsada (32 px): no hace falta ningun override.
  producto: 'libracargo',
  // 🔴 El interlineado va PEGADO al tamano (`/[17px]`) y no como `leading-*`
  // aparte: en Tailwind v4 una utilidad de tamano emite tambien `line-height`,
  // asi que el `leading-none` que libra-ui pone por defecto perderia contra
  // este `text-[15px]`. 17 = 32 (el alto de la marca) menos los 15 de la empresa.
  wordmarkClassName: `${WORDMARK} text-[15px]/[17px]`,
  homeTo: '/',
  navSections: NAV_SECCIONES,
  getUserName: (u) => u.name ?? '',
  // El nombre de la empresa, debajo del producto. `libra-ui` lo dibuja con
  // `getUserSubtitle`; en el resto de la familia viene en el usuario, y acá sale
  // de la configuracion de la instancia — que es donde el cliente la edita.
  getUserSubtitle: (u) => u.empresa || undefined,
  useAuth: useAuthConEmpresa,
})

export default Layout
