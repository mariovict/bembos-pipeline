"""
ETL diario de ventas por local - caso academico Bembos (datos sinteticos).

Extract  : lee el CSV de ventas de los locales.
Transform: limpia los datos (duplicados, nulos, fechas y montos invalidos).
Load     : guarda el resultado en PostgreSQL y genera un reporte CSV.
"""
import os
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.types import Date

ENTRADA = Path("data/ventas_locales.csv")
SALIDA = Path("output")
COLUMNAS = ["id_venta", "fecha", "local", "producto", "cantidad", "precio_unitario"]
MAX_RECHAZO = float(os.getenv("MAX_RECHAZO", "0.30"))  # control de calidad: maximo 30 % de filas rechazadas


def crear_engine() -> Engine:
    """Crea la conexion a PostgreSQL con variables de entorno (la clave viene de Jenkins)."""
    url_completa = os.getenv("DATABASE_URL")
    if url_completa:
        return create_engine(url_completa)
    for var in ("PGUSER", "PGPASSWORD"):
        if not os.getenv(var):
            raise RuntimeError(f"Falta la variable de entorno {var}")
    url = URL.create(
        "postgresql+psycopg",
        username=os.environ["PGUSER"],
        password=os.environ["PGPASSWORD"],
        host=os.getenv("PGHOST", "localhost"),
        port=int(os.getenv("PGPORT", "5432")),
        database=os.getenv("PGDATABASE", "bembos_dataops"),
    )
    return create_engine(url)


def extract(ruta: Path) -> pd.DataFrame:
    """Lee el archivo CSV de ventas."""
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el archivo de entrada: {ruta}")
    df = pd.read_csv(ruta, encoding="utf-8")
    faltantes = set(COLUMNAS) - set(df.columns)
    if faltantes:
        raise ValueError(f"Faltan columnas en el CSV: {sorted(faltantes)}")
    return df


def transform(df: pd.DataFrame):
    """Devuelve (datos_limpios, datos_rechazados)."""
    df = df.copy()

    # 1. Estandarizar texto
    df["local"] = df["local"].astype("string").str.strip().str.title()
    df["producto"] = df["producto"].astype("string").str.strip()

    # 2. Convertir tipos (lo invalido pasa a NaT / NaN)
    df["fecha"] = pd.to_datetime(df["fecha"], format="%Y-%m-%d", errors="coerce")
    df["cantidad"] = pd.to_numeric(df["cantidad"], errors="coerce")
    df["precio_unitario"] = pd.to_numeric(df["precio_unitario"], errors="coerce")

    # 3. Eliminar duplicados por id_venta
    df = df.drop_duplicates(subset="id_venta", keep="first")

    # 4. Separar filas validas de rechazadas
    valido = (
        df["fecha"].notna()
        & df["producto"].notna()
        & (df["producto"] != "")
        & (df["cantidad"] > 0)
        & (df["precio_unitario"] > 0)
    )
    limpios = df[valido].copy()
    rechazados = df[~valido].copy()

    # 5. Columna calculada
    limpios["total"] = (limpios["cantidad"] * limpios["precio_unitario"]).round(2)
    limpios["fecha"] = limpios["fecha"].dt.date
    rechazados["fecha"] = rechazados["fecha"].dt.date
    return limpios, rechazados


def validar_calidad(filas_leidas: int, filas_validas: int, max_rechazo: float = MAX_RECHAZO) -> float:
    """Control de calidad: falla si se rechaza mas filas de lo permitido."""
    if filas_leidas == 0 or filas_validas == 0:
        raise ValueError("No quedaron filas validas despues de la limpieza.")
    ratio = (filas_leidas - filas_validas) / filas_leidas
    if ratio > max_rechazo:
        raise ValueError(f"Calidad insuficiente: {ratio:.0%} de filas rechazadas (maximo {max_rechazo:.0%}).")
    return ratio


def load(engine: Engine, limpios: pd.DataFrame, rechazados: pd.DataFrame,
         filas_leidas: int, carpeta: Path, build: str = "local") -> pd.DataFrame:
    """Guarda en la base de datos y genera los archivos de salida."""
    carpeta.mkdir(exist_ok=True)

    resumen = (
        limpios.groupby(["fecha", "local"], as_index=False)
        .agg(pedidos=("id_venta", "nunique"), unidades=("cantidad", "sum"), venta_total=("total", "sum"))
        .round(2)
    )
    auditoria = pd.DataFrame([{
        "ejecutado_en": datetime.now(),
        "build": str(build),
        "filas_leidas": filas_leidas,
        "filas_validas": len(limpios),
        "filas_rechazadas": filas_leidas - len(limpios),
        "estado": "OK",
    }])

    with engine.begin() as con:
        limpios.to_sql("ventas_limpias", con, if_exists="replace", index=False, dtype={"fecha": Date()})
        resumen.to_sql("resumen_local_dia", con, if_exists="replace", index=False, dtype={"fecha": Date()})
        auditoria.to_sql("etl_auditoria", con, if_exists="append", index=False)

    resumen.to_csv(carpeta / "reporte_ventas.csv", index=False)
    rechazados.to_csv(carpeta / "filas_rechazadas.csv", index=False)
    return resumen


def main() -> int:
    print("=== ETL Bembos (caso academico): inicio ===")
    try:
        crudo = extract(ENTRADA)
        print(f"[EXTRACT]   filas leidas: {len(crudo)}")

        limpios, rechazados = transform(crudo)
        print(f"[TRANSFORM] filas validas: {len(limpios)} | rechazadas/duplicadas: {len(crudo) - len(limpios)}")

        ratio = validar_calidad(len(crudo), len(limpios))
        print(f"[CALIDAD]   rechazo {ratio:.0%} (maximo permitido {MAX_RECHAZO:.0%}): OK")

        engine = crear_engine()
        resumen = load(engine, limpios, rechazados, len(crudo), SALIDA, os.getenv("BUILD_NUMBER", "local"))
        print(f"[LOAD]      ventas_limpias: {len(limpios)} filas | resumen_local_dia: {len(resumen)} filas | etl_auditoria: +1 fila")
        print(f"[LOAD]      venta total del periodo: S/ {limpios['total'].sum():,.2f}")
    except Exception as exc:  # el pipeline debe fallar con un mensaje claro
        print(f"[ERROR] {type(exc).__name__}: {exc}")
        return 1
    print("=== ETL Bembos: fin OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
