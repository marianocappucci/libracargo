/** El botón «Consultar en ARCA»: llama al endpoint del motor, precarga sin pisar lo escrito y, si falta habilitar el
 *  servicio de Padrón, manda al tutorial de Configuración. */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { URL_TUTORIAL_PADRON } from '@/api/consultar-cuit'
import { condicionDeArca } from '@/pages/maestros/definiciones'

import { ConsultarEnArca } from './ConsultarEnArca'

const PERSONA = {
  nombre: 'ACME SA', domicilio: 'Ruta 8 km 5, Pilar, Buenos Aires',
  iva_condition: 'Responsable Inscripto', estado: 'ACTIVO',
}
const DESTINO = {
  nombre: { campo: 'razon_social', etiqueta: 'Razón social' },
  domicilio: { campo: 'direccion', etiqueta: 'Dirección' },
  iva: { campo: 'condicion_iva', etiqueta: 'Condición de IVA' },
}

const respuesta = (estado: number, cuerpo: unknown) =>
  Promise.resolve({ ok: estado >= 200 && estado < 300, status: estado, json: () => Promise.resolve(cuerpo) } as Response)

/** Un formulario mínimo: el estado vive acá, como en `AbmMaestro`, y se ve lo que quedó cargado. */
function Formulario({ inicial = {}, porDefecto }: { inicial?: Record<string, unknown>; porDefecto?: Record<string, unknown> }) {
  const [v, setV] = useState<Record<string, unknown>>({ cuit: '30-71111111-4', ...inicial })
  return (
    <div>
      <ConsultarEnArca cuit={v.cuit} valores={v} destino={DESTINO} ivaDe={condicionDeArca} porDefecto={porDefecto}
                       alAplicar={(c) => setV((a) => ({ ...a, ...c }))} />
      <span aria-label="razon">{String(v.razon_social ?? '')}</span>
      <span aria-label="direccion">{String(v.direccion ?? '')}</span>
      <span aria-label="iva">{String(v.condicion_iva ?? '')}</span>
    </div>
  )
}

const fetchMock = vi.fn()
beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock) })
afterEach(() => vi.unstubAllGlobals())

const consultar = () => fireEvent.click(screen.getByRole('button', { name: /Consultar en ARCA/ }))

describe('Consultar en ARCA', () => {
  it('pide el CUIT en dígitos al endpoint del motor y precarga razón social, dirección y condición de IVA', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario />)
    consultar()
    await waitFor(() => expect(screen.getByLabelText('razon')).toHaveTextContent('ACME SA'))
    expect(fetchMock).toHaveBeenCalledWith('/api/consultar-cuit/30711111114', { credentials: 'include' })
    expect(screen.getByLabelText('direccion')).toHaveTextContent('Ruta 8 km 5, Pilar, Buenos Aires')
    // La condición se guarda con el valor del enum del producto, no con el texto de ARCA.
    expect(screen.getByLabelText('iva')).toHaveTextContent('responsable_inscripto')
    expect(screen.getByRole('status')).toHaveTextContent('Datos importados desde ARCA — Estado: ACTIVO.')
  })

  it('no pisa lo que el usuario ya escribió: lo muestra y deja elegir', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario inicial={{ razon_social: 'Acme S.A. (mi nombre)' }} />)
    consultar()
    // Lo vacío se completa; lo escrito queda como estaba.
    await waitFor(() => expect(screen.getByLabelText('direccion')).toHaveTextContent('Ruta 8'))
    expect(screen.getByLabelText('razon')).toHaveTextContent('Acme S.A. (mi nombre)')
    const grupo = screen.getByRole('group', { name: /distintos de los cargados/ })
    expect(grupo).toHaveTextContent('Razón social: ACME SA')

    fireEvent.click(screen.getByRole('button', { name: 'Reemplazar con los de ARCA' }))
    expect(screen.getByLabelText('razon')).toHaveTextContent('ACME SA')
    expect(screen.queryByRole('group', { name: /distintos/ })).toBeNull()
  })

  it('en un alta, un valor que todavía es el inicial (la condición de IVA arranca en consumidor final) no cuenta como escrito', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario inicial={{ condicion_iva: 'consumidor_final' }} porDefecto={{ condicion_iva: 'consumidor_final' }} />)
    consultar()
    await waitFor(() => expect(screen.getByLabelText('iva')).toHaveTextContent('responsable_inscripto'))
    expect(screen.queryByRole('group', { name: /distintos/ })).toBeNull()
  })

  it('al editar (sin valores iniciales) una condición ya cargada sí se pregunta antes de cambiarla', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario inicial={{ condicion_iva: 'consumidor_final' }} />)
    consultar()
    expect(await screen.findByRole('group', { name: /distintos/ })).toHaveTextContent('Condición de IVA')
    expect(screen.getByLabelText('iva')).toHaveTextContent('consumidor_final')
  })

  it('«Dejar los míos» cierra el aviso sin tocar nada', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario inicial={{ razon_social: 'Mi nombre' }} />)
    consultar()
    fireEvent.click(await screen.findByRole('button', { name: 'Dejar los míos' }))
    expect(screen.getByLabelText('razon')).toHaveTextContent('Mi nombre')
    expect(screen.queryByRole('group', { name: /distintos/ })).toBeNull()
  })

  it('si lo escrito es lo mismo que informa ARCA (aunque cambien mayúsculas) no pregunta nada', async () => {
    fetchMock.mockReturnValue(respuesta(200, PERSONA))
    render(<Formulario inicial={{ razon_social: 'acme sa', direccion: 'Ruta 8 km 5, Pilar, Buenos Aires' }} />)
    consultar()
    await waitFor(() => expect(screen.getByLabelText('iva')).toHaveTextContent('responsable_inscripto'))
    expect(screen.queryByRole('group', { name: /distintos/ })).toBeNull()
  })

  it('una condición de IVA sin equivalente en el producto no se toca', async () => {
    fetchMock.mockReturnValue(respuesta(200, { ...PERSONA, iva_condition: 'IVA No Responsable' }))
    render(<Formulario />)
    consultar()
    await waitFor(() => expect(screen.getByLabelText('razon')).toHaveTextContent('ACME SA'))
    expect(screen.getByLabelText('iva')).toHaveTextContent('')
  })

  it('con el CUIT incompleto no llama al servidor', async () => {
    render(<Formulario inicial={{ cuit: '30-7111' }} />)
    consultar()
    expect(await screen.findByRole('alert')).toHaveTextContent('Ingresá un CUIT de 11 dígitos antes de consultar.')
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('503: dice que faltan los certificados y enlaza al tutorial de Configuración', async () => {
    fetchMock.mockReturnValue(respuesta(503, {
      error: 'Configurá los certificados ARCA en Configuración para habilitar la consulta de CUIT.' }))
    render(<Formulario />)
    consultar()
    const alerta = await screen.findByRole('alert')
    expect(alerta).toHaveTextContent('Configurá los certificados ARCA en Configuración')
    expect(screen.getByRole('link', { name: /Cómo habilitar el servicio de Padrón/ }))
      .toHaveAttribute('href', URL_TUTORIAL_PADRON)
  })

  it('403: el certificado no tiene acceso a Padrón, y también enlaza al tutorial', async () => {
    fetchMock.mockReturnValue(respuesta(403, {
      error: 'El certificado no tiene acceso al servicio de Padrón (ws_sr_padron_a13). Ingresá a ARCA…' }))
    render(<Formulario />)
    consultar()
    expect(await screen.findByRole('alert')).toHaveTextContent('no tiene acceso al servicio de Padrón')
    expect(screen.getByRole('link', { name: /Cómo habilitar el servicio de Padrón/ })).toBeInTheDocument()
  })

  it('un 403 que no es del motor (falta de permiso) no manda al tutorial del padrón', async () => {
    fetchMock.mockReturnValue(respuesta(403, { detail: 'No tenés permiso' }))
    render(<Formulario />)
    consultar()
    expect(await screen.findByRole('alert')).toHaveTextContent('No tenés permiso')
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('404: el CUIT no está en el padrón; es un dato, no un problema de configuración, así que sin enlace', async () => {
    fetchMock.mockReturnValue(respuesta(404, { error: 'CUIT no encontrado en el padrón de ARCA.' }))
    render(<Formulario />)
    consultar()
    expect(await screen.findByRole('alert')).toHaveTextContent('CUIT no encontrado en el padrón de ARCA.')
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('si no hay red lo dice, y el botón vuelve a quedar disponible', async () => {
    fetchMock.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<Formulario />)
    consultar()
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo conectar con ARCA.')
    expect(screen.getByRole('button', { name: /Consultar en ARCA/ })).toBeEnabled()
  })
})
