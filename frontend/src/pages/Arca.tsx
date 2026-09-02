/** Facturación electrónica: las credenciales de ARCA de esta instancia.
 *
 *  Hasta el 2026-09-02 esta pantalla era propia y listaba **una fila por razón
 *  social**, con el certificado y la clave guardados en columnas de la base.
 *  Ahora es la tarjeta compartida de `libra-ui`, apuntada al router del motor:
 *  la misma que ven los otros siete productos de la familia.
 *
 *  🔑 **Lo que se gana no es dejar de mantener un formulario: son los DOS
 *  pares.** El certificado de homologación y el de producción son dos archivos
 *  distintos del mismo CUIT, y con un solo par guardado probar con el cliente
 *  obligaba a **pisar** el que después tiene que quedar bien. La tarjeta
 *  compartida muestra los dos, cada uno con su vencimiento, y `ambiente` pasa a
 *  ser el selector de cuál se usa para emitir.
 *
 *  ⚠️ **Y lo que se pierde es la lista por razón social.** El motor guarda una
 *  configuración por instancia y sus archivos van a un nombre fijo dentro de
 *  `CERTS_DIR`, sin la empresa adentro: dos razones sociales se pisarían el
 *  certificado entre sí. Mientras eso siga así, factura **una sola**, y cuál es
 *  lo dice el CUIT — el del certificado tiene que ser el de la razón social.
 *  La regla vive en `app/servicios/emision_arca.py`, que es el camino que hace
 *  daño; acá sólo se configura.
 *
 *  El prefijo es `/api/arca`, el que este producto ya publicó. `basePath` es
 *  parámetro del kit justamente porque cambiarlo rompe el frontend desplegado.
 */
import { ArcaCard } from 'libra-ui/Configuracion'

/** El slug con el que se crea la fila de `arca_config`.
 *
 *  Tiene que decir lo mismo que `EMPRESA_ARCA` en
 *  `app/servicios/emision_arca.py`. **Que se desincronicen no rompe la
 *  emisión**, y eso es deliberado: el servicio resuelve la fila activa y no
 *  busca por slug, justamente para que un literal de más en el frontend no
 *  pueda producir la falla muda que documenta `build_arca_router` —pantalla
 *  que dice "Guardado" y facturación que dice "ARCA no está configurado"—.
 *  Hay un test que lo fija.
 */
const EMPRESA = 'agencia'

export function FacturacionArca() {
  return <ArcaCard producto="LibraCargo" basePath="/api/arca" empresa={EMPRESA} />
}

export default FacturacionArca
