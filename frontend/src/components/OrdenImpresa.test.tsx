import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('libra-ui/api-client', () => ({
  api: { get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn() },
}))

const { OrdenImpresa } = await import('./OrdenImpresa')

const OPCIONES = {
  clientes: [{ id: 1, etiqueta: 'Agro del Oeste' }],
  fleteros: [{ id: 2, etiqueta: 'Transportes Aguirre' }],
  localidades: [{ id: 3, etiqueta: 'Suipacha' }, { id: 4, etiqueta: 'Rosario' }],
  choferes: [{ id: 5, etiqueta: 'Ramón Ferreyra' }],
  vehiculos: [{ id: 6, etiqueta: 'AB123CD' }],
  tipos: [{ id: 7, etiqueta: 'Cereal' }],
  razones: [{ id: 8, etiqueta: 'Suitrans' }],
}

const ORDEN = {
  id: 4337, fecha: '2026-07-29', cliente_id: 1, origen_id: 3, destino_id: 4,
  fletero_id: 2, chofer_id: 5, vehiculo_id: 6, tipo_carga_id: 7, razon_social_id: 8,
  remito: '0001-00012345', cantidad: '30.360', unidad: 'tn',
  tarifa: '585778.00', alicuota_iva: '21.00', iva: '123013.38', total: '708791.38',
  comision: '468622.38', estado: 'facturada' as const, comprobante_id: 741,
  observaciones: 'Descargar por portón trasero', cantidad_legado: null,
  origen_legado: 'carga:4339',
}

const EMPRESA = {
  razon_social: 'Suitrans SRL', nombre_fantasia: 'Suitrans', cuit: '30-71234567-9',
  condicion_iva: 'Responsable Inscripto', ingresos_brutos: null,
  inicio_actividades: null, domicilio: 'San Martín 450', localidad: 'Suipacha',
  provincia: 'Buenos Aires', codigo_postal: null, telefono: '2324-441122',
  email: null, sitio_web: null, pie_de_impresion: 'Documento no válido como factura.',
  tiene_logo: false,
}

describe('OrdenImpresa', () => {
  it('el papel lleva el membrete de la empresa, no una constante', () => {
    render(<OrdenImpresa orden={ORDEN} opciones={OPCIONES} empresa={EMPRESA} />)
    const hoja = document.getElementById('hoja-impresa')!
    expect(hoja.textContent).toContain('Suitrans')
    expect(hoja.textContent).toContain('San Martín 450, Suipacha, Buenos Aires')
    expect(hoja.textContent).toContain('CUIT 30-71234567-9')
    expect(hoja.textContent).toContain('Documento no válido como factura.')
  })

  it('trae los datos del viaje y los importes en pesos', () => {
    render(<OrdenImpresa orden={ORDEN} opciones={OPCIONES} empresa={EMPRESA} />)
    const hoja = document.getElementById('hoja-impresa')!
    expect(hoja.textContent).toContain('ORDEN DE CARGA')
    expect(hoja.textContent).toContain('Nº 00004337')
    expect(hoja.textContent).toContain('Agro del Oeste')
    expect(hoja.textContent).toContain('Transportes Aguirre')
    expect(hoja.textContent).toContain('Ramón Ferreyra')
    expect(hoja.textContent).toContain('30.360 tn')
    expect(hoja.textContent).toContain('$ 708.791,38')
    // Las dos firmas: sin ellas es una ficha impresa, no un remito.
    expect(hoja.textContent).toContain('Firma y aclaración del transportista')
    expect(hoja.textContent).toContain('Recibí conforme')
  })

  it('🔑 sin configuración cargada, el papel sale igual', () => {
    // Lo que no puede pasar es que no se pueda imprimir una orden porque falta
    // un dato de configuracion: el remito lo necesita el camion que esta
    // esperando.
    const vacia = { ...EMPRESA, razon_social: '', nombre_fantasia: null, cuit: null,
                    domicilio: null, localidad: null, provincia: null, telefono: null,
                    pie_de_impresion: null }
    render(<OrdenImpresa orden={ORDEN} opciones={OPCIONES} empresa={vacia} />)
    const hoja = document.getElementById('hoja-impresa')!
    expect(hoja.textContent).toContain('ORDEN DE CARGA')
    expect(hoja.textContent).toContain('Agro del Oeste')
  })

  it('un dato que falta se ve como falta, no como vacío', () => {
    // Un guion dice "esto no tiene valor"; un hueco en blanco parece un error
    // de impresion.
    render(<OrdenImpresa orden={{ ...ORDEN, remito: null, chofer_id: null }}
                         opciones={OPCIONES} empresa={EMPRESA} />)
    expect(document.getElementById('hoja-impresa')!.textContent).toContain('—')
  })

  it('no se ve en pantalla: la clase la esconde hasta imprimir', () => {
    render(<OrdenImpresa orden={ORDEN} opciones={OPCIONES} empresa={EMPRESA} />)
    expect(document.getElementById('hoja-impresa')!.className).toContain('hoja-impresa')
  })
})
