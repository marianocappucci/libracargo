import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post: vi.fn(), put: vi.fn(), del: vi.fn() } }
})

const { SelectLocalidad, SelectProvincia } = await import('./CamposGeo')
const { _olvidarCache } = await import('@/api/geo')

const PROVINCIAS = [
  { id: '06', nombre: 'Buenos Aires' },
  { id: '82', nombre: 'Santa Fe' },
]
const LOCALIDADES = [
  { id: '06784020', nombre: 'Suipacha', provincia_id: '06', provincia: 'Buenos Aires' },
  { id: '06215010', nombre: 'Chivilcoy', provincia_id: '06', provincia: 'Buenos Aires' },
]

function responder() {
  get.mockImplementation((ruta?: string) => {
    if (ruta?.startsWith('/api/geo/provincias')) return Promise.resolve(PROVINCIAS)
    if (ruta?.startsWith('/api/geo/localidades')) return Promise.resolve(LOCALIDADES)
    return Promise.resolve([])
  })
}

describe('CamposGeo', () => {
  beforeEach(() => { get.mockReset(); _olvidarCache(); responder() })

  it('la provincia se elige de las del catálogo', async () => {
    render(<SelectProvincia id="p" etiqueta="Provincia" valor="" alCambiar={vi.fn()} />)
    const control = await screen.findByLabelText('Provincia')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/provincias'))
    expect(control).toBeTruthy()
  })

  it('🔴 una localidad que NO está en el catálogo arranca como texto, con su valor', async () => {
    // Es el modo de falla que importa. `Cnel. Bogado` es una de las 41 filas
    // abreviadas del maestro real: si el campo arrancara como desplegable, no
    // encontraría el valor, lo mostraría vacío y **guardar sin tocar nada
    // borraría el dato**.
    render(<SelectLocalidad id="l" etiqueta="Localidad" valor="Cnel. Bogado"
                            provincia="Buenos Aires" alCambiar={vi.fn()} />)
    // Se re-consulta adentro del `waitFor`: el primer render dibuja el
    // desplegable y el efecto lo reemplaza por un input. Una referencia
    // guardada antes apunta a un nodo que ya no está en el documento, y el
    // test daría rojo con el componente funcionando bien.
    await waitFor(() => {
      const control = screen.getByLabelText('Localidad')
      expect(control.tagName).toBe('INPUT')
      expect((control as HTMLInputElement).value).toBe('Cnel. Bogado')
    })
  })

  it('una localidad que sí está en el catálogo se elige de la lista', async () => {
    // El control positivo del test de arriba: sin este, "arranca como texto"
    // pasaría igual si el campo fuera SIEMPRE texto.
    render(<SelectLocalidad id="l" etiqueta="Localidad" valor="Suipacha"
                            provincia="Buenos Aires" alCambiar={vi.fn()} />)
    await screen.findByLabelText('Localidad')
    await waitFor(() => expect(screen.getByLabelText('Localidad').tagName).not.toBe('INPUT'))
  })

  it('sin provincia elegida no se puede seleccionar la localidad, y lo dice', async () => {
    render(<SelectLocalidad id="l" etiqueta="Localidad" valor="" provincia=""
                            alCambiar={vi.fn()} />)
    expect(await screen.findByText(/Elegí la provincia/)).toBeTruthy()
  })

  it('si el catálogo no responde, la provincia se puede escribir igual', async () => {
    // No poder elegir no puede volverse no poder cargar.
    get.mockImplementation(() => Promise.reject(new Error('sin red')))
    _olvidarCache()
    render(<SelectProvincia id="p" etiqueta="Provincia" valor="Corrientes"
                            alCambiar={vi.fn()} />)
    await waitFor(() => {
      const control = screen.getByLabelText('Provincia')
      expect(control.tagName).toBe('INPUT')
      expect((control as HTMLInputElement).value).toBe('Corrientes')
    })
  })

  it('las provincias se piden una sola vez aunque haya dos campos', async () => {
    // La caché guarda la PROMESA, no el resultado: con el resultado, dos campos
    // del mismo formulario dispararían dos pedidos.
    render(
      <>
        <SelectProvincia id="p1" etiqueta="Provincia" valor="" alCambiar={vi.fn()} />
        <SelectLocalidad id="l1" etiqueta="Localidad" valor="" provincia="Buenos Aires"
                         alCambiar={vi.fn()} />
      </>,
    )
    await screen.findByLabelText('Provincia')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/geo/provincias'))
    const pedidos = get.mock.calls.filter((c) => String(c[0]).startsWith('/api/geo/provincias'))
    expect(pedidos.length).toBe(1)
  })
})
