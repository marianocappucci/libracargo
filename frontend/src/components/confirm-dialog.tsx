import {
  AlertDialog, AlertDialogAction, AlertDialogCancel, AlertDialogContent,
  AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from '@/components/ui/alert-dialog'

// Reemplaza window.confirm() en toda la app -- modal propio del sistema en
// vez del dialog nativo del navegador, a pedido del usuario.
//
// `pending` es para una acción que tarda y que no se puede mandar dos veces:
// mientras sea `true` los dos botones quedan deshabilitados y Escape no cierra, y
// con `pending` definido (true o false) confirmar NO cierra el diálogo -- lo
// cierra quien llama cuando la acción termina, bien o mal. Sin `pending` se
// comporta como siempre: confirmar cierra y la acción sigue por su cuenta.
// Bajo `lg` los dos botones miden 44 px (el blanco táctil mínimo): son los que se tocan con el pulgar.
export function ConfirmDialog({
  open, onOpenChange, title, description, confirmLabel = 'Eliminar', cancelLabel = 'Cancelar', pending, onConfirm,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  title: string
  description?: string
  confirmLabel?: string
  cancelLabel?: string
  pending?: boolean
  onConfirm: () => void
}) {
  return (
    <AlertDialog open={open} onOpenChange={(v) => { if (!pending) onOpenChange(v) }}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description && <AlertDialogDescription>{description}</AlertDialogDescription>}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={pending} className="max-lg:h-11">{cancelLabel}</AlertDialogCancel>
          <AlertDialogAction
            disabled={pending}
            className="max-lg:h-11"
            onClick={(e) => {
              // `AlertDialogAction` cierra solo; con `pending` lo cierra quien llama.
              if (pending !== undefined) e.preventDefault()
              onConfirm()
            }}>
            {confirmLabel}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
