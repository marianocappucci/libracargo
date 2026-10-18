/** El `crear` de `SelectCliente` para todas las pantallas, con el CUIT repetido resuelto ahí mismo (ADR-052).
 *
 *  `crearCliente` da de alta un tercero cliente. Si el CUIT ya es de otra entidad (un fletero, un proveedor: ADR-040) el servidor contesta 409
 *  con esa entidad, y en vez de dejar sólo el mensaje se pregunta «Sumar el rol de cliente a X»: al aceptar se le suma el rol y queda elegida.
 *  El kit no tiene un lugar para una acción dentro de su panel de alta, así que la pregunta es el `ConfirmDialog` del producto, encima del
 *  panel; al cancelar, el panel muestra el mensaje del servidor como antes y lo cargado no se pierde.
 *
 *  Uso: `const alta = useAltaDeCliente()`; `crear={async (d) => { const c = await alta.crear(d); … }}` y `{alta.dialogo}` en la pantalla.
 *
 *  Con un `rol` (`useAltaDeCliente('fletero')`) da de alta un tercero de ese rol y, ante el CUIT repetido, ofrece sumarle **ese** rol: es el
 *  «Tercero» de Caja, que se elige después de la cuenta (ADR-053). Sin `rol`, cliente. */
import { useRef, useState } from 'react'
import type { ClienteNuevo } from 'libra-ui/SelectCliente'

import { crearOSumarRol, type ArregloDeCuitRepetido } from '@/api/clientes'
import type { CuitRepetido, RolDeEntidad } from '@/api/maestros'
import type { Opcion } from '@/api/ordenes'
import { ConfirmDialog } from '@/components/confirm-dialog'

type Pregunta = { repetido: CuitRepetido; arreglo: ArregloDeCuitRepetido }

const TEXTOS: Record<ArregloDeCuitRepetido, (nombre: string, rol: RolDeEntidad) => { titulo: string; boton: string }> = {
  'sumar-rol': (n, r) => ({ titulo: `Sumar el rol de ${r} a «${n}»`, boton: `Sumar el rol de ${r}` }),
  reactivar: (n, r) => ({ titulo: `«${n}» es un ${r} dado de baja`, boton: 'Reactivarlo y elegirlo' }),
  elegir: (n, r) => ({ titulo: `«${n}» ya es ${r}`, boton: 'Elegirlo' }),
}

const DESCRIPCION: Record<ArregloDeCuitRepetido, string> = {
  'sumar-rol': 'Queda como una sola entidad, con el rol sumado a los que ya tenía, y se la elige acá. No se carga otra con el mismo CUIT.',
  reactivar: 'Se lo vuelve a dar de alta y se lo elige acá. No se carga otro con el mismo CUIT.',
  elegir: 'Se lo elige acá. No se carga otro con el mismo CUIT.',
}

export function useAltaDeCliente(rol: RolDeEntidad = 'cliente') {
  const [pregunta, setPregunta] = useState<Pregunta | null>(null)
  const responder = useRef<((si: boolean) => void) | null>(null)

  function contestar(si: boolean) {
    const r = responder.current
    responder.current = null
    setPregunta(null)
    r?.(si)
  }

  const crear = (d: ClienteNuevo): Promise<Opcion> =>
    crearOSumarRol(d, (repetido, arreglo) => new Promise<boolean>((resolver) => {
      responder.current = resolver
      setPregunta({ repetido, arreglo })
    }), rol)

  const textos = pregunta ? TEXTOS[pregunta.arreglo](pregunta.repetido.existente.razon_social, rol) : null
  const dialogo = (
    <ConfirmDialog
      open={pregunta !== null}
      // Cerrar sin confirmar (Cancelar, Escape) es un «no». Al confirmar, `contestar(true)` corre antes y esto ya no hace nada.
      onOpenChange={(abierto) => { if (!abierto) contestar(false) }}
      title={textos?.titulo ?? ''}
      description={pregunta ? `${pregunta.repetido.mensaje} ${DESCRIPCION[pregunta.arreglo]}` : undefined}
      confirmLabel={textos?.boton}
      onConfirm={() => contestar(true)}
    />
  )
  return { crear, dialogo }
}
