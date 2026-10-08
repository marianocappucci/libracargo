import { useCallback, useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'

import { listarPorRol } from '@/api/maestros'

/** Los fleteros (bajas incluidas), para elegir uno por nombre en el formulario de un chofer o de un vehículo. Si el pedido
 *  falla queda la lista vacía, y el formulario sigue con el número: no vale romper una pantalla por un desplegable. */
export function useFleteros(): { id: number; razon_social: string }[] {
  const [fleteros, setFleteros] = useState<{ id: number; razon_social: string }[]>([])
  useEffect(() => {
    let vigente = true
    listarPorRol('fletero')
      .then((filas) => {
        if (!vigente || !Array.isArray(filas)) return
        setFleteros(filas.flatMap((f) =>
          typeof f.razon_social === 'string' ? [{ id: f.id, razon_social: f.razon_social }] : []))
      })
      .catch(() => {})
    return () => { vigente = false }
  }, [])
  return fleteros
}

/** La ficha abierta por la URL (`?ver=7`): qué fila abrir, y cómo borrar el parámetro al cerrarla — con `replace`, así
 *  atrás no la vuelve a abrir. Respeta el resto del query (`pestana`, `seccion`). */
export function useFichaEnLaUrl(): { abrirId: number | null; alCerrarFicha: () => void } {
  const [params, setParams] = useSearchParams()
  const ver = Number(params.get('ver'))
  const abrirId = params.get('ver') && Number.isInteger(ver) && ver > 0 ? ver : null
  const alCerrarFicha = useCallback(() => {
    setParams((previos) => {
      const nuevos = new URLSearchParams(previos)
      nuevos.delete('ver')
      return nuevos
    }, { replace: true })
  }, [setParams])
  return { abrirId, alCerrarFicha }
}
