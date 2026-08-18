import { z } from 'zod'

/** El esquema del formulario de orden.
 *
 * Acá SÍ entran Zod y React Hook Form, a diferencia de los seis ABM de
 * maestros: este formulario tiene doce campos y **una regla entre dos de
 * ellos** —origen distinto de destino—, que es justo lo que un formulario de
 * campos sueltos no sabe expresar.
 *
 * > La regla vive en tres lugares a propósito: acá para explicarla mientras se
 * > escribe, en el esquema de Pydantic para que la API la rechace con un 422, y
 * > como `CHECK` en la base, que es la única que no puede mentir. No es
 * > duplicación: es la misma regla dicha en las tres capas que pueden fallar.
 */
export const esquemaOrden = z
  .object({
    fecha: z.string().min(1, 'la fecha es obligatoria'),
    cliente_id: z.coerce.number().int().positive('elegí un cliente'),
    origen_id: z.coerce.number().int().positive('elegí un origen'),
    destino_id: z.coerce.number().int().positive('elegí un destino'),
    fletero_id: z.coerce.number().int().positive().nullable().optional(),
    chofer_id: z.coerce.number().int().positive().nullable().optional(),
    vehiculo_id: z.coerce.number().int().positive().nullable().optional(),
    tipo_carga_id: z.coerce.number().int().positive().nullable().optional(),
    razon_social_id: z.coerce.number().int().positive().nullable().optional(),
    remito: z.string().max(30).optional(),
    cantidad: z.string().optional(),
    unidad: z.string().max(20).optional(),
    // Los importes se manejan como TEXTO. Pasarlos por `number` los mete en un
    // float binario, que es exactamente el defecto que este producto viene a
    // reparar: en el legado el dinero estaba en `float` de precisión simple.
    tarifa: z.string().regex(/^\d+(\.\d{1,2})?$/, 'importe inválido'),
    alicuota_iva: z.string().regex(/^\d+(\.\d{1,2})?$/, 'alícuota inválida'),
    comision: z.string().regex(/^\d+(\.\d{1,2})?$/, 'importe inválido'),
    observaciones: z.string().optional(),
  })
  .refine((d) => d.origen_id !== d.destino_id, {
    message: 'el origen y el destino no pueden ser el mismo lugar',
    path: ['destino_id'],
  })

/** 🔑 El formulario tiene DOS tipos, y no son el mismo.
 *
 * Un `<select>` devuelve **texto**, y la API quiere un entero: `z.coerce`
 * convierte, asi que la ENTRADA del esquema es lo que se tipea y la SALIDA es
 * lo que se manda. Tratarlos como uno solo compila mal y, peor, esconde donde
 * ocurre la conversion.
 */
export type EntradaOrden = z.input<typeof esquemaOrden>
export type DatosOrden = z.output<typeof esquemaOrden>

/** Hoy, en hora de Argentina.
 *
 * 🔴 NO `toISOString().slice(0,10)`: eso da la fecha en **UTC**, y a las 21:00
 * de Argentina ya es el dia siguiente. Una orden cargada de noche nacia con la
 * fecha de manana, y el error no se ve --es una fecha plausible-- hasta que no
 * cierra un listado por dia.
 */
export function hoyEnArgentina(): string {
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Argentina/Buenos_Aires',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).format(new Date())
}

export const ORDEN_VACIA: Partial<EntradaOrden> = {
  fecha: hoyEnArgentina(),
  tarifa: '0.00',
  alicuota_iva: '21.00',
  comision: '0.00',
}
