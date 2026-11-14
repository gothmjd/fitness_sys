"""
FitPlate - Planificador semanal saludable (CRUD Flask + MySQL + reporte PDF)
Datos ficticios, uso lúdico.
"""
import io
import os
import ssl
import unicodedata
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation

import pymysql
from flask import (Flask, flash, redirect, render_template, request,
                   send_file, url_for)
from fpdf import FPDF
from pymysql.cursors import DictCursor

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me")

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
FOOD_FIELDS = ["desayuno", "comida", "cena", "snack"]
COST_FIELDS = ["coste_desayuno", "coste_comida", "coste_cena", "coste_snack"]
TEXT_FIELDS = FOOD_FIELDS + ["ejercicio"]

# Umbrales (en $ semanales) para clasificar el presupuesto. Ajústalos a tu gusto.
BUDGET_BAJO = 700
BUDGET_ALTO = 1750

SCHEMA = """
CREATE TABLE IF NOT EXISTS plan_semanal (
    id INT AUTO_INCREMENT PRIMARY KEY,
    dia VARCHAR(12) NOT NULL UNIQUE,
    desayuno VARCHAR(255) NOT NULL DEFAULT '',
    comida VARCHAR(255) NOT NULL DEFAULT '',
    cena VARCHAR(255) NOT NULL DEFAULT '',
    snack VARCHAR(255) NOT NULL DEFAULT '',
    ejercicio VARCHAR(255) NOT NULL DEFAULT '',
    descanso_horas DECIMAL(4,2) NOT NULL DEFAULT 0,
    coste_desayuno DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_comida DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_cena DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_snack DECIMAL(10,2) NOT NULL DEFAULT 0,
    coste_diario DECIMAL(10,2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
"""

COLUMNS = ("id, dia, desayuno, comida, cena, snack, ejercicio, descanso_horas, "
           "coste_desayuno, coste_comida, coste_cena, coste_snack, coste_diario")
ORDER_DIA = "FIELD(dia, " + ", ".join(f"'{d}'" for d in DIAS) + ")"

_schema_ready = False


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------
def connect():
    kwargs = dict(
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("DB_USER", "root"),
        password=os.environ.get("DB_PASSWORD", ""),
        database=os.environ.get("DB_NAME", "fitplate"),
        charset="utf8mb4",
        cursorclass=DictCursor,
        connect_timeout=10,
    )
    if os.environ.get("DB_SSL", "false").strip().lower() == "true":
        # Aiven proporciona un certificado CA PEM. Se guarda como variable
        # de entorno para no incluir archivos ni secretos en el repositorio.
        ca_cert = os.environ.get("DB_SSL_CA", "").strip()
        if not ca_cert:
            raise RuntimeError(
                "DB_SSL=true requiere DB_SSL_CA con el contenido PEM del certificado CA."
            )
        # create_default_context conserva la validación del certificado y del hostname.
        ssl_context = ssl.create_default_context(cadata=ca_cert)
        kwargs["ssl"] = ssl_context
    return pymysql.connect(**kwargs)


@contextmanager
def db():
    """Una conexión por petición (ideal para funciones serverless)."""
    global _schema_ready
    conn = connect()
    try:
        with conn.cursor() as cur:
            if not _schema_ready:
                cur.execute(SCHEMA)
                _schema_ready = True
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def serialize(row):
    return {k: (float(v) if isinstance(v, Decimal) else v) for k, v in row.items()}


def fetch_all(where="", params=()):
    with db() as cur:
        cur.execute(f"SELECT {COLUMNS} FROM plan_semanal {where} ORDER BY {ORDER_DIA}", params)
        return [serialize(r) for r in cur.fetchall()]


# --------------------------------------------------------------------------
# Validación del formulario
# --------------------------------------------------------------------------
def to_decimal(value, label, max_value):
    value = (value or "").strip()
    if value == "":
        return Decimal("0.00")
    try:
        d = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"'{label}' debe ser un número.")
    if not d.is_finite() or d < 0 or d > max_value:
        raise ValueError(f"'{label}' debe estar entre 0 y {max_value}.")
    return d.quantize(Decimal("0.01"))


def parse_form(form):
    dia = form.get("dia", "").strip()
    if dia not in DIAS:
        raise ValueError("Selecciona un día válido.")
    data = {"dia": dia}
    for f in TEXT_FIELDS:
        data[f] = form.get(f, "").strip()[:255]
    data["descanso_horas"] = to_decimal(form.get("descanso_horas"), "Descanso (horas)", Decimal("24"))
    for f in COST_FIELDS:
        data[f] = to_decimal(form.get(f), f.replace("_", " ").title(), Decimal("99999"))
    # Coste diario = suma de los costes de cada alimento
    data["coste_diario"] = sum((data[f] for f in COST_FIELDS), Decimal("0.00"))
    return data


# --------------------------------------------------------------------------
# Rutas CRUD
# --------------------------------------------------------------------------
@app.route("/")
def index():
    conds, params = [], []
    if request.args.get("dia") in DIAS:
        conds.append("dia = %s")
        params.append(request.args["dia"])
    for f in TEXT_FIELDS:
        v = request.args.get(f, "").strip()
        if v:
            conds.append(f"{f} LIKE %s")
            params.append(f"%{v}%")
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    rows = fetch_all(where, params)

    with db() as cur:
        cur.execute("SELECT COALESCE(SUM(coste_diario),0) AS total, COUNT(*) AS n FROM plan_semanal")
        t = cur.fetchone()
    total = float(t["total"])
    n = t["n"]
    return render_template("index.html", rows=rows, dias=DIAS, budget_semanal=total,
                           promedio=(total / n if n else 0), n=n, filtrado=bool(conds))


@app.post("/add")
def add():
    try:
        d = parse_form(request.form)
        with db() as cur:
            cur.execute(
                "INSERT INTO plan_semanal (dia, desayuno, comida, cena, snack, ejercicio, descanso_horas,"
                " coste_desayuno, coste_comida, coste_cena, coste_snack, coste_diario)"
                " VALUES (%(dia)s,%(desayuno)s,%(comida)s,%(cena)s,%(snack)s,%(ejercicio)s,%(descanso_horas)s,"
                "%(coste_desayuno)s,%(coste_comida)s,%(coste_cena)s,%(coste_snack)s,%(coste_diario)s)", d)
        flash(f"✅ {d['dia']} agregado. Coste diario: ${d['coste_diario']}", "ok")
    except pymysql.err.IntegrityError:
        flash("⚠️ Ese día ya existe. Selecciónalo en la tabla y usa Update.", "error")
    except ValueError as e:
        flash(f"⚠️ {e}", "error")
    return redirect(url_for("index"))


@app.post("/update")
def update():
    rid = request.form.get("id", "").strip()
    if not rid.isdigit():
        flash("⚠️ Primero elige un registro con ✏️ para actualizarlo.", "error")
        return redirect(url_for("index"))
    try:
        d = parse_form(request.form)
        d["id"] = int(rid)
        with db() as cur:
            cur.execute(
                "UPDATE plan_semanal SET dia=%(dia)s, desayuno=%(desayuno)s, comida=%(comida)s, cena=%(cena)s,"
                " snack=%(snack)s, ejercicio=%(ejercicio)s, descanso_horas=%(descanso_horas)s,"
                " coste_desayuno=%(coste_desayuno)s, coste_comida=%(coste_comida)s, coste_cena=%(coste_cena)s,"
                " coste_snack=%(coste_snack)s, coste_diario=%(coste_diario)s WHERE id=%(id)s", d)
        flash(f"🔄 {d['dia']} actualizado.", "ok")
    except pymysql.err.IntegrityError:
        flash("⚠️ Ya existe otro registro con ese día.", "error")
    except ValueError as e:
        flash(f"⚠️ {e}", "error")
    return redirect(url_for("index"))


@app.post("/delete")
def delete():
    rid = request.form.get("id", "").strip()
    if not rid.isdigit():
        flash("⚠️ Elige un registro con ✏️ (o usa el 🗑️ de la fila) para eliminarlo.", "error")
        return redirect(url_for("index"))
    with db() as cur:
        cur.execute("DELETE FROM plan_semanal WHERE id = %s", (int(rid),))
    flash("🗑️ Registro eliminado.", "ok")
    return redirect(url_for("index"))


# --------------------------------------------------------------------------
# Reporte de consejos
# --------------------------------------------------------------------------
def norm(text):
    return unicodedata.normalize("NFKD", text.lower()).encode("ascii", "ignore").decode()


PROTEINAS = ["pollo", "pescado", "huevo", "atun", "salmon", "sardina", "frijol", "lenteja", "garbanzo",
             "carne", "res", "tofu", "yogur", "yogurt", "queso", "pavo", "requeson", "soya", "proteina"]
VERDURAS = ["ensalada", "verdura", "brocoli", "espinaca", "nopal", "zanahoria", "jitomate", "tomate",
            "pepino", "calabaza", "lechuga", "apio", "chayote", "coliflor", "pimiento", "champin"]
FRUTAS = ["fruta", "manzana", "platano", "papaya", "naranja", "fresa", "mango", "sandia", "melon", "uva",
          "pera", "pina", "kiwi", "guayaba", "mandarina", "limon", "arandano", "durazno"]
INTEGRALES = ["avena", "integral", "quinoa", "amaranto", "centeno", "granola", "chia", "linaza"]
ULTRAPROC = ["pizza", "hamburguesa", "refresco", "soda", "frito", "fritura", "papas fritas", "dulce", "pastel",
             "galleta", "helado", "nugget", "salchicha", "chocolate", "sabritas", "pan dulce", "donas", "donut"]
CARDIO = ["correr", "caminar", "caminata", "trotar", "bici", "ciclismo", "nadar", "natacion", "cardio",
          "hiit", "zumba", "baile", "bailar", "senderismo", "saltar"]
FUERZA = ["pesas", "fuerza", "gym", "gimnasio", "sentadilla", "calistenia", "flexion", "crossfit",
          "dominada", "mancuerna", "plancha", "abdominal"]
SIN_EJERCICIO = {"", "ninguno", "ninguna", "no", "nada", "descanso", "-", "n/a", "na"}


def build_report(rows):
    n = len(rows)
    rep = {"n": n, "sections": []}
    if n == 0:
        rep.update(budget=0, promedio=0, proyeccion=0)
        return rep

    budget = sum(r["coste_diario"] for r in rows)
    prom = budget / n
    proy = prom * 7
    rep.update(budget=round(budget, 2), promedio=round(prom, 2), proyeccion=round(proy, 2))

    # ---- Presupuesto
    p = []
    if n < 7:
        p.append(f"Registraste {n} de 7 días. Con tu promedio (${prom:.2f}/día) tu presupuesto proyectado "
                 f"para la semana completa sería de ${proy:.2f}.")
    if proy < BUDGET_BAJO:
        p.append("Presupuesto ajustado: prioriza leguminosas (frijol, lenteja, garbanzo), huevo, avena, nopales, "
                 "verduras de temporada, tortilla de maíz y atún en lata. Son económicos y muy nutritivos.")
        p.append("Compra en mercado o tianguis, planea el menú antes de ir y cocina por lotes (batch cooking) "
                 "para reducir desperdicio y gasto.")
    elif proy <= BUDGET_ALTO:
        p.append("Presupuesto equilibrado: alterna proteína magra (pollo, pescado, huevo) 4-5 días con "
                 "leguminosas el resto, e incluye fruta o verdura en cada comida.")
        p.append("Compra por temporada y en presentaciones grandes de granos, avena y leguminosas para ahorrar "
                 "sin sacrificar calidad.")
    else:
        p.append("Tienes buen margen: incorpora pescado azul (salmón, sardina), frutos secos, aguacate y granos "
                 "integrales. Más caro no siempre es más saludable: evita gastar en productos ultraprocesados "
                 "etiquetados como 'fit'.")
        p.append("Destina parte del presupuesto a lo que te ayude a sostener el hábito: calzado adecuado, "
                 "ligas o mancuernas, o una membresía que realmente uses.")
    sums = {f.replace("coste_", ""): sum(r[f] for r in rows) for f in COST_FIELDS}
    top = max(sums, key=sums.get)
    if budget > 0:
        share = sums[top] / budget * 100
        p.append(f"Tu mayor gasto es en '{top}' (${sums[top]:.2f}, {share:.0f}% del total). "
                 "Ahí tienes la mejor oportunidad de optimizar.")
        if sums["snack"] / budget > 0.20:
            p.append("Tus snacks superan el 20% del gasto: cambia botanas empaquetadas por fruta, jícama con limón, "
                     "yogur natural o un puñado de nueces.")
    caro = max(rows, key=lambda r: r["coste_diario"])
    barato = min(rows, key=lambda r: r["coste_diario"])
    p.append(f"Día más caro: {caro['dia']} (${caro['coste_diario']:.2f}). "
             f"Día más económico: {barato['dia']} (${barato['coste_diario']:.2f}).")
    rep["sections"].append({"title": "Presupuesto inteligente", "icon": "💰", "tips": p})

    # ---- Alimentación
    texts = [norm(" ".join(r[f] for f in FOOD_FIELDS)) for r in rows]

    def days_with(kws):
        return sum(1 for t in texts if any(k in t for k in kws))

    a = []
    prot, ver, fru, integ, ultra = (days_with(PROTEINAS), days_with(VERDURAS), days_with(FRUTAS),
                                    days_with(INTEGRALES), days_with(ULTRAPROC))
    if prot < n:
        a.append(f"Solo {prot} de {n} días incluyen una fuente clara de proteína. Añade huevo, pollo, pescado, "
                 "legumbres o yogur natural en al menos una comida diaria para cuidar tu masa muscular y saciedad.")
    else:
        a.append("Excelente: todos tus días incluyen proteína. Varía las fuentes (animal y vegetal) para más nutrientes.")
    if ver < n:
        a.append(f"Verduras presentes en {ver} de {n} días. Usa como guía el Plato del Bien Comer: la mitad de tu plato "
                 "debe ser verduras y frutas.")
    if fru < n:
        a.append(f"Fruta presente en {fru} de {n} días. Úsala como snack o postre natural en lugar de dulces.")
    if integ == 0:
        a.append("No veo cereales integrales: prueba avena, pan o tortilla integral, arroz integral o amaranto "
                 "para más fibra y energía sostenida.")
    if ultra > 0:
        a.append(f"Detecté alimentos ultraprocesados o muy azucarados en {ultra} día(s). Déjalos como gusto ocasional "
                 "y no como base de tu semana.")
    a.append("Hidratación: procura 1.5 a 2 litros de agua al día y limita refrescos y jugos industrializados.")
    a.append("Estructura sugerida: desayuno con proteína + fibra, comida completa, cena ligera y snacks pequeños "
             "y simples. Come despacio y evita saltarte comidas.")
    rep["sections"].append({"title": "Alimentación y dieta", "icon": "🥗", "tips": a})

    # ---- Ejercicio
    ej_txt = [norm(r["ejercicio"]) for r in rows]
    activos = [t for t in ej_txt if t.strip() not in SIN_EJERCICIO]
    e = []
    if len(activos) < 3:
        e.append(f"Te mueves {len(activos)} de {n} días. La OMS recomienda al menos 150 minutos de actividad "
                 "moderada por semana: empieza con caminatas de 30 minutos y suma un día a la vez.")
    elif len(activos) < 6:
        e.append(f"Buen ritmo: {len(activos)} días activos. Mantén la constancia y sube la intensidad poco a poco.")
    else:
        e.append(f"Estás activo {len(activos)} días: cuida tu recuperación e incluye al menos 1 día de descanso "
                 "activo (estiramientos, caminata suave).")
    joined = " ".join(ej_txt)
    if not any(k in joined for k in CARDIO):
        e.append("Agrega cardio (caminar rápido, bici, nadar o bailar) 2-3 veces por semana para tu corazón.")
    if not any(k in joined for k in FUERZA):
        e.append("Incluye fuerza 2 días por semana (sentadillas, flexiones, plancha o pesas) para músculo y huesos.")
    e.append("Calienta 5-10 minutos antes y estira al terminar; ajusta la intensidad a tu nivel actual.")
    rep["sections"].append({"title": "Ejercicio", "icon": "🏋️", "tips": e})

    # ---- Descanso
    horas = [r["descanso_horas"] for r in rows if r["descanso_horas"] > 0]
    d = []
    if horas:
        avg = sum(horas) / len(horas)
        pocos = sum(1 for h in horas if h < 7)
        d.append(f"Duermes en promedio {avg:.1f} horas por noche.")
        if avg < 7:
            d.append("Estás por debajo de las 7-9 horas recomendadas para adultos. Fija horario de dormir, "
                     "evita pantallas 1 hora antes y cena ligero.")
        elif avg > 9:
            d.append("Duermes más de 9 horas en promedio. Revisa la calidad del sueño y mantén horarios regulares.")
        else:
            d.append("Estás dentro del rango ideal de 7-9 horas. ¡Sigue así!")
        if pocos:
            d.append(f"{pocos} día(s) con menos de 7 horas: intenta compensar con una rutina de sueño más regular.")
    else:
        d.append("Registra tus horas de descanso para recibir recomendaciones personalizadas de sueño.")
    d.append("Dormir bien regula el apetito, mejora el rendimiento y acelera la recuperación muscular.")
    rep["sections"].append({"title": "Descanso", "icon": "😴", "tips": d})
    return rep


# --------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------
def clean(text):
    # Las fuentes base de PDF usan latin-1 (acentos OK, emojis no).
    return str(text).encode("latin-1", "replace").decode("latin-1")


def trunc(text, width_mm):
    limit = max(int(width_mm / 1.9), 3)
    text = str(text)
    return text if len(text) <= limit else text[: limit - 2] + ".."


def build_pdf(rep, rows):
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(True, 15)
    pdf.add_page()

    pdf.set_fill_color(46, 125, 50)
    pdf.rect(0, 0, 297, 24, "F")
    pdf.set_xy(10, 7)
    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, clean("FitPlate - Reporte Saludable y Fitness"), new_x="LMARGIN", new_y="NEXT")

    pdf.set_y(30)
    pdf.set_text_color(27, 58, 31)
    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 7, clean(f"Presupuesto semanal: ${rep['budget']:.2f}    |    "
                         f"Promedio diario: ${rep['promedio']:.2f}    |    "
                         f"Proyeccion 7 dias: ${rep['proyeccion']:.2f}"), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)

    cols = [("Dia", 24), ("Desayuno", 38), ("Comida", 38), ("Cena", 38), ("Snack", 30),
            ("Ejercicio", 40), ("Descanso", 20), ("Coste ($)", 29)]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(124, 179, 66)
    pdf.set_text_color(255, 255, 255)
    for i, (name, w) in enumerate(cols):
        last = i == len(cols) - 1
        pdf.cell(w, 8, clean(name), border=1, fill=True, align="C",
                 new_x="LMARGIN" if last else "RIGHT", new_y="NEXT" if last else "TOP")
    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(27, 58, 31)
    for idx, r in enumerate(rows):
        pdf.set_fill_color(241, 248, 233) if idx % 2 == 0 else pdf.set_fill_color(255, 255, 255)
        vals = [r["dia"], r["desayuno"], r["comida"], r["cena"], r["snack"], r["ejercicio"],
                f"{r['descanso_horas']:.1f} h", f"{r['coste_diario']:.2f}"]
        for i, ((_, w), v) in enumerate(zip(cols, vals)):
            last = i == len(cols) - 1
            pdf.cell(w, 7, clean(trunc(v, w)), border=1, fill=True,
                     align="R" if last else "L",
                     new_x="LMARGIN" if last else "RIGHT", new_y="NEXT" if last else "TOP")
    pdf.set_font("Helvetica", "B", 9)
    pdf.cell(sum(w for _, w in cols[:-1]), 8, clean("TOTAL SEMANAL"), border=1, align="R")
    pdf.cell(cols[-1][1], 8, clean(f"{rep['budget']:.2f}"), border=1, align="R",
             new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    for sec in rep["sections"]:
        if pdf.get_y() > 175:
            pdf.add_page()
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(46, 125, 50)
        pdf.cell(0, 8, clean(sec["title"]), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(27, 58, 31)
        for tip in sec["tips"]:
            pdf.multi_cell(0, 5.5, clean("- " + tip), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)

    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 4.5, clean("Datos ficticios con fines ludicos. Este reporte no sustituye la orientacion "
                                 "de un nutriologo, medico o entrenador profesional."),
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


@app.route("/reporte")
def reporte():
    rows = fetch_all()
    return render_template("reporte.html", rep=build_report(rows), rows=rows)


@app.route("/reporte.pdf")
def reporte_pdf():
    rows = fetch_all()
    pdf_bytes = build_pdf(build_report(rows), rows)
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=True, download_name="reporte_saludable.pdf")


@app.errorhandler(pymysql.MySQLError)
def db_error(e):
    return ("<h2>No se pudo conectar con la base de datos MySQL</h2>"
            "<p>Revisa las variables DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME y DB_SSL.</p>"
            f"<pre>{type(e).__name__}</pre>"), 500


if __name__ == "__main__":
    app.run(debug=True)
