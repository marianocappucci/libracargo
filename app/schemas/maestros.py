"""Esquemas de entrada y salida de los maestros.

> 🔑 **`activo` es uniforme en la API aunque no lo sea en la base.**
> `localidades` y `razones_sociales` tienen la columna en femenino (`activa`);
> las otras cuatro, en masculino. Exponer esa diferencia obligaría a cada
> consumidor a saber de memoria cuál es cuál, y la primera pantalla que se
> equivoque va a mostrar todo como inactivo sin fallar. El mapeo vive acá, en
> un solo lugar, y hay tests que lo prueban en las dos direcciones.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import CondicionIVA

#: Longitudes tomadas del modelo. Repetirlas acá no es duplicar por gusto: sin
#: esto el rechazo llega recién de la base, como un 500 con el nombre de una
#: restricción, en vez de un 422 que dice qué campo y por qué.
CUIT = Field(default=None, max_length=13)


def _vacio_es_nulo(v):
    """Un campo de texto que el formulario manda vacío es ausencia, no `""`.

    Sin esto, dos altas sin CUIT guardan `''` las dos y chocan contra cualquier
    restricción de unicidad sobre esa columna — mientras que `NULL` no colisiona
    con `NULL` en PostgreSQL.
    """
    if isinstance(v, str) and not v.strip():
        return None
    return v.strip() if isinstance(v, str) else v


class _Base(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)


# ------------------------------------------------------------------ terceros

class TerceroIn(_Base):
    razon_social: str = Field(min_length=1, max_length=120)
    cuit: str | None = CUIT
    condicion_iva: CondicionIVA = CondicionIVA.CONSUMIDOR_FINAL
    es_cliente: bool = False
    es_fletero: bool = False
    es_proveedor: bool = False
    direccion: str | None = Field(default=None, max_length=160)
    codigo_postal: str | None = Field(default=None, max_length=12)
    localidad: str | None = Field(default=None, max_length=80)
    provincia: str | None = Field(default=None, max_length=60)
    telefono: str | None = Field(default=None, max_length=40)
    celular: str | None = Field(default=None, max_length=40)
    email: str | None = Field(default=None, max_length=120)
    contacto: str | None = Field(default=None, max_length=80)
    observaciones: str | None = None
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)

    # `model_validator` y no `field_validator`: un validador de campo NO corre
    # cuando el campo no viene en el cuerpo y se usa el default, que es
    # exactamente el caso que hay que atajar -- un alta que no menciona ningun
    # rol. Con `field_validator` el test de esto pasaba en verde sin validar.
    @model_validator(mode="after")
    def _al_menos_un_rol(self):
        """Un tercero sin ningún rol no aparece en ninguna pantalla.

        En el legado eran tres maestros separados y el rol era implícito. Acá
        la tabla es una sola, así que el rol es un dato y puede quedar vacío por
        descuido: la fila existe, no se puede elegir en ningún lado, y nadie
        entiende por qué.
        """
        if not (self.es_cliente or self.es_fletero or self.es_proveedor):
            raise ValueError(
                "el tercero tiene que ser al menos una cosa: cliente, fletero o proveedor"
            )
        return self


class TerceroOut(TerceroIn):
    id: int
    origen_legado: str | None = None


# --------------------------------------------------------------- localidades

class LocalidadIn(_Base):
    nombre: str = Field(min_length=1, max_length=80)
    provincia: str | None = Field(default=None, max_length=60)
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)


class LocalidadOut(LocalidadIn):
    id: int


# ------------------------------------------------------------------ choferes

class ChoferIn(_Base):
    nombre: str = Field(min_length=1, max_length=120)
    dni: str | None = Field(default=None, max_length=15)
    telefono: str | None = Field(default=None, max_length=40)
    fletero_id: int | None = None
    observaciones: str | None = None
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)


class ChoferOut(ChoferIn):
    id: int
    origen_legado: str | None = None


# ----------------------------------------------------------------- vehiculos

class VehiculoIn(_Base):
    patente_chasis: str = Field(min_length=1, max_length=12)
    patente_acoplado: str | None = Field(default=None, max_length=12)
    fletero_id: int | None = None
    observaciones: str | None = None
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)

    @field_validator("patente_chasis", "patente_acoplado", mode="after")
    @classmethod
    def _mayusculas(cls, v):
        """Las patentes se guardan en mayúsculas.

        Sin esto `AB123CD` y `ab123cd` son dos vehículos distintos para la
        restricción de unicidad, y el mismo camión entra dos veces.
        """
        return v.upper() if v else v


class VehiculoOut(VehiculoIn):
    id: int


# ---------------------------------------------------------- razones sociales

class RazonSocialIn(_Base):
    nombre: str = Field(min_length=1, max_length=120)
    cuit: str | None = CUIT
    condicion_iva: CondicionIVA = CondicionIVA.RESPONSABLE_INSCRIPTO
    punto_venta: int = Field(default=1, ge=1)
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)


class RazonSocialOut(RazonSocialIn):
    id: int
    codigo_legado: int | None = None


# --------------------------------------------------------------- tipos carga

class TipoCargaIn(_Base):
    nombre: str = Field(min_length=1, max_length=80)
    unidad_default: str | None = Field(default=None, max_length=20)
    activo: bool = True

    _limpiar = field_validator("*", mode="before")(_vacio_es_nulo)


class TipoCargaOut(TipoCargaIn):
    id: int
