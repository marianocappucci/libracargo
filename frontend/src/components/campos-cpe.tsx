/** Los campos del formulario de una Carta de Porte, compartidos por el asistente de emitir (`EmitirCartaDePorte`) y por el
 *  editor de la plantilla de un titular (`PlantillaDeTitular`): el mismo campo se ve y se comporta igual en los dos.
 *
 *  Sólo presentación. Qué es válido lo decide `emision-cpe.ts`, que es lo que comparten también.
 */
import type { OpcionDeArca } from '@/api/cartas-porte'
import { enmascararCuit } from '@/api/cartas-porte'
import { Elegir } from '@/components/Elegir'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { cn } from '@/lib/utils'

export const aOpciones = (lista: OpcionDeArca[]) => lista.map((o) => ({ id: o.codigo, etiqueta: o.nombre }))

export function Campo({ id, etiqueta, error, ayuda, children, className }: {
  id: string
  etiqueta: string
  error?: string
  ayuda?: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <div className={cn('grid min-w-0 content-start gap-1', className)}>
      <Label htmlFor={id}>{etiqueta}</Label>
      {children}
      {ayuda && !error && <p className="text-muted-foreground text-xs">{ayuda}</p>}
      {error && <p id={`${id}-error`} className="text-destructive text-xs">{error}</p>}
    </div>
  )
}

export function Texto({ id, etiqueta, valor, alCambiar, error, ayuda, className, ...resto }: {
  id: string
  etiqueta: string
  valor: string
  alCambiar: (v: string) => void
  error?: string
  ayuda?: string
  className?: string
} & Omit<React.ComponentProps<typeof Input>, 'id' | 'value' | 'onChange'>) {
  return (
    <Campo id={id} etiqueta={etiqueta} error={error} ayuda={ayuda} className={className}>
      <Input id={id} value={valor} onChange={(e) => alCambiar(e.target.value)}
             aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined} {...resto} />
    </Campo>
  )
}

export const TextoCuit = (p: Omit<Parameters<typeof Texto>[0], 'alCambiar' | 'inputMode' | 'placeholder'> & {
  alCambiar: (v: string) => void
}) => (
  <Texto {...p} inputMode="numeric" placeholder="00-00000000-0" alCambiar={(v) => p.alCambiar(enmascararCuit(v))} />
)

export const TextoNumero = (p: Parameters<typeof Texto>[0]) => (
  <Texto {...p} inputMode="numeric" alCambiar={(v) => p.alCambiar(v.replace(/\D/g, ''))} />
)

/** Un select de un catálogo de ARCA, con el error debajo (el de `Elegir` no pinta el borde). */
export function Catalogo({ id, etiqueta, valor, opciones, alCambiar, error, deshabilitado }: {
  id: string
  etiqueta: string
  valor: string
  opciones: OpcionDeArca[]
  alCambiar: (v: string) => void
  error?: string
  deshabilitado?: boolean
}) {
  return (
    <div className="grid min-w-0 content-start gap-1">
      <Elegir id={id} etiqueta={etiqueta} vacio="Elegir…" valor={valor} opciones={aOpciones(opciones)}
              alCambiar={alCambiar} deshabilitado={deshabilitado} />
      {error && <p className="text-destructive text-xs">{error}</p>}
    </div>
  )
}

export function Seccion({ titulo, children }: { titulo: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-3 rounded-md border p-4">
      <legend className="px-1 text-sm font-semibold">{titulo}</legend>
      <div className="grid gap-3 md:grid-cols-2">{children}</div>
    </fieldset>
  )
}

export function Casilla({ id, etiqueta, marcada, alCambiar, className }: {
  id: string; etiqueta: string; marcada: boolean; alCambiar: (v: boolean) => void; className?: string
}) {
  return (
    <div className={cn('flex items-center gap-2 self-end pb-2', className)}>
      <input id={id} type="checkbox" checked={marcada} onChange={(e) => alCambiar(e.target.checked)} />
      <Label htmlFor={id}>{etiqueta}</Label>
    </div>
  )
}
