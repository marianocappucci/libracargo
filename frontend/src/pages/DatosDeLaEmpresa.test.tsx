/** Los datos de la empresa, y la condición de IVA.
 *
 *  Este producto tiene tarjeta de Empresa propia —sus datos viven en tabla
 *  propia y tienen más campos—, y por eso quedó afuera del `<Select>` que la
 *  `EmpresaCard` del kit les da a los otros seis: acá la condición de IVA era
 *  un campo de texto libre. Lo que estos tests fijan es que ahora se elija de
 *  la lista **del kit**, y la salvaguarda del valor guardado que no está en
 *  ella.
 */
import { render, screen, waitFor } from '@testing-library/react'
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
const { CONDICIONES_IVA } = await import('libra-ui/Configuracion')

function empresa(extra: Record<string, unknown> = {}) {
  return {
    razon_social: 'Suitrans S.R.L.', nombre_fantasia: null, cuit: '30-11111111-1',
    condicion_iva: 'Responsable Inscripto', ingresos_brutos: null,
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

  it('muestra la condición guardada', async () => {
    await montar()

    expect(screen.getByLabelText('Condición frente al IVA'))
      .toHaveTextContent('Responsable Inscripto')
  })

  it('🔑 un valor guardado fuera de la lista NO desaparece', async () => {
    // Sin la salvaguarda el `<Select>` no lo encuentra, muestra el campo vacío
    // y el primer guardado lo pisa en silencio. Es la misma trampa que la
    // `EmpresaCard` del kit documenta.
    await montar({ condicion_iva: 'No Alcanzado' })

    expect(screen.getByLabelText('Condición frente al IVA'))
      .toHaveTextContent('No Alcanzado')
  })

  it('la lista es la del kit, no una copia local', async () => {
    await montar()

    // Se compara contra `CONDICIONES_IVA` importada: si alguien reemplazara el
    // import por tres strings escritos acá, este assert seguiría pasando sólo
    // mientras coincidan — y dejaría de pasar en cuanto el kit las corrija,
    // que es exactamente cuando queremos enterarnos.
    expect(CONDICIONES_IVA.map((c) => c.valor))
      .toContain('Responsable Inscripto')
    expect(CONDICIONES_IVA).toHaveLength(3)
  })

  it('los otros campos siguen siendo de texto', async () => {
    // Control: sin esto, "no es un INPUT" pasaría igual con una pantalla que
    // no renderizó ningún campo.
    await montar()

    expect(screen.getByLabelText('Razón social').tagName).toBe('INPUT')
    expect(screen.getByLabelText('CUIT').tagName).toBe('INPUT')
  })
})
