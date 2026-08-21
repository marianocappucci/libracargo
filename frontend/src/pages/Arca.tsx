/** Facturación electrónica: las credenciales de ARCA de cada razón social.
 *
 *  🔑 **Esta pantalla configura, no emite.** Hoy el comprobante se registra con
 *  el número que tipea una persona, igual que en el sistema viejo. Emitir es la
 *  fase siguiente, y lo que hace falta antes es tener las credenciales cargadas
 *  y **verificadas** — que es lo que se hace acá.
 *
 *  Lo que la pantalla contesta y ningún nombre de archivo puede: si el
 *  certificado es un certificado, **cuándo vence**, y si el certificado y la
 *  clave son pareja.
 */
import { AlertTriangle, CheckCircle2, ShieldCheck, Trash2, Upload } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import type { Ambiente, ConfiguracionArca } from '@/api/arca'
import { arca } from '@/api/arca'
import { mensajeDeError } from '@/components/AbmMaestro'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'

/** Cuántos días antes de vencer se empieza a avisar. Un certificado de ARCA
 *  dura dos años: con un mes hay tiempo de sobra para renovarlo, y menos que
 *  eso convierte el aviso en una urgencia. */
const DIAS_DE_AVISO = 30

function fechaCorta(iso: string | null): string {
  if (!iso) return '—'
  const [a, m, d] = iso.slice(0, 10).split('-')
  return `${d}-${m}-${a}`
}

function SubirArchivo({ etiqueta, nombre, alElegir, deshabilitado }: {
  etiqueta: string
  nombre: string | null
  alElegir: (archivo: File) => void
  deshabilitado?: boolean
}) {
  const entrada = useRef<HTMLInputElement>(null)
  return (
    <div className="grid gap-1">
      <Label>{etiqueta}</Label>
      <div className="flex items-center gap-2">
        <Button type="button" variant="outline" size="sm" disabled={deshabilitado}
                onClick={() => entrada.current?.click()}>
          <Upload className="size-4" /> {nombre ? 'Reemplazar' : 'Subir'}
        </Button>
        <span className="text-muted-foreground truncate text-sm">
          {nombre ?? 'Sin cargar'}
        </span>
      </div>
      <input ref={entrada} type="file" className="hidden"
             aria-label={etiqueta}
             onChange={(e) => {
               const archivo = e.target.files?.[0]
               if (archivo) alElegir(archivo)
               // Se limpia para que elegir DOS VECES el mismo archivo vuelva a
               // disparar el `change`: si no, corregir y resubir el mismo
               // nombre no hace nada y parece que la pantalla se colgó.
               e.target.value = ''
             }} />
    </div>
  )
}

function Estado({ cfg }: { cfg: ConfiguracionArca }) {
  const cert = cfg.certificado
  if (!cert && !cfg.tiene_clave) {
    return <p className="text-muted-foreground text-sm">Todavía no hay credenciales cargadas.</p>
  }
  if (!cert || !cfg.tiene_clave) {
    return (
      <p className="text-sm font-medium text-amber-600 dark:text-amber-500">
        <AlertTriangle className="mr-1 inline size-4" />
        Falta {cert ? 'la clave privada' : 'el certificado'}: con una sola mitad no se
        puede facturar.
      </p>
    )
  }
  if (cfg.coinciden === false) {
    return (
      <p role="alert" className="text-destructive text-sm font-semibold">
        🔴 El certificado y la clave <strong>no son pareja</strong>. Los dos archivos son
        válidos por separado, pero ARCA va a rechazar la autenticación: suele pasar
        cuando se genera una clave nueva y se sube el certificado anterior.
      </p>
    )
  }
  if (cert.vencido) {
    return (
      <p role="alert" className="text-destructive text-sm font-semibold">
        🔴 El certificado venció el {fechaCorta(cert.vence)}. Hay que renovarlo en ARCA.
      </p>
    )
  }
  if (cert.dias_para_vencer <= DIAS_DE_AVISO) {
    return (
      <p className="text-sm font-medium text-amber-600 dark:text-amber-500">
        <AlertTriangle className="mr-1 inline size-4" />
        El certificado vence en {cert.dias_para_vencer} días ({fechaCorta(cert.vence)}).
      </p>
    )
  }
  return (
    <p className="text-sm font-medium text-emerald-600 dark:text-emerald-500">
      <CheckCircle2 className="mr-1 inline size-4" />
      Certificado y clave verificados. Vence el {fechaCorta(cert.vence)}.
    </p>
  )
}

function Tarjeta({ cfg, alCambiar, alFallar }: {
  cfg: ConfiguracionArca
  alCambiar: (nueva: ConfiguracionArca) => void
  alFallar: (mensaje: string) => void
}) {
  const id = cfg.razon_social_id
  const listo = cfg.certificado != null && cfg.tiene_clave && cfg.coinciden === true

  const correr = (promesa: Promise<ConfiguracionArca>) =>
    promesa.then(alCambiar).catch((e) => alFallar(mensajeDeError(e)))

  return (
    <div className="mb-4 rounded-lg border p-4">
      <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold">{cfg.razon_social}</h3>
        <span className="text-muted-foreground text-sm">
          CUIT {cfg.cuit || '—'} · punto de venta {cfg.punto_venta}
        </span>
      </div>

      <div className="mb-3 grid gap-3 sm:grid-cols-2">
        <SubirArchivo etiqueta="Certificado (.crt)" nombre={cfg.certificado?.nombre ?? null}
                      alElegir={(a) => correr(arca.subirCertificado(id, a))} />
        <SubirArchivo etiqueta="Clave privada (.key)" nombre={cfg.clave_nombre}
                      alElegir={(a) => correr(arca.subirClave(id, a))} />
      </div>

      <div className="mb-3"><Estado cfg={cfg} /></div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1">
          <Label htmlFor={`amb-${id}`}>Ambiente</Label>
          <select id={`amb-${id}`} className="h-9 rounded-md border px-2 text-sm"
                  value={cfg.ambiente}
                  onChange={(e) => correr(arca.guardar(id, {
                    ambiente: e.target.value as Ambiente, habilitado: cfg.habilitado,
                  }))}>
            <option value="homologacion">Homologación (pruebas)</option>
            <option value="produccion">Producción (comprobantes reales)</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <input id={`hab-${id}`} type="checkbox" checked={cfg.habilitado}
                 disabled={!listo && !cfg.habilitado}
                 onChange={(e) => correr(arca.guardar(id, {
                   ambiente: cfg.ambiente, habilitado: e.target.checked,
                 }))} />
          <Label htmlFor={`hab-${id}`}>Habilitar facturación electrónica</Label>
        </div>

        {(cfg.certificado || cfg.tiene_clave) && (
          <Button variant="ghost" size="sm" className="ml-auto"
                  onClick={() => correr(arca.borrarCredenciales(id))}>
            <Trash2 className="size-4" /> Borrar credenciales
          </Button>
        )}
      </div>

      {cfg.ambiente === 'produccion' && cfg.habilitado && (
        <p className="text-muted-foreground mt-3 text-xs">
          En producción, cada comprobante que se emita es un comprobante fiscal real.
        </p>
      )}
    </div>
  )
}

export function FacturacionArca() {
  const [filas, setFilas] = useState<ConfiguracionArca[]>([])
  const [error, setError] = useState<string | null>(null)
  const [cargando, setCargando] = useState(true)

  useEffect(() => {
    arca.listar()
      .then(setFilas)
      .catch((e) => setError(mensajeDeError(e)))
      .finally(() => setCargando(false))
  }, [])

  const reemplazar = (nueva: ConfiguracionArca) => {
    setError(null)
    setFilas((previas) =>
      previas.map((f) => (f.razon_social_id === nueva.razon_social_id ? nueva : f)))
  }

  return (
    <div>
      <div className="mb-4">
        <h2 className="flex items-center gap-2 text-xl font-semibold">
          <ShieldCheck className="size-5" /> Facturación electrónica (ARCA)
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">
          El certificado de ARCA es de un CUIT, así que se carga por razón social. Acá se
          cargan y se verifican las credenciales; <strong>emitir todavía no está</strong>:
          los comprobantes se registran con el número que se tipea.
        </p>
      </div>

      {error && (
        <p role="alert" className="border-destructive/40 mb-4 rounded border p-3 text-sm">
          {error}
        </p>
      )}

      {cargando ? (
        <p className="text-muted-foreground text-sm">Cargando…</p>
      ) : filas.length === 0 ? (
        <p className="text-muted-foreground text-sm">
          No hay razones sociales activas. Cargá una en Configuración → Razones sociales:
          es la que le pone el CUIT y el punto de venta a los comprobantes.
        </p>
      ) : (
        filas.map((f) => (
          <Tarjeta key={f.razon_social_id} cfg={f} alCambiar={reemplazar} alFallar={setError} />
        ))
      )}
    </div>
  )
}

export default FacturacionArca
