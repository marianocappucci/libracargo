import type { ReactNode } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router-dom'

import Layout from '@/components/Layout'
import { useAuth } from '@/context/AuthContext'
import Inicio from '@/pages/Inicio'
import Caja from '@/pages/Caja'
import CartasDePorte from '@/pages/CartasDePorte'
import ComprobantesSeccion from '@/pages/ComprobantesSeccion'
import EditarPreFactura from '@/pages/EditarPreFactura'
import EmitirCartaDePorte from '@/pages/EmitirCartaDePorte'
import FacturarPendientes from '@/pages/FacturarPendientes'
import Configuracion from '@/pages/Configuracion'
import CuentaCorriente from '@/pages/CuentaCorriente'
import Login from '@/pages/Login'
import { ForgotPassword, ResetPassword } from '@/pages/PasswordReset'
import Logs from '@/pages/Logs'
import PlantillaDeTitular from '@/pages/PlantillaDeTitular'
import Ordenes from '@/pages/Ordenes'
import PreFactura from '@/pages/PreFactura'
import PreFacturas from '@/pages/PreFacturas'
import PreLiquidacionTransportistas from '@/pages/PreLiquidacionTransportistas'
import Reporte from '@/pages/Reporte'
import ReportesIndice from '@/pages/ReportesIndice'
import Usuarios from '@/pages/Usuarios'
import Entidades from '@/pages/Entidades'
import Vehiculos from '@/pages/Vehiculos'
import { Localidades, TiposCarga } from '@/pages/maestros'
import { irA } from '@/navegacion'

function Privado({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  // Mientras `GET /auth/me` está en vuelo, `user` es null — indistinguible de
  // "no autenticado". Sin esperar a `loading`, un refresh estando adentro
  // patea al login por un instante y se pierde la ruta que se estaba mirando.
  if (loading) return null
  return user ? <>{children}</> : <Navigate to="/login" replace />
}

/** `/gastos` era la pantalla de comprobantes de proveedores; hoy es la pestaña Proveedores de Comprobantes.
 *  Se redirige conservando el query, así `/gastos?ver=5` abre el 5 en su pestaña. `replace`: el enlace viejo
 *  no queda en el historial, y atrás no vuelve a rebotar. */
function GastosAProveedores() {
  const { search } = useLocation()
  // `seccion` primero, como la escribe `irA.gasto`: un solo enlace canónico.
  const params = new URLSearchParams({ seccion: 'proveedores' })
  new URLSearchParams(search).forEach((valor, clave) => {
    if (clave !== 'seccion') params.append(clave, valor)
  })
  return <Navigate to={`/comprobantes?${params}`} replace />
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      {/* Públicas, al lado del login y NO adentro de `Privado`: quien las usa
          es exactamente quien no puede entrar. Puestas del lado privado, el
          enlace del correo redirigiría a `/login` y pediría la contraseña que
          la persona justamente no tiene. */}
      <Route path="/forgot-password" element={<ForgotPassword />} />
      <Route path="/reset-password" element={<ResetPassword />} />
      <Route
        path="/*"
        element={
          <Privado>
            <Layout>
              <Routes>
                <Route path="/" element={<Inicio />} />
                <Route path="/ordenes" element={<Ordenes />} />
                <Route path="/cartas-porte" element={<CartasDePorte />} />
                {/* Formularios largos, en página propia y no en un diálogo (2026-10-09). Cuelgan de /cartas-porte: el menú
                    marca esa entrada. */}
                <Route path="/cartas-porte/emitir/:ordenId" element={<EmitirCartaDePorte />} />
                <Route path="/cartas-porte/titulares/:id/plantilla" element={<PlantillaDeTitular />} />
                <Route path="/cuentas" element={<CuentaCorriente />} />
                <Route path="/caja" element={<Caja />} />
                {/* Una entrada de menú, dos pestañas (`?seccion=`): Clientes —la ruta pelada— y Proveedores. */}
                <Route path="/comprobantes" element={<ComprobantesSeccion />} />
                <Route path="/comprobantes/facturar" element={<FacturarPendientes />} />
                {/* Las pre facturas ya no tienen entrada de menú: se llega desde Comprobantes > Clientes, y
                    «Comprobantes» queda marcada en el menú (`activoEn` con `RUTAS_DE_COMPROBANTES`). */}
                <Route path="/pre-facturas" element={<PreFacturas />} />
                <Route path="/pre-facturas/:id" element={<PreFactura />} />
                {/* Editar es la pantalla de facturar pendientes sobre una pre factura que ya existe. */}
                <Route path="/pre-facturas/:id/editar" element={<EditarPreFactura />} />
                <Route path="/gastos" element={<GastosAProveedores />} />
                <Route path="/reportes" element={<ReportesIndice />} />
                {/* Viene en bloques por transportista: no entra en la grilla genérica. Va antes que
                    `:slug`, aunque el router ya prefiere la ruta estática. */}
                <Route path="/reportes/pre-liquidacion-transportistas"
                       element={<PreLiquidacionTransportistas />} />
                <Route path="/reportes/:slug" element={<Reporte />} />
                <Route path="/usuarios" element={<Usuarios />} />
                <Route path="/logs" element={<Logs />} />
                <Route path="/configuracion" element={<Configuracion />} />
                {/* Los terceros y los choferes ya no son pantallas sueltas: son pestañas de «Entidades» (ADR-040).
                    Las rutas viejas se redirigen, que es lo que el log de actividad y los marcadores todavía usan. */}
                <Route path="/entidades" element={<Entidades />} />
                <Route path="/terceros" element={<Navigate to={irA.entidades('clientes')} replace />} />
                <Route path="/choferes" element={<Navigate to={irA.entidades('choferes')} replace />} />
                <Route path="/vehiculos" element={<Vehiculos />} />
                <Route path="/localidades" element={<Localidades />} />
                <Route path="/tipos-carga" element={<TiposCarga />} />
              </Routes>
            </Layout>
          </Privado>
        }
      />
    </Routes>
  )
}
