/** El alta de un cliente desde el campo «Cliente» de cualquier pantalla (`SelectCliente` del kit, ADR-071 de libra-ui; ADR-050 de este producto).
 *
 *  Un cliente de LibraCargo es un **tercero con el rol `es_cliente`** (ADR-040): se da de alta en `POST /api/terceros`, el mismo endpoint que usa
 *  la pantalla de Entidades. Este archivo es el único lugar que arma ese payload, para que las pantallas no lo repitan. */
import { api } from 'libra-ui/api-client'
import type { CampoDeAlta, ClienteNuevo } from 'libra-ui/SelectCliente'

import type { Opcion } from '@/api/ordenes'
import { cuitRepetido, sumarRol, type CuitRepetido, type Maestro } from '@/api/maestros'
import { condicionDeArca } from '@/pages/maestros/definiciones'

/** Qué se pide al dar de alta un cliente acá: se le factura, así que el CUIT y la condición frente al IVA van además del contacto. */
export const CAMPOS_DE_ALTA_DE_CLIENTE: CampoDeAlta[] = ['documento', 'condicionIva', 'telefono', 'email']

/** Lo que se le pasa a `SelectCliente` además de `crear`: lo mismo en todas las pantallas. */
export const ALTA_DE_CLIENTE = { campos: CAMPOS_DE_ALTA_DE_CLIENTE, etiquetaDocumento: 'CUIT' } as const

/** El cuerpo de `POST /api/terceros` para un cliente nuevo. Lo que no se pidió o quedó vacío no viaja.
 *
 *  La condición frente al IVA llega con los textos del kit (`IVA_CONDITIONS`) y se pasa al enum del servidor. «No Alcanzado» no tiene
 *  equivalente: no se manda y el servidor usa su valor por defecto (Consumidor Final), como hace la consulta al padrón de ARCA
 *  (`condicionDeArca`). */
export function terceroDeCliente(d: ClienteNuevo): Record<string, unknown> {
  const iva = d.condicionIva ? condicionDeArca(d.condicionIva) : undefined
  return {
    razon_social: d.nombre,
    es_cliente: true,
    ...(d.documento ? { cuit: d.documento } : {}),
    ...(iva ? { condicion_iva: iva } : {}),
    ...(d.telefono ? { telefono: d.telefono } : {}),
    ...(d.email ? { email: d.email } : {}),
  }
}

type TerceroDevuelto = Maestro & { razon_social: string; cuit?: string | null }

const aOpcion = (t: TerceroDevuelto): Opcion => ({ id: t.id, etiqueta: t.razon_social, ...(t.cuit ? { detalle: t.cuit } : {}) })

/** Da de alta el cliente y devuelve la opción con la misma forma que las de `cargarOpciones` (el CUIT va como `detalle`). */
export async function crearCliente(d: ClienteNuevo): Promise<Opcion> {
  return aOpcion(await api.post<TerceroDevuelto>('/api/terceros', terceroDeCliente(d)))
}

/** Qué hay que hacer con la entidad que ya tiene el CUIT para usarla de cliente: sumarle el rol, reactivarla (es un cliente dado de baja) o
 *  nada (ya es un cliente activo, y alcanza con elegirla). */
export type ArregloDeCuitRepetido = 'sumar-rol' | 'reactivar' | 'elegir'

export function arregloDe(r: CuitRepetido): ArregloDeCuitRepetido {
  if (!r.existente.roles.includes('cliente')) return 'sumar-rol'
  return r.existente.activo ? 'elegir' : 'reactivar'
}

/** El alta en el lugar cuando el CUIT ya es de otra entidad (ADR-040, ADR-052): el servidor contesta 409 con la entidad existente y, si quien
 *  carga acepta (`confirmar`), se le suma el rol de cliente —que también la reactiva— y se devuelve **ella** como el cliente elegido, en vez de
 *  cargar una segunda con el mismo CUIT. Si no acepta, o el error es otro, el error sigue de largo y el panel del kit lo muestra como siempre.
 *
 *  Una entidad que ya es cliente activo no se toca: se elige. */
export async function crearOSumarRol(
  d: ClienteNuevo, confirmar: (r: CuitRepetido, arreglo: ArregloDeCuitRepetido) => Promise<boolean>,
): Promise<Opcion> {
  try {
    return await crearCliente(d)
  } catch (e) {
    const r = cuitRepetido(e)
    if (!r) throw e
    const arreglo = arregloDe(r)
    if (!(await confirmar(r, arreglo))) throw e
    if (arreglo === 'elegir') {
      return { id: r.existente.id, etiqueta: r.existente.razon_social, ...(d.documento ? { detalle: d.documento } : {}) }
    }
    return aOpcion(await sumarRol(r.existente.id, 'cliente') as TerceroDevuelto)
  }
}

/** La opción del buscador del kit para una opción de este producto. */
export const aOpcionDeSelect = (o: Opcion) => ({ value: String(o.id), label: o.etiqueta, ...(o.detalle ? { hint: o.detalle } : {}) })

/** Las opciones del campo «Cliente»: la lista de la pantalla con la opción vacía adelante (`vacio` es lo que dice cuando no hay ninguno elegido). */
export const opcionesCliente = (clientes: Opcion[], vacio = 'Elegir…') =>
  [{ value: '', label: vacio }, ...clientes.map(aOpcionDeSelect)]

/** Suma el cliente recién creado a las listas de la pantalla (`clientes` y `terceros`), sin repetirlo. */
export function conClienteNuevo<T extends { clientes: Opcion[]; terceros: Opcion[] }>(o: T, c: Opcion): T {
  const sumar = (l: Opcion[]) => (l.some((x) => x.id === c.id) ? l : [...l, c])
  return { ...o, clientes: sumar(o.clientes), terceros: sumar(o.terceros) }
}
