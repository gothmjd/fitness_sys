# FitPlate · Plan semanal saludable (Flask + MySQL + PDF)

CRUD dinámico (Python/Flask) con MySQL, formulario temático "saludable y fitness",
reporte de consejos y descarga en PDF. Datos ficticios, uso lúdico.

## Estructura
```
app.py            # backend: CRUD, cálculo de costes, reporte y PDF
templates/        # base.html, index.html, reporte.html
requirements.txt
schema.sql        # opcional (la app crea la tabla sola)
.env.example
```

## 1) Base de datos MySQL
Vercel **no aloja MySQL**: usa un MySQL en la nube (Aiven, TiDB Cloud, Railway, Clever Cloud, etc.)
y crea una base de datos llamada `fitplate`. La tabla `plan_semanal` se crea automáticamente.

## 2) Probar en local
```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export DB_HOST=localhost DB_USER=root DB_PASSWORD=tu_clave DB_NAME=fitplate DB_SSL=false
python app.py        # http://127.0.0.1:5000
```

## 3) Publicar en Vercel
1. Sube la carpeta a un repositorio de GitHub (no subas `.env`).
2. En vercel.com → *Add New Project* → importa el repo (Vercel detecta Flask con `app.py`).
3. En *Settings → Environment Variables* agrega: `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`,
   `DB_NAME`, `DB_SSL=true` (si tu proveedor exige TLS) y `SECRET_KEY`.
4. *Deploy*. (También puedes usar `npm i -g vercel && vercel --prod`.)

## Cómo funciona
- **Coste diario** = desayuno + comida + cena + snack (se calcula en el servidor y se guarda).
- **Budget semanal** = `SUM(coste_diario)` de todos los días registrados.
- **Add / Update / Delete / Find**: botones del formulario. Find filtra por cualquier campo que llenes.
  Para actualizar o borrar, pulsa ✏️ en la fila (carga el registro en el formulario).
- **Reporte**: `/reporte` (vista) y `/reporte.pdf` (descarga) con consejos de alimentación,
  ejercicio, descanso y presupuesto. Los umbrales de presupuesto están en `BUDGET_BAJO` y `BUDGET_ALTO` (`app.py`).
