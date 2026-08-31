import { api } from 'libra-ui/api-client'

/** Configuración de ARCA por razón social.
 *
 *  🔑 **Nada de acá trae el certificado ni la clave**: el backend devuelve
 *  datos *sobre* los archivos —quién los emitió, cuándo vencen, si son
 *  pareja— y nunca su contenido. La clave privada no sale de la base.
 */

export type Ambiente = 'homologacion' | 'produccion'

export type Certificado = {
  nombre: string | null
  sujeto: string
  emisor: string
  vence: string | null
  vencido: boolean
  dias_para_vencer: number
}

export type ConfiguracionArca = {
  razon_social_id: number
  razon_social: string
  cuit: string | null
  punto_venta: number
  ambiente: Ambiente
  habilitado: boolean
  certificado: Certificado | null
  tiene_clave: boolean
  clave_nombre: string | null
  /** `null` mientras falte alguna de las dos mitades. */
  coinciden: boolean | null
}

/** `postForm` y no `post`: `post` serializa el cuerpo a JSON, y un `FormData`
 *  ahi se convierte en `{}` — la subida llegaria vacia y el error hablaria de
 *  un archivo faltante en vez de del envio. */
function subir(ruta: string, archivo: File): Promise<ConfiguracionArca> {
  const cuerpo = new FormData()
  cuerpo.append('archivo', archivo)
  return api.postForm<ConfiguracionArca>(ruta, cuerpo)
}

/** El resultado de *Probar conexión*.
 *
 *  🔑 **No trae el token ni la firma que devuelve WSAA.** Son credenciales de
 *  sesión de ARCA; el backend las usa y las descarta, y no salen por la API.
 */
export type PruebaArca = {
  ok: boolean
  ambiente: Ambiente
  cuit: string | null
  /** El webservice contra el que se probó — el mismo que usa la emisión. */
  servicio: string
  /** Hasta cuándo vale el ticket de acceso, tal como lo manda ARCA. */
  expira: string | null
}

export const arca = {
  listar: () => api.get<ConfiguracionArca[]>('/api/arca'),
  guardar: (razonSocialId: number, datos: { ambiente: Ambiente; habilitado: boolean }) =>
    api.put<ConfiguracionArca>(`/api/arca/${razonSocialId}`, datos),
  subirCertificado: (razonSocialId: number, archivo: File) =>
    subir(`/api/arca/${razonSocialId}/certificado`, archivo),
  subirClave: (razonSocialId: number, archivo: File) =>
    subir(`/api/arca/${razonSocialId}/clave`, archivo),
  borrarCredenciales: (razonSocialId: number) =>
    api.del<ConfiguracionArca>(`/api/arca/${razonSocialId}/credenciales`),
  /** Autentica de verdad contra ARCA. Es lo único que dice que el organismo
   *  acepta el certificado: leer los archivos no lo puede contestar. */
  probar: (razonSocialId: number) =>
    api.post<PruebaArca>(`/api/arca/${razonSocialId}/probar`),
}
