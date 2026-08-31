import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const put = vi.fn()
const post = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, put, post, postForm: vi.fn(), del: vi.fn() } }
})

const { FacturacionArca } = await import('./Arca')
// Resuelto una sola vez, a proposito: importarlo adentro de un test mete un
// tick en el que el pedido inicial de la pantalla se resuelve fuera de `act`.
const { ApiError } = await import('libra-ui/api-client') as unknown as {
  ApiError: new (status: number, detail: unknown) => Error
}

function fila(extra: Record<string, unknown> = {}) {
  return {
    razon_social_id: 1, razon_social: 'Suitrans', cuit: '30-11111111-1', punto_venta: 1,
    ambiente: 'homologacion', habilitado: false,
    certificado: null, tiene_clave: false, clave_nombre: null, coinciden: null,
    ...extra,
  }
}

const CERT = {
  nombre: 'suitrans.crt', sujeto: 'CN=suitrans', emisor: 'CN=ARCA',
  vence: '2028-01-15T00:00:00Z', vencido: false, dias_para_vencer: 500,
}

describe('FacturacionArca', () => {
  // Cuerpo de bloque: `mockReset()` devuelve el mock y vitest llamaria a lo
  // devuelto como hook de limpieza.
  beforeEach(() => { get.mockReset(); put.mockReset(); post.mockReset() })

  it('sin credenciales lo dice, y no deja habilitar', async () => {
    get.mockResolvedValue([fila()])
    render(<FacturacionArca />)
    expect(await screen.findByText(/Todavía no hay credenciales/)).toBeInTheDocument()
    const casilla = screen.getByLabelText('Habilitar facturación electrónica')
    expect((casilla as HTMLInputElement).disabled).toBe(true)
  })

  it('con una sola mitad dice cuál falta', async () => {
    get.mockResolvedValue([fila({ certificado: CERT })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/Falta la clave privada/)).toBeInTheDocument()
  })

  it('🔴 avisa cuando el certificado y la clave NO son pareja', async () => {
    // Es el hallazgo que ningun nombre de archivo puede dar: los dos archivos
    // son validos por separado y juntos no autentican.
    get.mockResolvedValue([fila({
      certificado: CERT, tiene_clave: true, clave_nombre: 'otra.key', coinciden: false,
    })])
    render(<FacturacionArca />)
    const alarma = await screen.findByRole('alert')
    expect(alarma.textContent).toContain('no son pareja')
  })

  it('avisa que el certificado vencio', async () => {
    get.mockResolvedValue([fila({
      certificado: { ...CERT, vencido: true, dias_para_vencer: -3, vence: '2026-08-01T00:00:00Z' },
      tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    const alarma = await screen.findByRole('alert')
    // La fecha en dd-mm-aaaa, como manda el estandar de la casa.
    expect(alarma.textContent).toContain('01-08-2026')
  })

  it('avisa ANTES de que venza, no despues', async () => {
    // Un certificado dura dos anios: el dia que vence, la facturacion deja de
    // andar sin que nadie haya tocado nada. Avisar recien ahi no sirve.
    get.mockResolvedValue([fila({
      certificado: { ...CERT, dias_para_vencer: 12 },
      tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/vence en 12 días/)).toBeInTheDocument()
  })

  it('con todo en orden lo dice, y deja habilitar', async () => {
    // El control de los de arriba: sin este, una pantalla que gritara SIEMPRE
    // pasaria igual y las alarmas dejarian de significar algo.
    get.mockResolvedValue([fila({
      certificado: CERT, tiene_clave: true, clave_nombre: 'k.key', coinciden: true,
    })])
    render(<FacturacionArca />)
    expect(await screen.findByText(/verificados/)).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    const casilla = screen.getByLabelText('Habilitar facturación electrónica')
    expect((casilla as HTMLInputElement).disabled).toBe(false)
  })

  it('sin razones sociales explica por donde empezar', async () => {
    get.mockResolvedValue([])
    render(<FacturacionArca />)
    // 🔑 No `/Razones sociales/` a secas: la aclaración del punto de venta,
    // que se muestra siempre, también nombra «Configuración → Razones
    // sociales», y con dos coincidencias `findByText` falla. Se busca la
    // frase que sólo existe en el estado vacío.
    expect(await screen.findByText(/No hay razones sociales activas/))
      .toBeInTheDocument()
  })
})


/** Lo que la sección de ARCA no tenía y el resto de la familia sí: el
 *  instructivo del certificado y una forma de preguntarle a ARCA si acepta las
 *  credenciales. Más el texto que decía que emitir no estaba, que quedó viejo
 *  cuando entró la emisión con CAE. */
describe('el instructivo y Probar conexión', () => {
  beforeEach(() => { get.mockReset(); put.mockReset(); post.mockReset() })

  /** Una razón social con el par cargado, verificado y la emisión habilitada. */
  function completa(extra: Record<string, unknown> = {}) {
    return fila({
      razon_social_id: 5, razon_social: 'Suitrans S.R.L.', habilitado: true,
      certificado: CERT, tiene_clave: true, clave_nombre: 'suitrans.key',
      coinciden: true, ...extra,
    })
  }

  function montar(filas: unknown[]) {
    get.mockResolvedValue(filas)
    render(<FacturacionArca />)
  }

  it('trae el instructivo del certificado, y es el del kit', async () => {
    montar([completa()])

    // El título del `<summary>` es literal de `libra-ui/Configuracion`: si
    // alguien reemplazara el import por un texto propio, este assert cae.
    expect(await screen.findByText(
      '¿Cómo obtener el certificado digital y la clave privada?')).toBeInTheDocument()
  })

  it('aclara dónde va el punto de venta, que el instructivo ubica en otro lado',
     async () => {
    // El paso 3 del tutorial del kit manda al campo «Punto de venta de abajo»,
    // que existe en la `ArcaCard` del kit y no en esta pantalla: acá el punto
    // de venta es de la razón social.
    montar([completa()])

    expect(await screen.findByText(/no se carga en esta pantalla/)).toBeInTheDocument()
    expect(screen.getByText(/Configuración → Razones sociales/)).toBeInTheDocument()
  })

  it('no sigue diciendo que emitir no está: este producto emite con CAE', async () => {
    montar([completa()])

    await screen.findByText('Suitrans S.R.L.')
    // 🔑 El positivo va junto al negativo: sin él, este test pasaría igual con
    // la pantalla vacía o con el párrafo entero borrado.
    expect(screen.getByText(/emite con CAE y el número se lo da ARCA/)).toBeInTheDocument()
    expect(screen.queryByText(/emitir todavía no está/)).toBeNull()
  })

  it('probar conexión pega en el endpoint de ESA razón social y cuenta el resultado',
     async () => {
    montar([completa()])
    post.mockResolvedValue({
      ok: true, ambiente: 'produccion', cuit: '30-11111111-1',
      servicio: 'wsfe', expira: '2026-08-31T23:59:59-03:00',
    })

    fireEvent.click(await screen.findByRole('button', { name: /Probar conexión/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/arca/5/probar'))
    expect(await screen.findByText(/ARCA aceptó las credenciales/)).toBeInTheDocument()
  })

  it('si ARCA rechaza, el texto de ARCA queda en pantalla', async () => {
    montar([completa()])
    post.mockRejectedValue(new ApiError(
      502, 'ARCA rechazó la autenticación: Computador no autorizado'))

    fireEvent.click(await screen.findByRole('button', { name: /Probar conexión/ }))

    // Es el motivo por el que existe el botón: distingue «el certificado no
    // está habilitado para wsfe» de un problema de armado del archivo.
    expect(await screen.findByText(/Computador no autorizado/)).toBeInTheDocument()
  })

  it('con media credencial no se ofrece probar: ARCA no tendría qué contestar',
     async () => {
    // El certificado subido y la clave no: es el estado real entre las dos
    // subidas, y el que la pantalla ya marcaba como incompleto.
    montar([completa({ tiene_clave: false, clave_nombre: null, coinciden: null,
                       habilitado: false })])

    await screen.findByText('Suitrans S.R.L.')
    expect(screen.queryByRole('button', { name: /Probar conexión/ })).toBeNull()
    // 🔑 Control positivo del selector: en ESTE mismo render hay otro botón que
    // sí depende de que haya algo cargado. Sin él, la ausencia de arriba podría
    // ser una pantalla que no renderizó nada.
    expect(screen.getByRole('button', { name: /Borrar credenciales/ })).toBeInTheDocument()
  })

  it('con el par completo el botón sí está', async () => {
    montar([completa()])
    expect(await screen.findByRole('button', { name: /Probar conexión/ }))
      .toBeInTheDocument()
  })
})
