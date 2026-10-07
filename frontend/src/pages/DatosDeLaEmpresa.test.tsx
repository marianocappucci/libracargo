/** Los datos de la empresa, y la condición de IVA.
 *
 *  La empresa es el emisor de toda la instancia (ADR-035) y su condición de IVA es **la enumeración del
 *  tercero** (`responsable_inscripto`, `monotributo`...), no texto libre: de ella depende qué clase de
 *  comprobante se puede emitir. Lo que estos tests fijan es que se elija de esa lista, que lo guardado se
 *  muestre con su etiqueta y que al guardar viaje el **valor del enum**.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, put, post: vi.fn(), del: vi.fn(), postForm: vi.fn() } }
})

const { DatosDeLaEmpresa } = await import('./DatosDeLaEmpresa')
const { CONDICIONES_IVA } = await import('./maestros/definiciones')

function empresa(extra: Record<string, unknown> = {}) {
  return {
    razon_social: 'Transportes de Prueba SRL', nombre_fantasia: null, cuit: '30-55667788-9',
    condicion_iva: 'responsable_inscripto', ingresos_brutos: null,
    inicio_actividades: null, domicilio: null, localidad: null, provincia: null,
    codigo_postal: null, telefono: null, email: null, sitio_web: null,
    pie_de_impresion: null, tiene_logo: false, ...extra,
  }
}

async function montar(extra: Record<string, unknown> = {}) {
  get.mockResolvedValue(empresa(extra))
  render(<DatosDeLaEmpresa />)
  await waitFor(() => expect(screen.getByLabelText('Razón social')).toBeInTheDocument())
}

describe('la condición de IVA', () => {
  beforeEach(() => { get.mockReset(); put.mockReset() })

  it('se elige de una lista, no se tipea', async () => {
    await montar()

    const control = screen.getByLabelText('Condición frente al IVA')
    // Un `<Select>` de shadcn anuncia `combobox`; un `<input>` de texto no.
    expect(control).toHaveAttribute('role', 'combobox')
    expect(control.tagName).not.toBe('INPUT')
  })

  it('muestra la condición guardada con su etiqueta', async () => {
    await montar()

    expect(screen.getByLabelText('Condición frente al IVA'))
      .toHaveTextContent('Responsable inscripto')
  })

  it('sin condición cargada pide elegir una', async () => {
    await montar({ condicion_iva: null })

    expect(screen.getByLabelText('Condición frente al IVA')).toHaveTextContent('Elegí una')
  })

  it('la lista es la del tercero (el enum del backend), no la del kit', async () => {
    // Los valores son los de `app/models/enums.py`: la del kit usa las etiquetas como valor.
    expect(CONDICIONES_IVA.map((c) => c.valor)).toEqual([
      'responsable_inscripto', 'monotributo', 'exento', 'consumidor_final', 'no_categorizado',
    ])
  })

  it('al guardar viaja el valor del enum, no la etiqueta', async () => {
    put.mockImplementation((_ruta: string, cuerpo: unknown) => Promise.resolve(cuerpo))
    await montar({ condicion_iva: 'monotributo' })

    fireEvent.click(screen.getByText('Guardar'))

    await waitFor(() => expect(put).toHaveBeenCalled())
    expect(put.mock.calls[0][0]).toBe('/api/configuracion')
    expect(put.mock.calls[0][1]).toMatchObject({ condicion_iva: 'monotributo', cuit: '30-55667788-9' })
  })

  it('los otros campos siguen siendo de texto', async () => {
    // Control: sin esto, "no es un INPUT" pasaría igual con una pantalla que
    // no renderizó ningún campo.
    await montar()

    expect(screen.getByLabelText('Razón social').tagName).toBe('INPUT')
    expect(screen.getByLabelText('CUIT').tagName).toBe('INPUT')
  })
})
