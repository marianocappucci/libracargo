/** Los datos de la empresa: lo que sale impreso en cada papel.
 *
 * Es una pestaña de Configuración, no una pantalla suelta: por eso no lleva
 * título propio — el de la página lo pone `Configuracion`.
 *
 * Es de la instancia, no del despliegue: por eso vive en la base y no en el
 * `.env`. El cliente cambia su teléfono sin que nadie redespliegue nada.
 */
import { Trash2, Upload } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { Configuracion as Datos } from '@/api/configuracion'
import { VACIA, configuracion, recordarConfiguracion, urlDelLogo } from '@/api/configuracion'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const CAMPOS: [keyof Datos, string][] = [
  ['razon_social', 'Razón social'],
  ['nombre_fantasia', 'Nombre de fantasía'],
  ['cuit', 'CUIT'],
  ['condicion_iva', 'Condición frente al IVA'],
  ['ingresos_brutos', 'Ingresos brutos'],
  ['inicio_actividades', 'Inicio de actividades'],
  ['domicilio', 'Domicilio'],
  ['localidad', 'Localidad'],
  ['provincia', 'Provincia'],
  ['codigo_postal', 'Código postal'],
  ['telefono', 'Teléfono'],
  ['email', 'Correo'],
  ['sitio_web', 'Sitio web'],
]

export function DatosDeLaEmpresa() {
  const [datos, setDatos] = useState<Datos>(VACIA)
  const [version, setVersion] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [aviso, setAviso] = useState<string | null>(null)
  const [guardando, setGuardando] = useState(false)

  useEffect(() => {
    configuracion.ver().then(setDatos).catch((e) => setError(mensajeDeError(e)))
  }, [])

  const set = (c: Partial<Datos>) => setDatos((d) => ({ ...d, ...c }))

  async function guardar() {
    setError(null); setAviso(null); setGuardando(true)
    try {
      const { tiene_logo: _, ...cuerpo } = datos
      const nueva = await configuracion.guardar(cuerpo)
      setDatos(nueva)
      // La barra lateral muestra el nombre de la empresa: sin avisarle, sigue
      // mostrando el anterior hasta recargar la página.
      recordarConfiguracion(nueva)
      setAviso('Guardado.')
    } catch (e) {
      setError(mensajeDeError(e))
    } finally {
      setGuardando(false)
    }
  }

  async function subirLogo(archivo: File | undefined) {
    if (!archivo) return
    setError(null); setAviso(null)
    try {
      const nueva = await configuracion.subirLogo(archivo)
      setDatos(nueva)
      recordarConfiguracion(nueva)
      // La marca cambia para que el navegador no siga mostrando el logo viejo.
      setVersion((v) => v + 1)
      setAviso('Logo actualizado.')
    } catch (e) {
      setError(e instanceof Error ? e.message : mensajeDeError(e))
    }
  }

  return (
    <div>
      <p className="text-muted-foreground max-w-2xl text-sm">
        Es lo que aparece en el encabezado de las órdenes de carga y los
        comprobantes impresos, y el nombre que se ve debajo de LibraCargo en el
        menú.
      </p>

      {error && (
        <p role="alert" className="mt-4 rounded border border-destructive/40 p-3 text-sm">
          {error}
        </p>
      )}
      {aviso && <p className="text-muted-foreground mt-4 text-sm">{aviso}</p>}

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        {CAMPOS.map(([campo, etiqueta]) => (
          <div key={campo} className="grid gap-1">
            <Label htmlFor={`c-${campo}`}>{etiqueta}</Label>
            <Input id={`c-${campo}`} value={String(datos[campo] ?? '')}
                   onChange={(e) => set({ [campo]: e.target.value } as Partial<Datos>)} />
          </div>
        ))}
      </div>

      <div className="mt-4 grid gap-1">
        <Label htmlFor="c-pie">Pie de los papeles impresos</Label>
        <textarea id="c-pie" rows={3}
                  className="w-full min-w-0 rounded-md border p-2 text-sm"
                  value={datos.pie_de_impresion ?? ''}
                  onChange={(e) => set({ pie_de_impresion: e.target.value })} />
        <p className="text-muted-foreground text-xs">
          Condiciones, aclaraciones, lo que tenga que decir cada papel abajo de todo.
        </p>
      </div>

      <div className="mt-6">
        <h2 className="font-semibold">Logo</h2>
        <p className="text-muted-foreground text-sm">
          Va arriba a la izquierda en cada impresión. PNG, JPG o WebP, hasta 2 MB.
        </p>
        <div className="mt-3 flex items-center gap-4">
          {datos.tiene_logo ? (
            <img src={urlDelLogo(version)} alt="Logo de la empresa"
                 className="max-h-20 max-w-48 rounded border object-contain p-1" />
          ) : (
            <div className="text-muted-foreground rounded border border-dashed p-4 text-sm">
              Todavía no hay logo
            </div>
          )}
          <div className="flex flex-col gap-2">
            <Label htmlFor="c-logo" className="sr-only">Subir logo</Label>
            <Button asChild variant="outline">
              <label htmlFor="c-logo" className="cursor-pointer">
                <Upload className="size-4" /> Subir logo
                <input id="c-logo" type="file" className="hidden"
                       accept="image/png,image/jpeg,image/webp"
                       onChange={(e) => subirLogo(e.target.files?.[0])} />
              </label>
            </Button>
            {datos.tiene_logo && (
              <Button variant="ghost" onClick={async () => {
                const nueva = await configuracion.borrarLogo()
                setDatos(nueva); recordarConfiguracion(nueva)
              }}>
                <Trash2 className="size-4" /> Quitar
              </Button>
            )}
          </div>
        </div>
      </div>

      <div className="mt-8">
        <Button onClick={guardar} disabled={guardando || !datos.razon_social.trim()}>
          {guardando ? 'Guardando…' : 'Guardar'}
        </Button>
        {!datos.razon_social.trim() && (
          <p className="text-muted-foreground mt-2 text-xs">
            La razón social es lo único obligatorio: sin ella el papel no tiene
            encabezado.
          </p>
        )}
      </div>
    </div>
  )
}
