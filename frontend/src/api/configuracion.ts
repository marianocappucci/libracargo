import { api } from 'libra-ui/api-client'
import { useEffect, useState } from 'react'

export type Configuracion = {
  razon_social: string
  nombre_fantasia: string | null
  cuit: string | null
  condicion_iva: string | null
  ingresos_brutos: string | null
  inicio_actividades: string | null
  domicilio: string | null
  localidad: string | null
  provincia: string | null
  codigo_postal: string | null
  telefono: string | null
  email: string | null
  sitio_web: string | null
  pie_de_impresion: string | null
  /** El logo NO viaja acá: se pide por `/api/configuracion/logo`. La barra
   *  lateral pide esto en cada carga, y la imagen entera de regalo sería. */
  tiene_logo: boolean
}

export const VACIA: Configuracion = {
  razon_social: '', nombre_fantasia: null, cuit: null, condicion_iva: null,
  ingresos_brutos: null, inicio_actividades: null, domicilio: null, localidad: null,
  provincia: null, codigo_postal: null, telefono: null, email: null, sitio_web: null,
  pie_de_impresion: null, tiene_logo: false,
}

export const configuracion = {
  ver: () => api.get<Configuracion>('/api/configuracion'),
  guardar: (datos: unknown) => api.put<Configuracion>('/api/configuracion', datos),
  borrarLogo: () => api.del<Configuracion>('/api/configuracion/logo'),
  async subirLogo(archivo: File): Promise<Configuracion> {
    // `fetch` directo y no el cliente de `libra-ui`: éste manda JSON, y una
    // imagen va como multipart. `credentials: 'include'` porque la sesión es una
    // cookie y sin eso el navegador no la manda.
    const cuerpo = new FormData()
    cuerpo.append('archivo', archivo)
    const r = await fetch('/api/configuracion/logo', {
      method: 'POST', body: cuerpo, credentials: 'include',
    })
    if (!r.ok) {
      const detalle = await r.json().catch(() => ({ detail: 'no se pudo subir el logo' }))
      throw new Error(typeof detalle.detail === 'string' ? detalle.detail : 'no se pudo subir')
    }
    return r.json()
  },
}

/** La URL del logo, con una marca que cambia al guardarlo.
 *
 * Sin la marca, el navegador sigue mostrando el logo anterior después de
 * cambiarlo —misma URL, misma imagen en caché— y quien lo subió cree que no se
 * guardó. */
export function urlDelLogo(version = 0): string {
  return `/api/configuracion/logo?v=${version}`
}

//: Se guarda entre montajes: la barra lateral se dibuja en cada navegación y
//: pedir la configuración cada vez es una consulta por click.
let cache: Configuracion | null = null
const suscriptos = new Set<(c: Configuracion) => void>()

export function recordarConfiguracion(nueva: Configuracion) {
  cache = nueva
  suscriptos.forEach((avisar) => avisar(nueva))
}

/** La configuración de la empresa, para cualquier pantalla que la necesite. */
export function useConfiguracion(): Configuracion {
  const [valor, setValor] = useState<Configuracion>(cache ?? VACIA)

  useEffect(() => {
    suscriptos.add(setValor)
    if (cache === null) {
      configuracion.ver()
        .then(recordarConfiguracion)
        // Un fallo acá no puede romper la pantalla: sin configuración se muestra
        // el producto sin el nombre de la empresa, que es exactamente lo que
        // pasaba antes de que existiera.
        .catch(() => undefined)
    }
    return () => { suscriptos.delete(setValor) }
  }, [])

  return valor
}
