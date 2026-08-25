"""El enum de medios de pago, contra el vocabulario de la familia.

🔴 **Este producto NO tiene una divergencia de grafías, y este test existe para
que siga así.** El barrido del 2026-08-24 encontró la lista declarada 28 veces
en 11 repos, con seis formas de divergencia; acá los cuatro valores del enum
—`efectivo`, `transferencia`, `cheque`, `otro`— son claves que la familia
conoce. No hubo nada que renombrar.

## Por qué el enum no se ensancha

`MedioPago` es un **tipo de PostgreSQL** (`sa.Enum(..., name="medio_pago")`,
migración `0001`) sobre una columna con datos. Agregarle los medios que este
producto no usa —MercadoPago, las tarjetas, Cuenta DNI— sería un `ALTER TYPE`
sobre una base viva **para ofrecer opciones que una agencia de cargas no cobra**.
El subconjunto es una decisión de producto, igual que en [[libraclub]]; lo que
la normalización exige no es adoptarlo todo, es **no inventar claves**.

## ⚠️ La tensión que queda: `otro`

`otro` está en `medios_pago.HISTORICOS`, no en `ELEGIBLES` — o sea que la
familia lo trata como algo que **se lee y no se escribe**, y este producto lo
escribe. Es la única discrepancia y no se resuelve acá porque las dos salidas
cuestan datos:

- meter `otro` en `ELEGIBLES` lo vuelve elegible **en los once repos**, y un
  cajón de sastre disponible en todas partes vacía de sentido a la lista
  controlada;
- migrar las filas de LibraCargo exige decidir a qué medio va cada una, que es
  información que la fila no tiene.

Queda anotado acá y en `wiki/concepts/medios-de-pago-familia-libra.md`. Este
test **no lo tapa**: lo nombra.
"""
from libracore import medios_pago

from app.models.enums import MedioPago

#: `otro` es el cajón de sastre de este producto. Ver el docstring.
EXCEPCION_DECLARADA = {"otro"}


def test_ningun_valor_del_enum_es_inventado():
    """🔴 **El trinquete.** Un valor nuevo que la familia no conozca —un
    `tarjeta` a secas, por ejemplo— entra al enum y de ahí a la columna, y a
    partir de ese momento sacarlo cuesta un `ALTER TYPE` y una migración de
    datos. Este test lo frena antes de que haya filas."""
    desconocidos = [
        m.value for m in MedioPago
        if m.value not in medios_pago.CONOCIDOS and m.value not in EXCEPCION_DECLARADA
    ]
    assert desconocidos == [], (
        f"medios que la familia no conoce: {desconocidos}. "
        "Si es deliberado, agregarlo a `libracore.medios_pago` primero."
    )
    # Control positivo: un enum vacío pasaría el filtro sin medir nada.
    assert len(list(MedioPago)) >= 4


def test_los_tres_que_se_cobran_son_claves_elegibles_de_la_familia():
    """No `CONOCIDOS` sino `ELEGIBLES`: son medios que este producto **escribe**,
    así que tienen que estar en la lista de lo que se puede elegir hoy, no en la
    de lo que sólo se sabe leer."""
    for valor in ("efectivo", "transferencia", "cheque"):
        assert medios_pago.es_elegible(valor), valor


def test_otro_sigue_siendo_la_unica_excepcion():
    """🔴 El control de la excepción. Sin esto, `EXCEPCION_DECLARADA` se podría
    ir llenando de valores inventados y el trinquete de arriba no se enteraría —
    que es exactamente cómo una lista de excepciones deja de servir."""
    assert EXCEPCION_DECLARADA == {"otro"}
    # Y sigue siendo una grafía que la familia sabe leer, no una inventada.
    assert medios_pago.label("otro") == "Otro"
    assert not medios_pago.es_elegible("otro")
