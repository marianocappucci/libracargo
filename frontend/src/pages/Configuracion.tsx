/** Configuración de LibraCargo.
 *
 *  El armado viene de `libra-ui/Configuracion`, que desde la v0.47.0 es **la
 *  pantalla de Configuración de la familia entera** — la de Contalibra, con su
 *  barra de pestañas, la sub-navegación de Integraciones, el botón de *Backup
 *  rápido* y los tutoriales. Hasta hoy este producto dibujaba su propia barra
 *  con las mismas clases copiadas a mano: se veía casi igual, pero era otro
 *  mecanismo y divergía sin que nadie lo notara.
 *
 *  ## Dos cosas que este producto NO comparte, y por qué
 *
 *  🔴 **La tarjeta de Empresa es la suya.** Los datos de la empresa de este
 *  producto viven en una **tabla propia** (`/api/configuracion`) y tienen más
 *  campos que los ocho del `config.json` del motor: nombre de fantasía,
 *  localidad, provincia, código postal, sitio web y pie de impresión, que salen
 *  en el membrete de la orden. Usar la del kit sería perderlos.
 *
 *  🔴 **ARCA es por RAZÓN SOCIAL, y sigue siéndolo.** Una empresa de transporte
 *  factura bajo varias razones sociales, cada una con su CUIT, su punto de venta
 *  y su propio par de certificado y clave. El router del motor maneja **una sola
 *  fila** por instancia: pasarlo ahí no sería normalizar, sería borrarle la
 *  capacidad. Es el mismo caso que Contalibra, que también es multi-empresa.
 *
 *  Su pantalla, además, ya hace lo que la del motor vino a traerle al resto:
 *  sube el certificado y la clave, y dice cuándo vence. Entra como una
 *  integración propia —que es lo que es— y no como pestaña de primer nivel.
 *
 *  ## Lo que sí gana
 *
 *  La pestaña de **Correo (SMTP)**, que este producto no tenía aunque su router
 *  estaba montado desde siempre: el SMTP sólo entraba por el backoffice de la
 *  suite. Con el tutorial de la contraseña de aplicación de Gmail.
 */
import { createConfiguracion } from 'libra-ui/Configuracion'
import {
  Building2, MapPin, Package, Settings, ShieldCheck, Truck, Users, UserSquare,
} from 'lucide-react'

import { FacturacionArca } from '@/pages/Arca'
import { DatosDeLaEmpresa } from '@/pages/DatosDeLaEmpresa'
import {
  Choferes, Localidades, RazonesSociales, Terceros, TiposCarga, Vehiculos,
} from '@/pages/maestros'

export const Configuracion = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: Settings,
  // Sale en el tutorial de Gmail —es el nombre que hay que ponerle a la
  // contraseña de aplicación— y en el de Padrón A13.
  producto: 'LibraCargo',
  // Ver el docstring: la tarjeta es la propia, pero la pestaña sigue siendo la
  // PRIMERA, como en los otros siete.
  empresa: { contenido: <DatosDeLaEmpresa /> },
  integraciones: {
    email: true,
    extra: [
      // Va acá y no como pestaña de primer nivel porque es exactamente eso:
      // con qué otro sistema habla este producto.
      {
        clave: 'arca', label: 'ARCA / AFIP', icono: ShieldCheck,
        contenido: <FacturacionArca />,
      },
    ],
  },
  // Los maestros. Se cargan al arrancar y después se tocan poco, que es el
  // criterio por el que están en Configuración y no como siete ítems del menú
  // lateral con el mismo peso que las pantallas de todos los días.
  propias: [
    { clave: 'terceros', label: 'Terceros', icono: Users, contenido: <Terceros /> },
    { clave: 'choferes', label: 'Choferes', icono: UserSquare, contenido: <Choferes /> },
    { clave: 'vehiculos', label: 'Vehículos', icono: Truck, contenido: <Vehiculos /> },
    { clave: 'localidades', label: 'Localidades', icono: MapPin, contenido: <Localidades /> },
    { clave: 'tipos-carga', label: 'Tipos de carga', icono: Package, contenido: <TiposCarga /> },
    // Última de los maestros y no primera: el certificado de ARCA es de un
    // CUIT, y el CUIT lo pone la razón social. Configurar ARCA sin razones
    // sociales cargadas no tiene por dónde empezar.
    {
      clave: 'razones-sociales', label: 'Razones sociales', icono: Building2,
      contenido: <RazonesSociales />,
    },
  ],
})

export default Configuracion
