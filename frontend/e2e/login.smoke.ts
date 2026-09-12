import { expect, test, type Page } from '@playwright/test'

// Lo único que un unitario no puede ver: que la SPA construida, servida por la
// app real, deje entrar y muestre una pantalla de dominio. Si el bundle quedó
// viejo, si el gate de Términos tapa todo, si el login devuelve HTML por el
// catch-all en vez de JSON, esto se pone rojo y los unitarios no.
//
// Los campos se ubican por los `id` que pone `createLogin` de libra-ui
// (`#username`, `#password`): `getByLabel('Contraseña')` matchea también al
// botón «Mostrar contraseña», y el nombre del producto es un wordmark, no un
// heading accesible. La primera pantalla se reconoce por el sidebar de libra-ui
// (`data-sidebar="sidebar"`) y por su título.
//
// El captcha ALTCHA (2026-09-12, libraauth v0.40.0): «Ingresar» queda
// deshabilitado hasta tildar «No soy un robot» y que el navegador termine la
// prueba de trabajo. Se resuelve el desafío real que emite la app, como el
// humano: es lo único que prueba que el worker del widget carga bajo la CSP.
async function pasarElCaptcha(page: Page) {
  const ingresar = page.getByRole('button', { name: 'Ingresar' })
  await expect(ingresar).toBeDisabled()
  await expect(page.getByRole('checkbox', { name: /No soy un robot/ })).toBeVisible()
  // 🔴 Click en el LABEL y no en el `<input>`: altcha le superpone el `<svg>`
  // del tilde, y Playwright se queda reintentando ("svg intercepts pointer
  // events") hasta el timeout. El label es lo que clickea el humano y está
  // asociado al checkbox, así que lo tilda igual.
  await page.locator('altcha-widget').getByText('No soy un robot').click()
  await expect(ingresar).toBeEnabled({ timeout: 30_000 })
}

test('entra por /login, acepta los Términos y ve la primera pantalla', async ({ page }) => {
  await page.goto('/login')
  await expect(page.getByRole('button', { name: 'Ingresar' })).toBeVisible()

  await page.locator('#username').fill(process.env.SMOKE_USER ?? 'admin')
  await page.locator('#password').fill(process.env.SMOKE_PASSWORD ?? '')
  await pasarElCaptcha(page)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page).toHaveURL(/\/$/)

  // Una instancia recién nacida pone el gate de Términos y Condiciones delante
  // de todo (libraauth v0.34.0, libra-ui GateTerminos): es lo que ve un cliente
  // nuevo, y lo que en agosto dejó las ocho demos "vacías" sin que ningún
  // unitario lo viera. El smoke lo atraviesa como el humano: tilda, acepta.
  await expect(page.getByRole('heading', { name: /Términos y Condiciones/ })).toBeVisible()
  await page.getByRole('checkbox', { name: /Leí y acepto/ }).check()
  await page.getByRole('button', { name: 'Aceptar y continuar' }).click()

  await expect(page.locator('[data-sidebar="sidebar"]').first()).toBeVisible()
  await expect(page.getByText('LibraCargo', { exact: true }).first()).toBeVisible()
  await expect(page.locator('#username')).toHaveCount(0)
})

test('una credencial mala no entra (control)', async ({ page }) => {
  // Sin esto el test de arriba podría pasar con un login que acepte cualquier
  // cosa; el rechazo tiene que verse en la pantalla, no sólo en la API.
  await page.goto('/login')
  await page.locator('#username').fill('admin')
  await page.locator('#password').fill('esta-no-es')
  // Con el captcha resuelto: el rechazo tiene que ser por la clave, no por él.
  await pasarElCaptcha(page)
  await page.getByRole('button', { name: 'Ingresar' }).click()
  await expect(page).toHaveURL(/\/login/)
  await expect(page.locator('p.text-destructive')).toBeVisible()
  await expect(page.locator('#username')).toBeVisible()
})
