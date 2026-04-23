# RE_CL — Notebooks de Análisis

Notebooks exploratorios para la plataforma RE_CL. Compatibles con VS Code (Jupyter extension) y Jupytext.

## Cómo ejecutar

```bash
# Desde el directorio re_cl/
cd re_cl

# Opción 1: VS Code — abrir el archivo .py, verás las celdas # %% directamente
# Opción 2: Convertir a .ipynb con Jupytext
pip install jupytext
jupytext --to notebook notebooks/01_exploratory_analysis.py
jupyter notebook notebooks/01_exploratory_analysis.ipynb

# Opción 3: Ejecutar como script Python normal
python notebooks/01_exploratory_analysis.py
```

## Prerequisitos

1. Base de datos corriendo: `docker-compose up -d`
2. Pipeline completo ejecutado (al menos hasta `opportunity_score.py`)
3. Variables de entorno configuradas en `.env`

```bash
pip install -r requirements.txt
pip install jupytext matplotlib seaborn  # extras para notebooks
```

## Notebooks disponibles

| Archivo | Descripción |
|---------|-------------|
| `01_exploratory_analysis.py` | EDA completo: precios, geografía, scores, comunas, OSM coverage |

## Secciones del notebook 01

1. Setup & conexion DB
2. Resumen del dataset (conteos, rangos de fecha)
3. Distribucion de precios (histograma UF/m2, box por tipo)
4. Geografia (scatter lat/lon coloreado por score)
5. Analisis por comuna (top 10 por score mediano)
6. Gap analysis (distribucion gap_pct, zona subvalorada)
7. Features del modelo (matriz de correlacion)
8. Score analysis (distribucion, SHAP drivers)
9. Antiguedad (distribucion por ano de construccion)
10. OSM coverage (cobertura de features de proximidad)
