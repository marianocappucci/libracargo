// La identidad visual de LibraCargo: como se escribe el nombre.
//
// Vive en un archivo propio porque lo usan las DOS superficies que lo muestran
// -- el login y la sidebar -- y son shims distintos sobre `libra-ui`. Con la
// definicion repetida en cada uno, alcanza con tocar una para que las dos
// pantallas dejen de coincidir, que es el tipo de divergencia que nadie
// reporta porque nunca se ven juntas.
//
// La marca (el icono sobre el cuadrado del color) ya no esta aca: sale de
// `libra-ui/identidad` (ADR-033), se pasa como `producto="libracargo"` a `Layout` y
// `Login`, y el logo ilustrado `logo-libracargo.png` se retiro.

/**
 * Familia, peso y color del nombre del producto. Igual en los seis productos
 * de la suite (pedido del humano, 2026-08-16).
 *
 * El TAMANO no esta aca: es lo unico que cambia entre las dos superficies
 * (22 px en el login, 15 px en la sidebar), y meterlo obligaria a que una de
 * las dos lo pise igual.
 *
 * `text-[#2d2d2d]` es un color literal y no un token del tema a proposito: es
 * el color de la marca, no el del texto de la interfaz.
 */
export const WORDMARK = 'font-montserrat font-bold text-[#2d2d2d] dark:text-neutral-100'
