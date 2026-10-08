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
 *  🔴 **El emisor es uno solo: la empresa (ADR-035).** La configuración de ARCA
 *  es lo técnico —certificado, clave, punto de venta y ambiente— y sólo emite si
 *  su CUIT es el de «Datos de la empresa». Ya no hay «Razones sociales».
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
import { CarFront, MapPin, Package, Route, ShieldCheck } from 'lucide-react'
import { Navigate, useSearchParams } from 'react-router-dom'

import { EmisionRealDeCpe } from '@/components/EmisionRealDeCpe'
import { ICONOS_LC } from '@/iconos'
import { irA, SECCIONES_MUDADAS_A_ENTIDADES } from '@/navegacion'
import { FacturacionArca } from '@/pages/Arca'
import { DatosDeLaEmpresa } from '@/pages/DatosDeLaEmpresa'
import {
  Localidades, TiposCarga, Vehiculos,
} from '@/pages/maestros'
import { TarifarioDeReferencia } from '@/pages/Tarifario'

const ConfiguracionDelKit = createConfiguracion({
  // El icono que el sidebar de este producto le da a /configuracion.
  icono: ICONOS_LC.configuracion,
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
        // La tarjeta compartida (certificados) y, debajo, el interruptor de la emisión real de cartas de porte
        // (ADR-043), que sólo ven los administradores.
        contenido: (
          <div className="grid gap-6">
            <FacturacionArca />
            <EmisionRealDeCpe />
          </div>
        ),
      },
    ],
  },
  // Los maestros que quedan. Se cargan al arrancar y después se tocan poco, que es el
  // criterio por el que están en Configuración y no como ítems del menú
  // lateral con el mismo peso que las pantallas de todos los días. Terceros y Choferes ya no están:
  // son «Entidades», una entrada propia del menú (ADR-040).
  propias: [
    // `CarFront` y no `Truck`: en LibraCargo el camión es el ícono de los fleteros (catálogo de íconos de identidad, ADR-035).
    { clave: 'vehiculos', label: 'Vehículos', icono: CarFront, contenido: <Vehiculos /> },
    { clave: 'localidades', label: 'Localidades', icono: MapPin, contenido: <Localidades /> },
    { clave: 'tipos-carga', label: 'Tipos de carga', icono: Package, contenido: <TiposCarga /> },
    // `Route` y no `Ruler`/`Gauge`: es la tarifa por kilómetro. No está en el catálogo de íconos de identidad (ADR-035)
    // ni en el menú de este producto, así que no repite el dibujo de ningún concepto.
    { clave: 'tarifario', label: 'Tarifario de referencia', icono: Route, contenido: <TarifarioDeReferencia /> },
  ],
})

/** Configuración, con los enlaces viejos a Terceros y Choferes redirigidos a «Entidades» (ADR-040).
 *
 *  `/configuracion?seccion=terceros` y `?seccion=choferes` existían en marcadores, en el log y en los correos: sin la
 *  redirección el kit cae en su primera sección y quien llega no sabe adónde se fue lo que buscaba. Se conserva el
 *  resto del query (el `?ver=`), y `replace`: el enlace viejo no queda en el historial. */
export function Configuracion() {
  const [params] = useSearchParams()
  const pestana = SECCIONES_MUDADAS_A_ENTIDADES[params.get('seccion') ?? '']
  if (pestana) {
    const ver = Number(params.get('ver'))
    return <Navigate to={irA.entidades(pestana, Number.isInteger(ver) && ver > 0 ? ver : undefined)} replace />
  }
  return <ConfiguracionDelKit />
}

export default Configuracion
