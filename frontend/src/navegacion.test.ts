import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { estaActivo } from 'libra-ui/Layout'
import { describe, expect, it } from 'vitest'

import {
  MAESTROS_AUDITADOS, PESTANAS_DE_CARTAS_DE_PORTE, PESTANAS_DE_TRANSPORTE, SECCIONES_MUDADAS_DE_CONFIGURACION, TIPOS_DE_ENTIDAD,
  destinoDeEntidadesViejo, destinoDeFilaDeReporte, destinoDelLog, destinoDeVehiculosViejo, irA,
  origenDelMovimiento, pestanaDeCartasDePorte, pestanaDeTransporte, RUTAS_DE_COMPROBANTES, seccionDe, verValido,
} from './navegacion'

function movimiento(extra: Record<string, unknown>) {
  return {
    movimiento: {
      id: 1, fecha: '2026-08-20', tercero_id: 1, rol: 'cliente', concepto: 'x',
      descripcion: null, debe: '0.00', haber: '0.00',
      orden_id: null, comprobante_id: null, movimiento_caja_id: null,
      gasto_id: null, ...extra,
    },
    saldo: '0.00',
  } as never
}

describe('origenDelMovimiento', () => {
  it('🔑 prefiere el comprobante cuando el asiento apunta a los dos', () => {
    // Un asiento migrado puede tener orden Y comprobante. Gana el comprobante
    // porque es el documento que explica el importe de esa linea, y desde ahi
    // se ven todas las ordenes que agrupa.
    expect(origenDelMovimiento(movimiento({ orden_id: 7, comprobante_id: 9 })))
      .toBe('/comprobantes?ver=9')
  })

  it('lleva a la orden cuando es lo unico que hay', () => {
    expect(origenDelMovimiento(movimiento({ orden_id: 7 }))).toBe('/ordenes?ver=7')
  })

  it('lleva a caja cuando el asiento salio de un cobro o un pago', () => {
    expect(origenDelMovimiento(movimiento({ movimiento_caja_id: 3 }))).toBe('/caja?ver=3')
  })

  it('lleva al gasto cuando el asiento salio de un gasto de proveedor', () => {
    // Es el cuarto origen posible, y el que trajo el bloque de proveedores.
    expect(origenDelMovimiento(movimiento({ gasto_id: 4 }))).toBe('/comprobantes?seccion=proveedores&ver=4')
  })

  it('un asiento sin origen NO es clickeable', () => {
    // Son los 36 asientos sueltos del historico migrado. Devolver una ruta
    // igual mandaria a una pantalla que no explica nada.
    expect(origenDelMovimiento(movimiento({}))).toBeNull()
  })
})

describe('destinoDelLog', () => {
  it('las tres entidades con detalle propio', () => {
    expect(destinoDelLog('orden_carga', 5)).toBe('/ordenes?ver=5')
    expect(destinoDelLog('comprobante', 5)).toBe('/comprobantes?ver=5')
    expect(destinoDelLog('movimiento_caja', 5)).toBe('/caja?ver=5')
    expect(destinoDelLog('gasto_de_proveedor', 5)).toBe('/comprobantes?seccion=proveedores&ver=5')
  })

  it('la pre factura lleva a su pantalla, que no es un diálogo sobre la lista', () => {
    expect(destinoDelLog('pre_factura', 7)).toBe('/pre-facturas/7')
    expect(irA.preFactura(7)).toBe('/pre-facturas/7')
    expect(destinoDelLog('pre_factura', null)).toBeNull()
  })

  it('🔑 los maestros se auditan en PLURAL, que es el prefijo del ABM', () => {
    // El backend registra con el `prefijo` del router generico, asi que en la
    // base dice `localidades` y no `localidad`. Un mapa escrito en singular
    // habria compilado igual y no habria linkeado nada.
    expect(destinoDelLog('localidades', 3)).toBe('/localidades')
    // Un tercero no dice de qué rol era: va a Clientes. Los choferes y los vehículos, a su pestaña de Transporte (ADR-045).
    expect(destinoDelLog('terceros', 3)).toBe('/clientes')
    expect(destinoDelLog('choferes', 3)).toBe('/transporte?pestana=choferes')
    expect(destinoDelLog('vehiculos', 3)).toBe('/transporte?pestana=vehiculos')
    // La razón social se retiró (ADR-035): un asiento viejo del log ya no lleva a ninguna pantalla.
    expect(destinoDelLog('razones-sociales', 3)).toBeNull()
  })

  it('configuracion lleva a su pantalla, sin id', () => {
    expect(destinoDelLog('configuracion', null)).toBe('/configuracion')
  })

  it('una entidad desconocida no es clickeable', () => {
    expect(destinoDelLog('lo-que-sea', 1)).toBeNull()
    // Y con id nulo, las que necesitan id tampoco.
    expect(destinoDelLog('orden_carga', null)).toBeNull()
  })

  it('🔴 cada maestro auditado tiene una ruta de verdad en App.tsx', () => {
    // El guard que evita el modo de falla silencioso: si manana entra un
    // maestro nuevo, o si alguien renombra una ruta, el link del log manda a
    // una pantalla que no existe y el catch-all del SPA devuelve el index --
    // o sea que no falla, simplemente no pasa nada.
    // Desde `process.cwd()`, que bajo vitest es la raiz del frontend:
    // `import.meta.url` no es un `file://` despues de la transformacion.
    const app = readFileSync(resolve(process.cwd(), 'src/App.tsx'), 'utf8')
    for (const maestro of MAESTROS_AUDITADOS) {
      expect(app, `falta la ruta /${maestro}`).toContain(`path="/${maestro}"`)
    }
    // Control positivo del propio chequeo: una ruta inventada NO esta.
    expect(app).not.toContain('path="/maestro-inventado"')
  })
})

describe('destinoDeFilaDeReporte', () => {
  it('los reportes por tercero llevan a su cuenta corriente', () => {
    expect(destinoDeFilaDeReporte('saldos', { tercero_id: 4, rol: 'proveedor' }))
      .toBe('/cuentas?rol=proveedor&tercero=4')
    expect(destinoDeFilaDeReporte('por-cliente', { tercero_id: 4 }))
      .toBe('/cuentas?rol=cliente&tercero=4')
    expect(destinoDeFilaDeReporte('por-fletero', { tercero_id: 4 }))
      .toBe('/cuentas?rol=fletero&tercero=4')
    expect(destinoDeFilaDeReporte('pendientes-de-facturar', { cliente_id: 8 }))
      .toBe('/cuentas?rol=cliente&tercero=8')
  })

  it('🔑 los agregados puros NO son clickeables, a proposito', () => {
    // La fila de "caja por medio de pago" no es una cosa, es una suma: no hay
    // a donde mandar. Devolver algo arbitrario es peor que no hacer nada.
    expect(destinoDeFilaDeReporte('caja', { tipo: 'ingreso', importe: '1.00' })).toBeNull()
    expect(destinoDeFilaDeReporte('por-ruta', { origen: 'A', destino: 'B' })).toBeNull()
  })

  it('una fila sin el id que el reporte promete no rompe', () => {
    expect(destinoDeFilaDeReporte('saldos', {})).toBeNull()
    expect(destinoDeFilaDeReporte('por-cliente', { tercero_id: null })).toBeNull()
  })
})

describe('irA', () => {
  it('las rutas son las que el ruteo conoce', () => {
    expect(irA.orden(1)).toBe('/ordenes?ver=1')
    expect(irA.cuentaDe(2)).toBe('/cuentas?tercero=2')
  })
})

describe('Comprobantes: secciones y menú', () => {
  it('la sección sale del query, y lo desconocido cae en Clientes', () => {
    expect(seccionDe('proveedores')).toBe('proveedores')
    expect(seccionDe('clientes')).toBe('clientes')
    expect(seccionDe(null)).toBe('clientes')
    expect(seccionDe('cualquier-cosa')).toBe('clientes')
  })

  it('🔑 todo lo que cuelga de Comprobantes marca esa entrada del menú', () => {
    for (const ruta of [
      '/comprobantes', '/comprobantes/facturar', '/pre-facturas', '/pre-facturas/7',
      '/pre-facturas/7/editar', '/gastos',
    ]) expect(estaActivo(ruta, '/comprobantes', RUTAS_DE_COMPROBANTES), ruta).toBe(true)
  })

  it('el resto de las rutas no la marca, ni las que sólo se parecen', () => {
    for (const ruta of ['/', '/ordenes', '/cuentas', '/caja', '/reportes/por-cliente', '/gastos-raros', '/pre-facturasX'])
      expect(estaActivo(ruta, '/comprobantes', RUTAS_DE_COMPROBANTES), ruta).toBe(false)
})
})

describe('Clientes, Proveedores y Transporte (ADR-045, que reemplaza en parte a ADR-040)', () => {
  it('Transporte tiene tres pestañas, en orden; la pestaña sale del query y lo desconocido cae en Fleteros', () => {
    expect(PESTANAS_DE_TRANSPORTE).toEqual(['fleteros', 'choferes', 'vehiculos'])
    expect(pestanaDeTransporte('choferes')).toBe('choferes')
    expect(pestanaDeTransporte('vehiculos')).toBe('vehiculos')
    expect(pestanaDeTransporte(null)).toBe('fleteros')
    expect(pestanaDeTransporte('cualquier-cosa')).toBe('fleteros')
    // Clientes y Proveedores ya no son pestañas de nadie.
    expect(pestanaDeTransporte('clientes')).toBe('fleteros')
    expect(pestanaDeTransporte('proveedores')).toBe('fleteros')
  })

  it('las rutas nuevas arman la pantalla y la ficha', () => {
    expect(irA.clientes()).toBe('/clientes')
    expect(irA.clientes(4)).toBe('/clientes?ver=4')
    expect(irA.proveedores()).toBe('/proveedores')
    expect(irA.proveedores(4)).toBe('/proveedores?ver=4')
    expect(irA.transporte()).toBe('/transporte')
    expect(irA.transporte('choferes')).toBe('/transporte?pestana=choferes')
    expect(irA.transporte('fleteros', 4)).toBe('/transporte?pestana=fleteros&ver=4')
    expect(irA.vehiculos()).toBe('/transporte?pestana=vehiculos')
    expect(irA.vehiculos(21)).toBe('/transporte?pestana=vehiculos&ver=21')
  })

  it('🔴 ninguna ruta nueva se llama «entidades»: irA.entidad lleva cada tipo a SU pantalla', () => {
    expect(TIPOS_DE_ENTIDAD).toEqual(['clientes', 'fleteros', 'choferes', 'proveedores'])
    expect(irA.entidad('clientes', 1)).toBe('/clientes?ver=1')
    expect(irA.entidad('proveedores', 3)).toBe('/proveedores?ver=3')
    expect(irA.entidad('fleteros', 2)).toBe('/transporte?pestana=fleteros&ver=2')
    expect(irA.entidad('choferes', 11)).toBe('/transporte?pestana=choferes&ver=11')
    expect(irA.entidad('choferes')).toBe('/transporte?pestana=choferes')
    for (const tipo of TIPOS_DE_ENTIDAD) expect(irA.entidad(tipo, 5), tipo).not.toContain('/entidades')
  })

  it('🔑 el enlace viejo a /entidades va a la pantalla nueva de su pestaña, conservando la ficha', () => {
    expect(destinoDeEntidadesViejo('')).toBe('/clientes')
    expect(destinoDeEntidadesViejo('?pestana=clientes')).toBe('/clientes')
    expect(destinoDeEntidadesViejo('?pestana=clientes&ver=1')).toBe('/clientes?ver=1')
    expect(destinoDeEntidadesViejo('?pestana=proveedores&ver=3')).toBe('/proveedores?ver=3')
    expect(destinoDeEntidadesViejo('?pestana=fleteros')).toBe('/transporte?pestana=fleteros')
    expect(destinoDeEntidadesViejo('?pestana=fleteros&ver=2')).toBe('/transporte?pestana=fleteros&ver=2')
    expect(destinoDeEntidadesViejo('?pestana=choferes&ver=11')).toBe('/transporte?pestana=choferes&ver=11')
    // Sin pestaña o con una desconocida era Clientes; un `ver` que no es un id se descarta.
    expect(destinoDeEntidadesViejo('?ver=1')).toBe('/clientes?ver=1')
    expect(destinoDeEntidadesViejo('?pestana=cualquier-cosa&ver=1')).toBe('/clientes?ver=1')
    expect(destinoDeEntidadesViejo('?pestana=fleteros&ver=abc')).toBe('/transporte?pestana=fleteros')
    expect(destinoDeEntidadesViejo('?pestana=fleteros&ver=0')).toBe('/transporte?pestana=fleteros')
  })

  it('🔑 el enlace viejo a /vehiculos va a la pestaña Vehículos conservando TODO el query', () => {
    expect(destinoDeVehiculosViejo('')).toBe('/transporte?pestana=vehiculos')
    expect(destinoDeVehiculosViejo('?ver=21')).toBe('/transporte?pestana=vehiculos&ver=21')
    expect(destinoDeVehiculosViejo('?ver=21&otro=x')).toBe('/transporte?pestana=vehiculos&ver=21&otro=x')
    // Una `pestana` que traiga el enlace no pisa a Vehículos.
    expect(destinoDeVehiculosViejo('?pestana=choferes&ver=21')).toBe('/transporte?pestana=vehiculos&ver=21')
  })

  it('verValido sólo acepta un id entero positivo', () => {
    expect(verValido('7')).toBe(7)
    for (const malo of [null, '', '0', '-1', '1.5', 'abc']) expect(verValido(malo), String(malo)).toBeUndefined()
  })

  it('🔑 las secciones que salieron de Configuración apuntan al tipo de entidad, y de ahí a la pantalla de hoy', () => {
    expect(SECCIONES_MUDADAS_DE_CONFIGURACION).toEqual({ terceros: 'clientes', choferes: 'choferes' })
    expect(irA.entidad(SECCIONES_MUDADAS_DE_CONFIGURACION.terceros, 5)).toBe('/clientes?ver=5')
    expect(irA.entidad(SECCIONES_MUDADAS_DE_CONFIGURACION.choferes, 5)).toBe('/transporte?pestana=choferes&ver=5')
  })

  it('🔴 App.tsx tiene las rutas nuevas, redirige las viejas y ya no tiene pantallas de Entidades ni de Vehículos', () => {
    const app = readFileSync(resolve(process.cwd(), 'src/App.tsx'), 'utf8')
    for (const ruta of ['/clientes', '/proveedores', '/transporte']) expect(app, ruta).toContain(`path="${ruta}"`)
    expect(app).toContain('path="/entidades" element={<EntidadesAlDestinoNuevo />}')
    expect(app).toContain('path="/vehiculos" element={<VehiculosAlTransporte />}')
    expect(app).toMatch(/path="\/terceros" element=\{<Navigate/)
    expect(app).toMatch(/path="\/choferes" element=\{<Navigate/)
    expect(app).not.toContain("@/pages/Entidades")
    expect(app).not.toContain("@/pages/Vehiculos")
  })
})

describe('Cartas de porte: pestañas y titulares (ADR-044)', () => {
  it('la pestaña sale del query, y lo desconocido cae en el listado', () => {
    expect(PESTANAS_DE_CARTAS_DE_PORTE).toEqual(['cartas', 'titulares'])
    expect(pestanaDeCartasDePorte('titulares')).toBe('titulares')
    expect(pestanaDeCartasDePorte(null)).toBe('cartas')
    expect(pestanaDeCartasDePorte('cualquier-cosa')).toBe('cartas')
  })

  it('irA.titulares arma la pestaña y la ficha', () => {
    expect(irA.titulares()).toBe('/cartas-porte?pestana=titulares')
    expect(irA.titulares(3)).toBe('/cartas-porte?pestana=titulares&ver=3')
  })

  it('el log lleva el titular y su plantilla a la ficha del titular', () => {
    expect(destinoDelLog('titular_cpe', 3)).toBe('/cartas-porte?pestana=titulares&ver=3')
    expect(destinoDelLog('plantilla_cpe', 3)).toBe('/cartas-porte/titulares/3/plantilla')
    expect(destinoDelLog('titular_cpe', null)).toBeNull()
  })
})
