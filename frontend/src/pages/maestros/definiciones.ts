import type { Campo } from '@/components/AbmMaestro'

/** Las cinco condiciones de IVA del enum del backend (`app/models/enums.py`).
 *  Si allá se agrega una, acá falta: es el precio de que el enum viva en la
 *  base y no en un maestro. */
export const CONDICIONES_IVA = [
  { valor: 'responsable_inscripto', etiqueta: 'Responsable inscripto' },
  { valor: 'monotributo', etiqueta: 'Monotributo' },
  { valor: 'exento', etiqueta: 'Exento' },
  { valor: 'consumidor_final', etiqueta: 'Consumidor final' },
  { valor: 'no_categorizado', etiqueta: 'No categorizado' },
]

/** Va en los cinco formularios, al final: es lo que permite reactivar desde el
 *  formulario además de desde el botón de la fila. */
export const ACTIVO: Campo = { nombre: 'activo', etiqueta: 'Activo', tipo: 'booleano' }

const GRUPO_ROLES = 'Roles (puede tener más de uno)'

export const CAMPOS_TERCERO: Campo[] = [
  { nombre: 'razon_social', etiqueta: 'Razón social' },
  { nombre: 'cuit', etiqueta: 'CUIT' },
  { nombre: 'condicion_iva', etiqueta: 'Condición de IVA', tipo: 'opciones',
    opciones: CONDICIONES_IVA },
  // Los tres roles juntos y arriba: en el legado eran tres maestros separados,
  // y acá son la única forma de que la entidad aparezca en alguna pestaña. Una misma persona o empresa puede
  // tener más de uno (ADR-040): se tildan, no se vuelve a cargar.
  { nombre: 'es_cliente', etiqueta: 'Cliente', tipo: 'booleano', grupo: GRUPO_ROLES },
  { nombre: 'es_fletero', etiqueta: 'Fletero', tipo: 'booleano', grupo: GRUPO_ROLES },
  { nombre: 'es_proveedor', etiqueta: 'Proveedor', tipo: 'booleano', grupo: GRUPO_ROLES },
  { nombre: 'direccion', etiqueta: 'Dirección' },
  // La provincia va ANTES que la localidad, y no es cosmético: el desplegable
  // de localidades se filtra por ella, así que el orden del formulario es el
  // orden en que hay que completarlo.
  { nombre: 'provincia', etiqueta: 'Provincia', tipo: 'provincia' },
  { nombre: 'localidad', etiqueta: 'Localidad', tipo: 'localidad' },
  { nombre: 'codigo_postal', etiqueta: 'Código postal' },
  { nombre: 'telefono', etiqueta: 'Teléfono' },
  { nombre: 'celular', etiqueta: 'Celular' },
  { nombre: 'email', etiqueta: 'Email' },
  { nombre: 'contacto', etiqueta: 'Contacto' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

/** El maestro de orígenes y destinos.
 *
 *  🔑 El `nombre` es un campo de localidad —se elige del catálogo— pero **sigue
 *  siendo texto libre por debajo**, con la salida explícita para escribirlo.
 *  Es lo que permite cargar un paraje que no está en ningún recurso oficial sin
 *  romper las 121 filas que ya existen, varias de ellas abreviadas. */
export const CAMPOS_LOCALIDAD: Campo[] = [
  { nombre: 'provincia', etiqueta: 'Provincia', tipo: 'provincia' },
  { nombre: 'nombre', etiqueta: 'Nombre', tipo: 'localidad', provinciaEn: 'provincia' },
  ACTIVO,
]

export const CAMPOS_CHOFER: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'dni', etiqueta: 'DNI' },
  // Es el que trae la Carta de Porte: con él se cruza el chofer de la CPE con el de la orden (ADR-037).
  { nombre: 'cuit', etiqueta: 'CUIT', tipo: 'cuit' },
  { nombre: 'telefono', etiqueta: 'Teléfono' },
  { nombre: 'fletero_id', etiqueta: 'Fletero', tipo: 'numero' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

export const CAMPOS_VEHICULO: Campo[] = [
  { nombre: 'patente_chasis', etiqueta: 'Patente del chasis' },
  { nombre: 'patente_acoplado', etiqueta: 'Patente del acoplado' },
  { nombre: 'fletero_id', etiqueta: 'Fletero', tipo: 'numero' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

/** El campo `fletero_id` de un formulario, que en la tabla es un número, como un desplegable con los fleteros por nombre.
 *  Mientras la lista no llegó queda el número tal cual: el formulario no espera a la red para poder abrirse. */
export function conFleteros(campos: Campo[], fleteros: { id: number; razon_social: string }[]): Campo[] {
  if (fleteros.length === 0) return campos
  return campos.map((c) => c.nombre !== 'fletero_id' ? c : {
    ...c, tipo: 'opciones', numerico: true,
    opciones: [
      { valor: '', etiqueta: 'Sin fletero' },
      ...fleteros.map((f) => ({ valor: String(f.id), etiqueta: f.razon_social })),
    ],
  })
}

export const CAMPOS_TIPO_CARGA: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'unidad_default', etiqueta: 'Unidad por defecto' },
  ACTIVO,
]
