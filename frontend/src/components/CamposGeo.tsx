/** Provincia y localidad: se eligen, no se tipean.
 *
 *  El pedido del cliente fue *"que no se carguen mal y sólo se seleccionen"*, y
 *  el maestro que lo motivó lo explica solo: 121 localidades cargadas a mano,
 *  con `Gral Paz` y `Gral. Paz` como dos filas distintas, `Pto San Martín` y
 *  `Pto. San Martín` también, y `Campo`, `Shap` y `(sin nombre)` conviviendo
 *  con pueblos reales.
 *
 *  🔑 **Pero el campo sigue guardando texto, no un id.** Es a propósito:
 *
 *  - Los datos viejos no se pierden ni se reescriben solos. Al abrir un tercero
 *    cuya localidad dice `Cnel. Bogado` —que no está en el catálogo con esa
 *    abreviatura— el campo **arranca en modo texto con el valor puesto**. Un
 *    desplegable que no encuentra el valor guardado lo mostraría vacío, y
 *    guardar sin tocar nada borraría el dato.
 *  - Hay lugares reales que no están en ningún recurso oficial —Tomás Jofré,
 *    sin ir más lejos— y un desplegable cerrado dejaría al operador sin poder
 *    cargar el viaje.
 *
 *  Así que el valor por omisión es elegir, y escribir es una salida explícita
 *  que queda a la vista.
 */
import { useEffect, useState } from 'react'
import { SelectBuscable } from 'libra-ui/SelectBuscable'

import {
  localidadesDe, provincias as traerProvincias,
  type LocalidadDelCatalogo, type Provincia,
} from '@/api/geo'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const SIN_ESPECIFICAR = ''

function Alternar({ escribiendo, alAlternar }: {
  escribiendo: boolean
  alAlternar: () => void
}) {
  return (
    <Button type="button" variant="link" className="h-auto justify-start p-0 text-xs"
            onClick={alAlternar}>
      {escribiendo ? 'Elegir de la lista' : 'No está en la lista: escribirla'}
    </Button>
  )
}

export function SelectProvincia({ id, etiqueta, valor, alCambiar }: {
  id: string
  etiqueta: string
  valor: string
  alCambiar: (v: string) => void
}) {
  const [opciones, setOpciones] = useState<Provincia[]>([])
  const [error, setError] = useState(false)

  useEffect(() => {
    traerProvincias().then(setOpciones).catch(() => setError(true))
  }, [])

  // Si el catálogo no cargó, el campo cae a texto en vez de quedar como un
  // desplegable vacío: no poder elegir no puede volverse no poder cargar.
  if (error) {
    return (
      <div className="grid gap-1">
        <Label htmlFor={id}>{etiqueta}</Label>
        <Input id={id} value={valor} onChange={(e) => alCambiar(e.target.value)} />
        <span className="text-muted-foreground text-xs">
          No se pudo cargar el catálogo de provincias; se puede escribir.
        </span>
      </div>
    )
  }

  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      <SelectBuscable
        id={id}
        value={valor ?? SIN_ESPECIFICAR}
        onChange={alCambiar}
        opciones={[{ value: SIN_ESPECIFICAR, label: 'Sin especificar' },
                   ...opciones.map((p) => ({ value: p.nombre, label: p.nombre }))]}
        placeholder="Sin especificar"
        emptyMessage="No hay ninguna provincia con ese nombre."
        ariaLabel={etiqueta}
        className="w-full min-w-0"
      />
    </div>
  )
}

export function SelectLocalidad({ id, etiqueta, valor, provincia, alCambiar }: {
  id: string
  etiqueta: string
  valor: string
  /** El nombre de la provincia elegida en el mismo formulario. */
  provincia: string
  alCambiar: (v: string) => void
}) {
  const [opciones, setOpciones] = useState<LocalidadDelCatalogo[]>([])
  const [escribiendo, setEscribiendo] = useState(false)
  // Una sola vez, al montar: si el valor guardado no está en el catálogo, el
  // campo arranca en modo texto. Después de eso manda lo que elija la persona,
  // porque si no cambiar de provincia devolvería el campo a texto solo.
  const [decidido, setDecidido] = useState(false)

  useEffect(() => {
    let vigente = true
    traerProvincias()
      .then((ps) => ps.find((p) => p.nombre === provincia)?.id ?? '')
      .then(localidadesDe)
      .then((filas) => {
        if (!vigente) return
        setOpciones(filas)
        if (!decidido) {
          setEscribiendo(Boolean(valor) && !filas.some((f) => f.nombre === valor))
          setDecidido(true)
        }
      })
      .catch(() => { if (vigente) { setEscribiendo(true); setDecidido(true) } })
    return () => { vigente = false }
  }, [provincia, valor, decidido])

  const sinProvincia = !provincia

  return (
    <div className="grid gap-1">
      <Label htmlFor={id}>{etiqueta}</Label>
      {escribiendo || sinProvincia ? (
        <Input id={id} value={valor ?? ''} onChange={(e) => alCambiar(e.target.value)} />
      ) : (
        <SelectBuscable
          id={id}
          value={valor ?? ''}
          onChange={alCambiar}
          opciones={[{ value: '', label: 'Sin especificar' },
                     ...opciones.map((l) => ({ value: l.nombre, label: l.nombre }))]}
          placeholder="Sin especificar"
          emptyMessage="No hay ninguna con ese nombre en esta provincia."
          ariaLabel={etiqueta}
          className="w-full min-w-0"
        />
      )}
      {sinProvincia ? (
        <span className="text-muted-foreground text-xs">
          Elegí la provincia para poder seleccionar la localidad.
        </span>
      ) : (
        <Alternar escribiendo={escribiendo}
                  alAlternar={() => { setEscribiendo((e) => !e); setDecidido(true) }} />
      )}
    </div>
  )
}
