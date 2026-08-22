// El primitivo de pestanas de shadcn/ui sobre `radix-ui`, tal como lo genera
// `shadcn add tabs` -- mismo archivo, byte a byte, que el de Contalibra.
//
// Se vendoriza el 2026-08-22 por dos motivos a la vez:
//
// 1. La Configuracion de este producto dibujaba sus pestanas con botones a
//    mano y un subrayado, porque el paquete no estaba instalado. El humano
//    pidio que se vean como las de Contalibra, y esas SON este primitivo.
// 2. 🔴 **Sin este archivo, subir el pin de `libra-ui` a v0.35.0 rompe el
//    build.** Este producto importa `DatosBackupCard` de
//    `libra-ui/Configuracion`, y desde esa version ese modulo importa
//    `@/components/ui/tabs` -- que el kit resuelve contra el CONSUMIDOR. No es
//    un error de runtime: no llega a compilar. Es la misma trampa que se comio
//    a Gestiolibra y VentaLibra con la v0.29.0.
import * as React from "react"
import { Tabs as TabsPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Tabs({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Root>) {
  return (
    <TabsPrimitive.Root
      data-slot="tabs"
      className={cn("flex flex-col gap-2", className)}
      {...props}
    />
  )
}

function TabsList({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List>) {
  return (
    <TabsPrimitive.List
      data-slot="tabs-list"
      className={cn(
        "inline-flex h-9 w-fit items-center justify-center rounded-lg bg-muted p-[3px] text-muted-foreground",
        className
      )}
      {...props}
    />
  )
}

function TabsTrigger({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger>) {
  return (
    <TabsPrimitive.Trigger
      data-slot="tabs-trigger"
      className={cn(
        "inline-flex flex-1 items-center justify-center gap-1.5 rounded-md border border-transparent px-2 py-1 text-sm font-medium whitespace-nowrap text-foreground outline-none focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:pointer-events-none disabled:opacity-50 data-[state=active]:bg-background data-[state=active]:shadow-sm dark:text-muted-foreground dark:data-[state=active]:border-input dark:data-[state=active]:bg-input/30 dark:data-[state=active]:text-foreground [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
        className
      )}
      {...props}
    />
  )
}

function TabsContent({
  className,
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content>) {
  return (
    <TabsPrimitive.Content
      data-slot="tabs-content"
      className={cn("flex-1 outline-none", className)}
      {...props}
    />
  )
}

export { Tabs, TabsList, TabsTrigger, TabsContent }
