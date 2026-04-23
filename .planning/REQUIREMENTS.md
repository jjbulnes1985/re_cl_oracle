# Requirements: RE_CL

> Plataforma para detectar inmuebles subvalorados en Chile mediante scoring explicable, mapas de calor y análisis cuantitativo institucional.

## Funcionales

### RF-01 Ingesta de datos transaccionales
El sistema debe poder cargar el dataset CSV del CBR (~1M registros) en PostgreSQL con PostGIS, procesando en chunks para manejar el tamaño del archivo.

### RF-02 Limpieza y normalización
El sistema debe detectar y corregir la escala de Real_Value (pesos vs UF), deduplicar por rol+fecha, imputar superficies nulas y detectar outliers de precio.

### RF-03 Feature engineering
El sistema debe calcular brechas de precio (Real vs Calculated), percentiles por comuna/tipología, precios unitarios UF/m² y variables espaciales (distancia a centroide comunal, clustering).

### RF-04 Modelo hedónico de valoración
El sistema debe entrenar un modelo XGBoost que prediga el precio justo (UF/m²) a partir de atributos del inmueble, con RMSE < 30% del precio mediano por tipología.

### RF-05 Opportunity Score explicable
Cada inmueble debe recibir un score de oportunidad (0-1) compuesto por: undervaluation_score, data_confidence. El score debe incluir SHAP top-3 features como drivers explicables.

### RF-06 Mapa de calor interactivo
El sistema debe generar un mapa Folium con heatmap de scores por coordenadas, filtrable por tipología (Apartments, Residential, Land).

### RF-07 Ranking comunal
El sistema debe calcular y mostrar un ranking de comunas por score mediano, volumen de transacciones y % de propiedades subvaloradas.

### RF-08 Dashboard Streamlit
El sistema debe ofrecer una interfaz con: filtros laterales, mapa embebido, tabla de ranking, ficha de activo con comparables y panel de calidad de datos.

### RF-09 API REST básica
El sistema debe exponer endpoints GET /properties (con filtros) y GET /scores/{id} para consumo externo.

### RF-10 Trazabilidad de modelos
Cada score debe registrar la versión del modelo, timestamp y features SHAP en la tabla model_scores para auditoría completa.

## No funcionales

### RNF-01 Performance de ingesta
La carga de ~1M registros debe completarse en menos de 10 minutos.

### RNF-02 Seguridad de credenciales
Nunca hardcodear credenciales. Usar .env + python-dotenv. .env no debe commitearse.

### RNF-03 Reproducibilidad
Todos los pipelines ETL deben ser idempotentes y reproducibles desde cero con `docker-compose up`.

### RNF-04 Robustez de datos
El sistema debe asumir datos sucios: duplicados, nulos, escalas inconsistentes, outliers. Nunca tratar el dato como perfecto.
