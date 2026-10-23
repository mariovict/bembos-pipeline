import pandas as pd
import pytest
from sqlalchemy import create_engine, text

from etl_ventas import load, transform, validar_calidad


def _fila(**kw):
    base = dict(id_venta=1, fecha="2026-10-20", local="Surco",
                producto="Papas fritas", cantidad=2, precio_unitario=7.5)
    base.update(kw)
    return base


def test_elimina_duplicados():
    limpios, _ = transform(pd.DataFrame([_fila(), _fila()]))
    assert len(limpios) == 1


def test_rechaza_cantidad_o_precio_invalido():
    df = pd.DataFrame([_fila(id_venta=1, cantidad=-1), _fila(id_venta=2, precio_unitario=0)])
    limpios, rechazados = transform(df)
    assert limpios.empty
    assert len(rechazados) == 2


def test_rechaza_fecha_invalida_y_producto_vacio():
    df = pd.DataFrame([_fila(id_venta=1, fecha="20/13/2026"), _fila(id_venta=2, producto=None)])
    limpios, rechazados = transform(df)
    assert limpios.empty
    assert len(rechazados) == 2


def test_calcula_total_y_estandariza_local():
    limpios, _ = transform(pd.DataFrame([_fila(local="  san miguel ", cantidad=3, precio_unitario=4.5)]))
    assert limpios.iloc[0]["total"] == 13.5
    assert limpios.iloc[0]["local"] == "San Miguel"


def test_calidad_falla_si_rechazo_es_alto():
    with pytest.raises(ValueError):
        validar_calidad(filas_leidas=10, filas_validas=5, max_rechazo=0.30)
    assert validar_calidad(10, 9, 0.30) == pytest.approx(0.1)


def test_load_guarda_en_base_de_datos(tmp_path):
    engine = create_engine("sqlite://")
    limpios, rechazados = transform(pd.DataFrame([_fila(id_venta=1), _fila(id_venta=2, local="Miraflores")]))
    load(engine, limpios, rechazados, filas_leidas=2, carpeta=tmp_path, build="7")
    with engine.connect() as con:
        assert con.execute(text("select count(*) from ventas_limpias")).scalar() == 2
        assert con.execute(text("select count(*) from resumen_local_dia")).scalar() == 2
        assert con.execute(text("select build from etl_auditoria")).scalar() == "7"
