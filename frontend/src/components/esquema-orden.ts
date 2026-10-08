import { z } from 'zod'

import { VALORES_DE_ETAPA } from '@/api/ordenes'
import { aDecimal, conDosDecimales } from '@/lib/tarifa'

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
/** Kilos de un campo del formulario: vacío es «no se sabe» (`null`), no cero. Enteros ≥ 0, como en el backend. */
const kilos = z.preprocess(
  (v) => (v === '' || v == null || (typeof v === 'number' && Number.isNaN(v)) ? null : v),
  z.coerce.number({ error: 'los kilos tienen que ser un número' })
    .int('los kilos son un número entero')
    .min(0, 'los kilos no pueden ser negativos')
    .nullable(),
)

/** Los km del viaje: vacío es «no se sabe» (`null`). Entero de 1 a 99999, como en el backend. */
const kmDelViaje = z.preprocess(
  (v) => (v === '' || v == null || (typeof v === 'number' && Number.isNaN(v)) ? null : v),
  z.coerce.number({ error: 'los km tienen que ser un número' })
    .int('los km son un número entero')
    .min(1, 'los km son 1 o más')
    .max(99999, 'los km no pueden pasar de 99999')
    .nullable(),
)

/** La tarifa por tonelada pactada: vacío es `null`; si no, TEXTO con dos decimales (`19724.7` → `19724.70`), nunca
 *  un `number`. Acepta la coma (`19724,73`) porque así se escribe. */
const tarifaPorTonelada = z.preprocess(
  (v) => (v == null || (typeof v === 'string' && v.trim() === '') ? null : String(v)),
  z.string()
    .refine((v) => aDecimal(v) !== null, 'importe inválido')
    .transform((v) => conDosDecimales(aDecimal(v) as string))
    .nullable(),
)

/** Los dos tramos con kilos: lo que se pesó al cargar y lo que dice el ticket al descargar. */
export const TRAMOS_DE_KILOS = ['carga', 'descarga'] as const
export type TramoDeKilos = (typeof TRAMOS_DE_KILOS)[number]

/** El neto de un tramo cuando se puede calcular: hay bruto y tara y la tara no pasa al bruto. */
export function netoCalculado(bruto: unknown, tara: unknown): number | null {
  if (bruto === '' || bruto == null || tara === '' || tara == null) return null
  const b = Number(bruto)
  const t = Number(tara)
  return Number.isInteger(b) && Number.isInteger(t) && b >= 0 && t >= 0 && t <= b ? b - t : null
}

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
    // `nullish` y no `optional`: la API devuelve `null` en lo que no se cargó, y editar una orden sin remito
    // (o sin cantidad, o sin observaciones) quedaba trabado con «expected string, received null» sin que el
    // usuario hubiera tocado ese campo.
    remito: z.string().max(30).nullish(),
    cantidad: z.string().nullish(),
    unidad: z.string().max(20).nullish(),
    // Los importes se manejan como TEXTO. Pasarlos por `number` los mete en un
    // float binario, que es exactamente el defecto que este producto viene a
    // reparar: en el legado el dinero estaba en `float` de precisión simple.
    tarifa: z.string().regex(/^\d+(\.\d{1,2})?$/, 'importe inválido'),
    alicuota_iva: z.string().regex(/^\d+(\.\d{1,2})?$/, 'alícuota inválida'),
    comision: z.string().regex(/^\d+(\.\d{1,2})?$/, 'importe inválido'),
    observaciones: z.string().nullish(),
    etapa: z.enum(VALORES_DE_ETAPA).default('asignada'),
    kg_bruto_carga: kilos,
    kg_tara_carga: kilos,
    kg_neto_carga: kilos,
    kg_bruto_descarga: kilos,
    kg_tara_descarga: kilos,
    kg_neto_descarga: kilos,
    km: kmDelViaje,
    tarifa_tonelada: tarifaPorTonelada,
  })
  .refine((d) => d.origen_id !== d.destino_id, {
    message: 'el origen y el destino no pueden ser el mismo lugar',
    path: ['destino_id'],
  })
  // Con bruto y tara, la tara no puede pasar al bruto: el mismo mensaje que el 422 del backend.
  .superRefine((d, ctx) => {
    for (const tramo of TRAMOS_DE_KILOS) {
      const bruto = d[`kg_bruto_${tramo}`]
      const tara = d[`kg_tara_${tramo}`]
      if (bruto != null && tara != null && tara > bruto) {
        ctx.addIssue({
          code: 'custom', path: [`kg_tara_${tramo}`],
          message: `los kilos de ${tramo}: la tara (${tara}) no puede ser mayor que el bruto (${bruto})`,
        })
      }
    }
  })
  // 🔑 El neto lo decide la resta cuando hay bruto y tara: se manda ese y no el que haya quedado tipeado, que
  // el servidor rechazaría con un 422 si no coincide.
  .transform((d) => {
    const neto = { ...d }
    for (const tramo of TRAMOS_DE_KILOS) {
      const calculado = netoCalculado(d[`kg_bruto_${tramo}`], d[`kg_tara_${tramo}`])
      if (calculado !== null) neto[`kg_neto_${tramo}`] = calculado
    }
    return neto
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
 *
 * Delega en `libra-ui/fechas` desde la unificacion del 2026-08-24: la cuenta
 * era correcta pero era la cuarta copia de lo mismo en la familia, y de las
 * cinco que habia solo tres fijaban la zona. El nombre se conserva porque lo
 * importan varias pantallas de este producto.
 */
import { hoyISO } from 'libra-ui/fechas'

export { hoyISO as hoyEnArgentina }

/** Un importe en pesos: `$ 1.173.307.438,05`.
 *
 * 🔴 **Formatea sobre el TEXTO, no sobre un número.** Los importes llegan como
 * string porque son `NUMERIC` en la base y `Decimal` en Python; pasarlos por
 * `Number()` para poder usar `toLocaleString` los mete en un float binario, que
 * es exactamente el defecto que este producto vino a reparar. Acá se separa la
 * parte entera de la decimal con `split`, se agrupan los miles de a tres y se
 * arma la cadena: ningún dígito pasa por punto flotante.
 *
 * El negativo lleva el signo **antes del peso** (`-$ 1.234,56`), como se escribe
 * en Argentina.
 */
export function formatearImporte(valor: string | number | null | undefined): string {
  if (valor == null || valor === '') return ''
  const texto = String(valor).trim()
  const negativo = texto.startsWith('-')
  const [entero = '0', decimales = ''] = texto.replace(/^[-+]/, '').split('.')
  // Si no vienen decimales, se completan: un importe con dos decimales siempre
  // se lee igual, y una columna donde algunos tienen coma y otros no se lee mal.
  const centavos = (decimales + '00').slice(0, 2)
  const miles = entero.replace(/\B(?=(\d{3})+(?!\d))/g, '.')
  return `${negativo ? '-' : ''}$ ${miles},${centavos}`
}

/** `dd-mm-aaaa` a partir del texto ISO que devuelve la API.
 *
 * 🔴 Se reordena el TEXTO, sin construir un `Date`. Un `aaaa-mm-dd` no es un
 * instante sino un dia del calendario: `new Date('2026-08-22')` es medianoche
 * UTC, o sea las 21:00 del 21 en Argentina, asi que convertirlo de zona corre
 * el dia para atras SIEMPRE -- no es un caso de borde nocturno. Es el mismo
 * cuidado que ya tenia `hoyEnArgentina` en la otra direccion.
 *
 * Acepta tambien un timestamp (`2026-08-22T14:30:00`) y se queda con la fecha.
 * Lo que no tiene forma de ISO vuelve tal cual: recortarlo a ciegas armaria una
 * fecha con pedazos de otra cosa.
 */
export function formatearFecha(valor: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(valor ?? '')
  return m ? `${m[3]}-${m[2]}-${m[1]}` : (valor ?? '')
}

/** `dd-mm-aaaa HH:MM` a partir del texto ISO que devuelve la API. */
export function formatearFechaHoraDeTexto(valor: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(valor ?? '')
  return m ? `${m[3]}-${m[2]}-${m[1]} ${m[4]}:${m[5]}` : formatearFecha(valor)
}

/** `dd-mm-aaaa HH:MM`, hora de Argentina, reloj de 24 h.
 *
 * El formato de la familia es de PRESENTACION: la API y la base siguen en ISO.
 * Vive aca, al lado de `hoyEnArgentina`, para que el producto tenga un solo
 * lugar donde se decide como se ve una fecha -- y no uno por vista.
 */
export function formatearFechaHora(valor: Date): string {
  const partes = new Intl.DateTimeFormat('es-AR', {
    timeZone: 'America/Argentina/Buenos_Aires',
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).formatToParts(valor)
  const d = Object.fromEntries(partes.map((p) => [p.type, p.value]))
  return `${d.day}-${d.month}-${d.year} ${d.hour}:${d.minute}`
}

/** `850` → `850 B`, `1536` → `1,5 KB`, `2411724` → `2,3 MB`: el tamaño de un archivo como se lee. */
export function formatearTamanio(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const unidades = ['KB', 'MB', 'GB']
  let valor = bytes / 1024
  let i = 0
  while (valor >= 1024 && i < unidades.length - 1) { valor /= 1024; i += 1 }
  return `${valor.toFixed(1).replace('.', ',').replace(/,0$/, '')} ${unidades[i]}`
}

export const ORDEN_VACIA: Partial<EntradaOrden> = {
  fecha: hoyISO(),
  etapa: 'asignada',
  tarifa: '0.00',
  alicuota_iva: '21.00',
  comision: '0.00',
}
