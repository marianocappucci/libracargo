import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const postForm = vi.fn()
vi.mock('libra-ui/api-client', () => ({ api: { get, postForm } }))

const { tarifario } = await import('./tarifario')

const error = (status: number) => Object.assign(new Error(`HTTP ${status}`), { status })

beforeEach(() => { get.mockReset(); postForm.mockReset() })

describe('referencia', () => {
  it('pide los km con la fecha de la orden', async () => {
    get.mockResolvedValue({ tarifa: '23205.57' })
    await tarifario.referencia(80, '2026-09-10')
    expect(get).toHaveBeenCalledWith('/api/tarifario/referencia?km=80&fecha=2026-09-10')
  })

  it('sin fecha no manda el parámetro: rige el tarifario de hoy', async () => {
    get.mockResolvedValue({ tarifa: '23205.57' })
    await tarifario.referencia(80)
    expect(get).toHaveBeenCalledWith('/api/tarifario/referencia?km=80')
  })

  it('🔑 un 404 es «no hay tarifario» y vuelve null; cualquier otro error se propaga', async () => {
    get.mockRejectedValueOnce(error(404))
    await expect(tarifario.referencia(80, '2026-09-10')).resolves.toBeNull()
    get.mockRejectedValueOnce(error(500))
    await expect(tarifario.referencia(80, '2026-09-10')).rejects.toThrow('HTTP 500')
  })
})

describe('sugerencia', () => {
  it('pide el último viaje del cliente, y un 404 es «no tiene» (null)', async () => {
    get.mockResolvedValueOnce({ porcentaje: '85.00' })
    await expect(tarifario.sugerencia(5)).resolves.toEqual({ porcentaje: '85.00' })
    expect(get).toHaveBeenCalledWith('/api/tarifario/sugerencia?cliente_id=5')
    get.mockRejectedValueOnce(error(404))
    await expect(tarifario.sugerencia(5)).resolves.toBeNull()
  })
})

describe('cargar', () => {
  const archivo = new File(['80;23.205,57\n'], 'tarifario.csv', { type: 'text/csv' })

  it('manda el CSV, la vigencia y el nombre como multipart; el valor de estadía sólo si hay', async () => {
    postForm.mockResolvedValue({ id: 1 })
    await tarifario.cargar({ archivo, vigencia: '2026-04-10', nombre: 'Abril 2026', valorEstadia: ' 214.146,67 ' })
    const [ruta, cuerpo] = postForm.mock.calls[0] as [string, FormData]
    expect(ruta).toBe('/api/tarifario')
    expect(cuerpo.get('archivo')).toBeInstanceOf(File)
    expect(cuerpo.get('vigencia')).toBe('2026-04-10')
    expect(cuerpo.get('nombre')).toBe('Abril 2026')
    // Tal cual lo escribió, sin el espacio de los costados: el servidor entiende `214.146,67`.
    expect(cuerpo.get('valor_estadia')).toBe('214.146,67')

    await tarifario.cargar({ archivo, vigencia: '2026-04-10', nombre: 'Abril 2026', valorEstadia: '  ' })
    expect((postForm.mock.calls[1][1] as FormData).has('valor_estadia')).toBe(false)
  })
})
