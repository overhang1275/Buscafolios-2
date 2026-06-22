# Busca Folios

Aplicacion de escritorio para Windows y Linux que cruza folios de reposicion contra archivos TXT/CSV grandes usando DuckDB, sin cargar el archivo completo en memoria.

## Requisitos

- Python 3.13
- DuckDB
- PySide6
- Pandas solo para vista previa y exportacion XLSX

## Ejecutar

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -e .
.\.venv\Scripts\python -m busca_folios.app
```

En Linux:

```bash
python3.13 -m venv .venv
. .venv/bin/activate
pip install -e .
python -m busca_folios.app
```

## Notas de rendimiento

- DuckDB lee los archivos directo desde disco con `read_csv`.
- Los cruces se hacen con SQL (`JOIN`, `ANTI JOIN`, CTE).
- Los folios se tratan como texto para conservar ceros a la izquierda.
- `encontrados.csv` conserva todas las columnas originales del archivo de produccion.
- `no_encontrados.csv` contiene solo los folios no hallados.
- XLSX tiene limite fisico de 1,048,576 filas por hoja; la app divide en hojas cuando exporta.

## Distribucion Windows

Instala Inno Setup 6 y ejecuta:

```bat
build.bat
```

PyInstaller genera `dist\Busca Folios\Busca Folios.exe`. Si Inno Setup esta disponible, tambien genera el instalador en `dist\installer\BuscaFoliosSetup.exe`.
