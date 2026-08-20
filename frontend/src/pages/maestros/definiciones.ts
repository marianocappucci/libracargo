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

/** Va en los seis formularios, al final: es lo que permite reactivar desde el
 *  formulario además de desde el botón de la fila. */
export const ACTIVO: Campo = { nombre: 'activo', etiqueta: 'Activo', tipo: 'booleano' }

export const CAMPOS_TERCERO: Campo[] = [
  { nombre: 'razon_social', etiqueta: 'Razón social' },
  { nombre: 'cuit', etiqueta: 'CUIT' },
  { nombre: 'condicion_iva', etiqueta: 'Condición de IVA', tipo: 'opciones',
    opciones: CONDICIONES_IVA },
  // Los tres roles juntos y arriba: en el legado eran tres maestros separados,
  // y acá son la única forma de que el tercero aparezca en alguna pantalla.
  { nombre: 'es_cliente', etiqueta: 'Es cliente', tipo: 'booleano' },
  { nombre: 'es_fletero', etiqueta: 'Es fletero', tipo: 'booleano' },
  { nombre: 'es_proveedor', etiqueta: 'Es proveedor', tipo: 'booleano' },
  { nombre: 'direccion', etiqueta: 'Dirección' },
  { nombre: 'localidad', etiqueta: 'Localidad' },
  { nombre: 'provincia', etiqueta: 'Provincia' },
  { nombre: 'codigo_postal', etiqueta: 'Código postal' },
  { nombre: 'telefono', etiqueta: 'Teléfono' },
  { nombre: 'celular', etiqueta: 'Celular' },
  { nombre: 'email', etiqueta: 'Email' },
  { nombre: 'contacto', etiqueta: 'Contacto' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

export const CAMPOS_LOCALIDAD: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'provincia', etiqueta: 'Provincia' },
  ACTIVO,
]

export const CAMPOS_CHOFER: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'dni', etiqueta: 'DNI' },
  { nombre: 'telefono', etiqueta: 'Teléfono' },
  { nombre: 'fletero_id', etiqueta: 'ID del fletero', tipo: 'numero' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

export const CAMPOS_VEHICULO: Campo[] = [
  { nombre: 'patente_chasis', etiqueta: 'Patente del chasis' },
  { nombre: 'patente_acoplado', etiqueta: 'Patente del acoplado' },
  { nombre: 'fletero_id', etiqueta: 'ID del fletero', tipo: 'numero' },
  { nombre: 'observaciones', etiqueta: 'Observaciones' },
  ACTIVO,
]

export const CAMPOS_RAZON_SOCIAL: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'cuit', etiqueta: 'CUIT' },
  { nombre: 'condicion_iva', etiqueta: 'Condición de IVA', tipo: 'opciones',
    opciones: CONDICIONES_IVA },
  { nombre: 'punto_venta', etiqueta: 'Punto de venta', tipo: 'numero' },
  ACTIVO,
]

export const CAMPOS_TIPO_CARGA: Campo[] = [
  { nombre: 'nombre', etiqueta: 'Nombre' },
  { nombre: 'unidad_default', etiqueta: 'Unidad por defecto' },
  ACTIVO,
]
