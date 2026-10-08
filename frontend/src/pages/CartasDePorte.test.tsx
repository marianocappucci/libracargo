import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const get = vi.fn()
const post = vi.fn()
const put = vi.fn()
vi.mock('libra-ui/api-client', async () => {
  class ApiError extends Error {
    status: number
    detail: unknown
    constructor(status: number, detail: unknown) {
      super(String(detail)); this.status = status; this.detail = detail
    }
  }
  return { ApiError, api: { get, post, put, del: vi.fn(), postForm: vi.fn() } }
})

// Un operador cualquiera: la pantalla es de staff, no de administración.
vi.mock('@/context/AuthContext', () => ({
  useAuth: () => ({ user: { role: 'operador', name: 'Ana' }, loading: false, logout: vi.fn() }),
}))

const { default: CartasDePorte } = await import('./CartasDePorte')
const { NAV_SECCIONES } = await import('@/components/Layout')

const parte = (cuit: string | null, nombre: string | null = null) => ({ cuit, nombre })

/** Una CPE como la devuelve el backend: abierta, con los kilos de carga y sin descarga. */
function carta(id: number, extra: Record<string, unknown> = {}) {
  return {
    id, nro_ctg: 10123456780 + id, numero: `00001-0007241${id}`, estado: 'AC', estado_descripcion: 'Activa',
    fecha_inicio_estado: null,
    fecha_emision: '2026-10-05T14:30:00', fecha_vencimiento: '2026-10-08T14:30:00',
    fecha_partida: '2026-10-05T16:00:00-03:00',
    cuit_representada: '30222222223', ambiente: 'produccion',
    transportista: parte('30222222223', 'Suitrans'), pagador_flete: parte('30111111118'),
    chofer: parte('20333333336'), origen: parte('30444444441'), destino: parte('30555555558'),
    destinatario: parte('30555555558'), dominios: ['AB123CD', 'EF456GH'],
    cod_grano: 15, cosecha: 2526,
    peso_bruto: 44000, peso_tara: 14500, peso_neto: 29500,
    peso_bruto_descarga: null, peso_tara_descarga: null, peso_neto_descarga: null,
    cod_provincia_origen: 12, cod_localidad_origen: 3456, cod_provincia_destino: 20, cod_localidad_destino: 777,
    planta_destino: 9, km: 320, tarifa: '45678.50', tiene_pdf: false, tiene_descarga: false,
    consultada_en: '2026-10-06T09:00:00', orden_carga_id: null, guardada_id: null,
    ...extra,
  }
}

const REPRESENTADOS = {
  ambiente: 'produccion',
  cuits: [{ cuit: '30222222223', nombre: 'Suitrans SRL' }, { cuit: '30999999995', nombre: null }],
}

type Respuestas = {
  lista?: unknown[]
  representados?: unknown | Error
}

async function error(status: number, detail: string) {
  const { ApiError } = await import('libra-ui/api-client')
  return new (ApiError as unknown as new (s: number, d: string) => Error)(status, detail)
}

function responder({ lista = [], representados = REPRESENTADOS }: Respuestas = {}) {
  get.mockImplementation((ruta?: string) => {
    if (ruta === '/api/cartas-porte/representados') {
      return representados instanceof Error ? Promise.reject(representados) : Promise.resolve(representados)
    }
    if (ruta?.startsWith('/api/cartas-porte')) return Promise.resolve(lista)
    return Promise.resolve([])
  })
}

function abrir() {
  render(
    <MemoryRouter initialEntries={['/cartas-porte']}>
      <Routes>
        <Route path="/cartas-porte" element={<CartasDePorte />} />
        <Route path="/ordenes" element={<p>Pantalla de órdenes</p>} />
      </Routes>
    </MemoryRouter>)
}

beforeEach(() => {
  get.mockReset(); post.mockReset(); put.mockReset()
  responder()
})

describe('Cartas de porte · listado', () => {
  it('lista cada carta con su CTG, número, emisión, estado, pagador, chofer, dominios y kilos', async () => {
    responder({
      lista: [
        carta(1, { pagador_flete: parte('30111111118', 'Agro Norte SA'), chofer: parte('20333333336', 'Juan Pérez') }),
        carta(2, {
          estado: 'DD', estado_descripcion: 'Descargada', tiene_descarga: true,
          peso_bruto_descarga: 44100, peso_tara_descarga: 14600, peso_neto_descarga: 29500,
          orden_carga_id: 12,
        }),
      ],
    })
    abrir()

    expect(await screen.findByText('10123456781')).toBeInTheDocument()
    expect(screen.getByText('10123456782')).toBeInTheDocument()
    expect(screen.getByText('00001-00072411')).toBeInTheDocument()
    expect(screen.getAllByText('05-10-2026')).toHaveLength(2)
    expect(screen.getByText('Activa')).toBeInTheDocument()
    expect(screen.getByText('Descargada')).toBeInTheDocument()
    // El pagador: el nombre si el CUIT está cargado, y si no el CUIT con guiones.
    expect(screen.getByText('Agro Norte SA')).toBeInTheDocument()
    expect(screen.getByText('30-11111111-8')).toBeInTheDocument()
    // El chofer: el CUIT formateado, y el nombre si viene.
    expect(screen.getByText('Juan Pérez')).toBeInTheDocument()
    expect(screen.getAllByText('20-33333333-6')).toHaveLength(2)
    expect(screen.getAllByText('AB123CD, EF456GH')).toHaveLength(2)
    // Kilos netos: los de carga con separador de miles; los de descarga, o que están pendientes.
    expect(screen.getAllByText('29.500').length).toBeGreaterThanOrEqual(3)
    expect(screen.getByText('pendiente')).toBeInTheDocument()
    // La orden vinculada es un enlace a la orden; sin vínculo, «—».
    expect(screen.getByRole('link', { name: '12' })).toHaveAttribute('href', '/ordenes?ver=12')
    expect(screen.getAllByText('—').length).toBeGreaterThanOrEqual(1)
  })

  it('una carta anulada no queda esperando una descarga que no va a llegar', async () => {
    responder({ lista: [carta(1, { estado: 'AN', estado_descripcion: 'Anulada' })] })
    abrir()
    await screen.findByText('Anulada')
    expect(screen.queryByText('pendiente')).toBeNull()
  })

  it('«Sólo abiertas» pide ?abiertas=true, y destildarlo vuelve a pedirlas todas', async () => {
    responder({ lista: [carta(1)] })
    abrir()
    await screen.findByText('10123456781')
    expect(get).toHaveBeenLastCalledWith('/api/cartas-porte')

    fireEvent.click(screen.getByLabelText('Sólo abiertas'))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/cartas-porte?abiertas=true'))
    fireEvent.click(screen.getByLabelText('Sólo abiertas'))
    await waitFor(() => expect(get).toHaveBeenLastCalledWith('/api/cartas-porte'))
  })

  it('sin cartas lo dice, y con el filtro puesto dice otra cosa', async () => {
    abrir()
    expect(await screen.findByText(/Todavía no hay cartas de porte/)).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('Sólo abiertas'))
    expect(await screen.findByText('No hay cartas de porte abiertas.')).toBeInTheDocument()
  })

  it('si el servidor falla, muestra el motivo', async () => {
    get.mockRejectedValue(await error(500, 'se cayó'))
    abrir()
    expect(await screen.findByRole('alert')).toHaveTextContent('se cayó')
  })

  it('el botón PDF sólo aparece en las cartas que lo tienen, y abre otra pestaña', async () => {
    responder({ lista: [carta(1), carta(2, { tiene_pdf: true })] })
    abrir()
    await screen.findByText('10123456781')
    const pdf = screen.getByRole('link', { name: 'PDF' })
    expect(screen.getAllByRole('link', { name: 'PDF' })).toHaveLength(1)
    expect(pdf).toHaveAttribute('href', '/api/cartas-porte/2/pdf')
    expect(pdf).toHaveAttribute('target', '_blank')
  })

  it('hacer click en una fila abre el detalle con los kilos de carga y de descarga', async () => {
    responder({ lista: [carta(1)] })
    abrir()
    fireEvent.click(await screen.findByText('10123456781'))
    const detalle = await screen.findByRole('dialog')
    expect(within(detalle).getByText('Carta de porte 00001-00072411')).toBeInTheDocument()
    expect(within(detalle).getByText('44.000')).toBeInTheDocument()
    expect(within(detalle).getByText('14.500')).toBeInTheDocument()
    expect(within(detalle).getByText('pendiente')).toBeInTheDocument()
    // La partida viene con zona (-03:00) y se lee en hora de Argentina.
    expect(within(detalle).getByText('05-10-2026 16:00')).toBeInTheDocument()
  })

  it('🔑 una carta anulada dice desde cuándo, en hora de Argentina: su PDF es del día de la emisión', async () => {
    responder({ lista: [carta(1, {
      estado: 'AN', estado_descripcion: 'Anulada', tiene_pdf: true, fecha_inicio_estado: '2026-10-07T18:45:00+00:00',
    })] })
    abrir()
    fireEvent.click(await screen.findByText('10123456781'))
    const detalle = await screen.findByRole('dialog')
    expect(within(detalle).getByText('Anulada')).toBeInTheDocument()
    expect(within(detalle).getByText('desde 07-10-2026 15:45')).toBeInTheDocument()
    // La emisión sigue siendo la del PDF: otra fecha, la de antes.
    expect(within(detalle).getByText('05-10-2026 14:30')).toBeInTheDocument()
  })

  it('sin fecha de inicio del estado no inventa un «desde»', async () => {
    responder({ lista: [carta(1)] })
    abrir()
    fireEvent.click(await screen.findByText('10123456781'))
    const detalle = await screen.findByRole('dialog')
    expect(within(detalle).queryByText(/^desde /)).toBeNull()
  })
})

describe('Cartas de porte · acciones de la fila', () => {
  it('«Actualizar» vuelve a consultar esa carta y deja la fila con lo nuevo', async () => {
    responder({ lista: [carta(1)] })
    post.mockResolvedValue(carta(1, {
      estado: 'DD', estado_descripcion: 'Descargada', tiene_descarga: true,
      peso_bruto_descarga: 44100, peso_tara_descarga: 14600, peso_neto_descarga: 29500,
    }))
    abrir()
    await screen.findByText('Activa')

    fireEvent.click(screen.getByLabelText('Actualizar'))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/cartas-porte/1/actualizar', {}))
    expect(await screen.findByText('Descargada')).toBeInTheDocument()
    expect(screen.queryByText('pendiente')).toBeNull()
    expect(screen.getByRole('status')).toHaveTextContent('CTG 10123456781 actualizada')
  })

  it('si ARCA no contesta al actualizar, muestra el motivo y deja la fila como estaba', async () => {
    responder({ lista: [carta(1)] })
    post.mockRejectedValue(await error(502, 'ARCA no da acceso'))
    abrir()
    await screen.findByText('Activa')
    fireEvent.click(screen.getByLabelText('Actualizar'))
    expect(await screen.findByRole('alert')).toHaveTextContent('ARCA no da acceso')
    expect(screen.getByText('Activa')).toBeInTheDocument()
  })

  it('«Vincular orden» manda el N.º de orden y muestra el vínculo', async () => {
    responder({ lista: [carta(1)] })
    put.mockResolvedValue(carta(1, { orden_carga_id: 45 }))
    abrir()
    await screen.findByText('Activa')

    fireEvent.click(screen.getByLabelText('Vincular orden'))
    const dialogo = await screen.findByRole('dialog')
    // Sin número no se puede vincular, y no hay nada que desvincular.
    expect(within(dialogo).getByRole('button', { name: 'Vincular' })).toBeDisabled()
    expect(within(dialogo).queryByRole('button', { name: 'Desvincular' })).toBeNull()

    fireEvent.change(within(dialogo).getByLabelText('N.º de orden'), { target: { value: '45' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Vincular' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/cartas-porte/1/orden', { orden_carga_id: 45 }))
    expect(await screen.findByRole('link', { name: '45' })).toHaveAttribute('href', '/ordenes?ver=45')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('una orden que no existe se lee en el diálogo, que sigue abierto', async () => {
    responder({ lista: [carta(1)] })
    put.mockRejectedValue(await error(404, 'no existe la orden 999'))
    abrir()
    await screen.findByText('Activa')
    fireEvent.click(screen.getByLabelText('Vincular orden'))
    const dialogo = await screen.findByRole('dialog')
    fireEvent.change(within(dialogo).getByLabelText('N.º de orden'), { target: { value: '999' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Vincular' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('no existe la orden 999')
  })

  it('una carta vinculada se puede desvincular', async () => {
    responder({ lista: [carta(1, { orden_carga_id: 45 })] })
    put.mockResolvedValue(carta(1, { orden_carga_id: null }))
    abrir()
    await screen.findByRole('link', { name: '45' })

    fireEvent.click(screen.getByLabelText('Vincular orden'))
    const dialogo = await screen.findByRole('dialog')
    expect(within(dialogo).getByLabelText('N.º de orden')).toHaveValue(45)
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Desvincular' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('/api/cartas-porte/1/orden', { orden_carga_id: null }))
    await waitFor(() => expect(screen.queryByRole('link', { name: '45' })).toBeNull())
  })
})

describe('Cartas de porte · actualizar abiertas', () => {
  it('muestra cuántas se actualizaron y los errores de las que no', async () => {
    responder({ lista: [carta(1)] })
    post.mockResolvedValue({
      actualizadas: 3, errores: [{ ctg: 10123456785, error: 'ARCA no la encuentra' }],
    })
    abrir()
    await screen.findByText('Activa')
    get.mockClear()

    fireEvent.click(screen.getByRole('button', { name: /Actualizar abiertas/ }))

    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/cartas-porte/actualizar-abiertas', {}))
    const resumen = await screen.findByRole('status', { name: 'Resumen de la actualización' })
    expect(resumen).toHaveTextContent('Se actualizaron 3 cartas de porte; 1 con error.')
    expect(resumen).toHaveTextContent('10123456785')
    expect(resumen).toHaveTextContent('ARCA no la encuentra')
    // Y el listado se vuelve a pedir, para ver lo que cambió.
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/cartas-porte'))
  })
})

describe('Cartas de porte · Traer de ARCA', () => {
  async function abrirTraer() {
    abrir()
    fireEvent.click(await screen.findByRole('button', { name: /Traer de ARCA/ }))
    return await screen.findByRole('dialog')
  }

  it('🔑 «Consultar como» arranca sin elegir y Guardar no se habilita hasta elegirlo', async () => {
    const dialogo = await abrirTraer()
    const select = await within(dialogo).findByLabelText('Consultar como')
    // Sin valor por defecto, aunque haya un solo CUIT. Muestra el nombre y, si no hay, el CUIT con guiones.
    expect(select).toHaveValue('')
    expect(within(dialogo).getByRole('option', { name: 'Suitrans SRL' })).toBeInTheDocument()
    expect(within(dialogo).getByRole('option', { name: '30-99999999-5' })).toBeInTheDocument()

    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781' } })
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeDisabled()
    expect(within(dialogo).getByRole('button', { name: 'Ver antes de guardar' })).toBeDisabled()

    fireEvent.change(select, { target: { value: '30222222223' } })
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeEnabled()
    expect(within(dialogo).getByRole('button', { name: 'Ver antes de guardar' })).toBeEnabled()
  })

  it('con un solo CUIT tampoco lo elige solo', async () => {
    responder({ representados: { ambiente: 'produccion', cuits: [{ cuit: '30222222223', nombre: null }] } })
    const dialogo = await abrirTraer()
    expect(await within(dialogo).findByLabelText('Consultar como')).toHaveValue('')
  })

  it('el ambiente va en texto chico, y homologación se resalta porque no tiene CPE reales', async () => {
    let dialogo = await abrirTraer()
    expect(await within(dialogo).findByText('Ambiente: producción')).toBeInTheDocument()
    expect(within(dialogo).queryByText(/no tiene CPE reales/)).toBeNull()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    responder({ representados: { ...REPRESENTADOS, ambiente: 'homologacion' } })
    fireEvent.click(screen.getByRole('button', { name: /Traer de ARCA/ }))
    dialogo = await screen.findByRole('dialog')
    expect(await within(dialogo).findByText('Homologación: no tiene CPE reales')).toBeInTheDocument()
  })

  it('🔑 un 409 de representados muestra el detalle y no deja seguir', async () => {
    responder({
      representados: await error(409, 'No hay certificado de ARCA: cargalo en Configuración / ARCA'),
    })
    const dialogo = await abrirTraer()
    expect(await within(dialogo).findByRole('alert'))
      .toHaveTextContent('cargalo en Configuración / ARCA')
    expect(within(dialogo).queryByLabelText('Consultar como')).toBeNull()
    expect(within(dialogo).queryByLabelText('CTG')).toBeNull()
    expect(within(dialogo).queryByRole('button', { name: 'Guardar' })).toBeNull()
  })

  it('un 502 de representados también se explica, y se puede reintentar', async () => {
    responder({ representados: await error(502, 'ARCA no da acceso ahora') })
    const dialogo = await abrirTraer()
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('ARCA no da acceso ahora')

    responder()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Reintentar' }))
    expect(await within(dialogo).findByLabelText('Consultar como')).toBeInTheDocument()
  })

  it('lee varios CTG: quita los repetidos y no deja guardar con uno que no tiene 11 dígitos', async () => {
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    const campo = within(dialogo).getByLabelText('CTG')

    // Separados por espacio, coma y renglón; uno repetido; uno corto.
    fireEvent.change(campo, {
      target: { value: '10123456781 10123456782,10123456781\n10123456783, 1234' },
    })
    expect(within(dialogo).getByText(/3 CTG/)).toHaveTextContent('se quitó 1 repetido')
    expect(within(dialogo).getByRole('alert')).toHaveTextContent('Un CTG tiene 11 dígitos. No sirve: 1234')
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeDisabled()
    // Con varios no hay vista previa.
    expect(within(dialogo).queryByRole('button', { name: 'Ver antes de guardar' })).toBeNull()

    fireEvent.change(campo, { target: { value: '10123456781 10123456782,10123456781\n10123456783' } })
    expect(within(dialogo).queryByRole('alert')).toBeNull()
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeEnabled()
  })

  it('el tope es de 50 CTG por vez', async () => {
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    const ctgs = Array.from({ length: 51 }, (_, i) => String(10000000000 + i)).join(' ')
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: ctgs } })
    expect(within(dialogo).getByRole('alert')).toHaveTextContent('hasta 50 CTG')
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeDisabled()
  })

  it('«Ver antes de guardar» muestra la vista previa con los kilos, sin guardar nada', async () => {
    post.mockResolvedValue(carta(1, {
      id: null, tiene_descarga: true,
      peso_bruto_descarga: 44100, peso_tara_descarga: 14600, peso_neto_descarga: 29500,
      pagador_flete: parte('30111111118', 'Agro Norte SA'),
    }))
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Ver antes de guardar' }))

    const vista = await within(dialogo).findByRole('region', { name: 'Vista previa' })
    expect(post).toHaveBeenCalledTimes(1)
    expect(post).toHaveBeenCalledWith('/api/cartas-porte/consultar', {
      ctg: 10123456781, cuit_representada: '30222222223',
    })
    expect(within(vista).getByText('00001-00072411')).toBeInTheDocument()
    expect(within(vista).getByText('Activa')).toBeInTheDocument()
    expect(within(vista).getByText('Agro Norte SA (30-11111111-8)')).toBeInTheDocument()
    expect(within(vista).getByText('AB123CD, EF456GH')).toBeInTheDocument()
    // Origen y destino: el CUIT y los códigos de ARCA.
    expect(within(vista).getByText('30-44444444-1 · Provincia 12 · Localidad 3456')).toBeInTheDocument()
    expect(within(vista).getByText('30-55555555-8 · Provincia 20 · Localidad 777 · Planta 9')).toBeInTheDocument()
    // Kilos de carga y de descarga: bruto, tara y neto.
    for (const kilos of ['44.000', '14.500', '29.500', '44.100', '14.600']) {
      expect(within(vista).getAllByText(kilos).length).toBeGreaterThanOrEqual(1)
    }
    expect(within(vista).getAllByText('29.500')).toHaveLength(2)
    expect(within(vista).getByText('$ 45.678,50')).toBeInTheDocument()
    expect(within(vista).queryByText(/Ya está guardada/)).toBeNull()
  })

  it('si la carta ya estaba guardada, la vista previa avisa que se va a actualizar', async () => {
    post.mockResolvedValue(carta(1, { id: null, guardada_id: 7 }))
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Ver antes de guardar' }))
    expect(await within(dialogo).findByText('Ya está guardada: se va a actualizar')).toBeInTheDocument()
  })

  it('un 404 o un 409 de la consulta se muestran, y no hay vista previa', async () => {
    post.mockRejectedValue(await error(409, 'El CUIT 30222222223 no tiene delegación'))
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Ver antes de guardar' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('no tiene delegación')
    expect(within(dialogo).queryByRole('region', { name: 'Vista previa' })).toBeNull()
  })

  it('🔑 Guardar muestra el resultado de cada CTG, con su error si no se pudo, y refresca el listado', async () => {
    post.mockResolvedValue([
      { ctg: 10123456781, id: 1, error: null },
      { ctg: 10123456782, id: null, error: 'ARCA no tiene esa carta de porte' },
    ])
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781, 10123456782' } })
    get.mockClear()
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Guardar' }))

    const resultado = await within(dialogo).findByRole('region', { name: 'Resultado' })
    expect(post).toHaveBeenCalledWith('/api/cartas-porte', {
      ctgs: [10123456781, 10123456782], cuit_representada: '30222222223',
    })
    expect(resultado).toHaveTextContent('Se guardó 1 carta de porte; 1 con error.')
    const filas = within(resultado).getAllByRole('listitem')
    expect(filas[0]).toHaveTextContent('10123456781 — guardada')
    expect(filas[1]).toHaveTextContent('10123456782 — ARCA no tiene esa carta de porte')
    await waitFor(() => expect(get).toHaveBeenCalledWith('/api/cartas-porte'))
    // Ya se guardó: no se puede apretar dos veces.
    expect(within(dialogo).getByRole('button', { name: 'Guardar' })).toBeDisabled()
  })

  it('un 409 al guardar (falta la delegación) corta todo y se lee', async () => {
    post.mockRejectedValue(await error(409, 'El CUIT no tiene delegación'))
    const dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.change(within(dialogo).getByLabelText('CTG'), { target: { value: '10123456781 10123456782' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Guardar' }))
    expect(await within(dialogo).findByRole('alert')).toHaveTextContent('El CUIT no tiene delegación')
    expect(within(dialogo).queryByRole('region', { name: 'Resultado' })).toBeNull()
  })

  it('cada vez que se abre arranca limpio: el CUIT vuelve a quedar sin elegir', async () => {
    let dialogo = await abrirTraer()
    fireEvent.change(await within(dialogo).findByLabelText('Consultar como'), { target: { value: '30222222223' } })
    fireEvent.click(within(dialogo).getByRole('button', { name: 'Cancelar' }))
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())

    fireEvent.click(screen.getByRole('button', { name: /Traer de ARCA/ }))
    dialogo = await screen.findByRole('dialog')
    expect(await within(dialogo).findByLabelText('Consultar como')).toHaveValue('')
  })
})

describe('Cartas de porte · el menú', () => {
  it('la entrada está cerca de Órdenes de carga, justo después, y lleva a /cartas-porte', () => {
    const items = NAV_SECCIONES.flatMap((s) => s.items)
    const posicion = items.findIndex((i) => i.to === '/ordenes')
    expect(items[posicion + 1]).toMatchObject({ to: '/cartas-porte', label: 'Cartas de porte' })
  })
})
