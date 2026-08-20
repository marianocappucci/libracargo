// Shim sobre libra-ui/AuthContext (mismo patrón que el resto de la familia).
// La instancia pre-configurada apunta a /auth/me, /auth/login y /auth/logout,
// que son exactamente las rutas que monta `build_json_api_auth_router` en el
// backend.
export { AuthProvider, useAuth } from 'libra-ui/AuthContext'
