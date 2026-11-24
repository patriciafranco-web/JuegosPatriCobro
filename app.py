import csv
import io
import os
import re
import shutil
import sqlite3
import urllib.parse
import urllib.request
import uuid
import webbrowser
from datetime import datetime, timedelta
from functools import wraps
from threading import Timer
from flask import (
    Flask, render_template, render_template_string, request,
    jsonify, send_file, send_from_directory, Response, session, redirect, url_for
)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "juegos-patri-clave-secreta-2026")

# USUARIOS Y CONTRASEÑAS (Puedes cambiarlos aquí)
ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASS = os.environ.get("ADMIN_PASS", "patri2026")
COBRADOR_USER = os.environ.get("COBRADOR_USER", "cobrador")
COBRADOR_PASS = os.environ.get("COBRADOR_PASS", "cobro2026")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "juegos_patri.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")

os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "No autorizado"}), 401
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("logged_in"):
            if request.path.startswith("/api/"):
                return jsonify({"error": "No autorizado"}), 401
            return redirect(url_for("login"))
        if session.get("role") != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Solo administrador"}), 403
            return redirect(url_for("vista_cobrador"))
        return f(*args, **kwargs)
    return decorated


LOGIN_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Acceso — Juegos Patri</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-900 min-h-screen flex items-center justify-center p-4">
  <div class="bg-white rounded-2xl shadow-2xl max-w-sm w-full p-6 space-y-5">
    <div class="text-center">
      <div class="inline-block bg-emerald-600 text-white font-black px-3 py-1.5 rounded-xl text-lg mb-2">JP</div>
      <h1 class="text-xl font-black text-slate-900">JUEGOS PATRI</h1>
      <p class="text-xs text-slate-500">Sistema de Control, Fichas y Rutas</p>
    </div>
    {% if error %}
      <div class="bg-rose-50 border border-rose-200 text-rose-700 text-xs font-bold p-2.5 rounded-lg text-center">{{ error }}</div>
    {% endif %}
    <form method="POST" class="space-y-3 text-sm">
      <div>
        <label class="block text-xs font-bold text-slate-700 mb-1">Usuario</label>
        <input name="username" required autofocus class="w-full px-3 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500" placeholder="admin o cobrador" />
      </div>
      <div>
        <label class="block text-xs font-bold text-slate-700 mb-1">Contraseña</label>
        <input name="password" type="password" required class="w-full px-3 py-2.5 border border-slate-300 rounded-lg focus:ring-2 focus:ring-emerald-500" placeholder="••••••••" />
      </div>
      <button type="submit" class="w-full bg-emerald-600 hover:bg-emerald-500 text-white font-extrabold py-3 rounded-lg shadow">
        Ingresar al Sistema
      </button>
    </form>
  </div>
</body>
</html>
"""


QR_ETIQUETAS_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Etiquetas QR por Mesa — Juegos Patri</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
  <style>
    @media print {
      .no-print { display: none !important; }
      body { background: #ffffff !important; padding: 0 !important; }
      .etiqueta-card { break-inside: avoid; page-break-inside: avoid; box-shadow: none !important; border: 1.5px solid #0f172a !important; }
    }
  </style>
</head>
<body class="bg-slate-100 text-slate-900 min-h-screen p-4">
  <div class="max-w-5xl mx-auto space-y-4">
    <div class="no-print bg-white p-4 rounded-2xl border border-slate-200 shadow-sm flex flex-wrap items-center justify-between gap-3">
      <div>
        <h1 class="text-lg font-black text-slate-900">Etiquetas QR por Mesa — Juegos Patri</h1>
        <p class="text-xs text-slate-500">Cada código abre directo la carga de esa mesa en <code>/cobrador?mesa=...</code></p>
      </div>
      <div class="flex items-center gap-2">
        <a href="/cobrador" class="bg-slate-200 hover:bg-slate-300 text-slate-900 text-xs font-extrabold px-3.5 py-2.5 rounded-xl">
          ← Volver a Cobrador
        </a>
        <button type="button" onclick="window.print()" class="bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-black px-4 py-2.5 rounded-xl shadow">
          🖨️ Imprimir todas las etiquetas
        </button>
      </div>
    </div>

    <div id="grid-qr" class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 gap-3"></div>
  </div>

  <script>
    const mesas = {{ mesas | tojson }};
    const baseUrl = window.location.origin;
    const grid = document.getElementById('grid-qr');

    if (!mesas.length) {
      grid.innerHTML = '<div class="col-span-full bg-white p-6 rounded-2xl text-center text-sm text-slate-500 border">No hay mesas activas para generar etiquetas.</div>';
    } else {
      mesas.forEach((m, idx) => {
        const mesaNum = String(m.mesa_num || '').trim();
        const urlDestino = `${baseUrl}/cobrador?mesa=${encodeURIComponent(mesaNum)}`;
        const qrId = `qr-box-${idx}`;

        const card = document.createElement('div');
        card.className = 'etiqueta-card bg-white p-3.5 rounded-2xl border border-slate-300 shadow-sm flex flex-col items-center text-center space-y-2';
        card.innerHTML = `
          <div class="w-full flex items-center justify-between text-[10px] font-black uppercase text-slate-500 border-b pb-1.5">
            <span>JUEGOS PATRI</span>
            <span class="bg-slate-900 text-white px-2 py-0.5 rounded text-xs">MESA ${mesaNum}</span>
          </div>
          <div id="${qrId}" class="py-1 flex items-center justify-center"></div>
          <div class="w-full">
            <p class="font-extrabold text-xs text-slate-900 truncate">${m.senor || ''}</p>
            <p class="text-[11px] text-slate-500 truncate">${m.ciudad || ''}${m.lugar ? ' • ' + m.lugar : ''}</p>
          </div>
        `;
        grid.appendChild(card);

        new QRCode(document.getElementById(qrId), {
          text: urlDestino,
          width: 132,
          height: 132,
          correctLevel: QRCode.CorrectLevel.M
        });
      });
    }
  </script>
</body>
</html>
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def crear_backup_automatico():
    if os.path.exists(DB_PATH):
        fecha = datetime.now().strftime("%Y-%m-%d")
        destino = os.path.join(BACKUP_DIR, f"juegos_patri_{fecha}.db")
        shutil.copy2(DB_PATH, destino)
        archivos = sorted(os.listdir(BACKUP_DIR))
        while len(archivos) > 30:
            os.remove(os.path.join(BACKUP_DIR, archivos.pop(0)))


def _buscar_coords_en_texto(texto):
    if not texto:
        return None, None
    texto = urllib.parse.unquote(texto)
    patrones = [
        r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)",
        r"@(-?\d+\.\d+),(-?\d+\.\d+)",
        r"[?&](?:q|ll|query)=(-?\d+\.\d+),\s*(-?\d+\.\d+)",
        r"/search/(-?\d+\.\d+),\s*\+?(-?\d+\.\d+)",
        r"(-?\d{1,2}\.\d{4,}),\s*(-?\d{1,3}\.\d{4,})",
    ]
    for p in patrones:
        m = re.search(p, texto)
        if m:
            lat, lng = float(m.group(1)), float(m.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
    return None, None


def extraer_coordenadas_maps(url):
    url = (url or "").strip()
    if not url:
        return None, None

    lat, lng = _buscar_coords_en_texto(url)
    if lat is not None:
        return lat, lng

    if url.startswith("http://") or url.startswith("https://"):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                final_url = resp.geturl()
                lat, lng = _buscar_coords_en_texto(final_url)
                if lat is not None:
                    return lat, lng
                html = resp.read(50000).decode("utf-8", errors="ignore")
                lat, lng = _buscar_coords_en_texto(html)
                if lat is not None:
                    return lat, lng
        except Exception:
            pass

    return None, None


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS clientes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mesa_num TEXT NOT NULL,
                senor TEXT NOT NULL,
                ciudad TEXT DEFAULT '',
                calle TEXT DEFAULT '',
                lugar TEXT DEFAULT '',
                ci TEXT DEFAULT '',
                tarifa INTEGER DEFAULT 1000,
                maps_url TEXT DEFAULT '',
                lat REAL DEFAULT NULL,
                lng REAL DEFAULT NULL,
                notas TEXT DEFAULT '',
                activo INTEGER DEFAULT 1,
                creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS lecturas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                reloj INTEGER NOT NULL,
                cant_jug INTEGER DEFAULT 0,
                total_gs INTEGER DEFAULT 0,
                entrega INTEGER DEFAULT 0,
                saldo_resultante INTEGER DEFAULT 0,
                observacion TEXT DEFAULT '',
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS mantenimientos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                fecha TEXT NOT NULL,
                tipo TEXT NOT NULL,
                costo INTEGER DEFAULT 0,
                observacion TEXT DEFAULT '',
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS gastos_gira (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fecha TEXT NOT NULL,
                categoria TEXT NOT NULL,
                ciudad TEXT DEFAULT '',
                monto INTEGER DEFAULT 0,
                descripcion TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS inventario_mesas (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                mesa_num TEXT NOT NULL,
                estado TEXT NOT NULL DEFAULT 'Depósito',
                modelo TEXT DEFAULT '',
                comprador TEXT DEFAULT '',
                telefono TEXT DEFAULT '',
                precio INTEGER DEFAULT 0,
                pagado INTEGER DEFAULT 0,
                fecha TEXT DEFAULT '',
                observacion TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS fotos_cliente (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                cliente_id INTEGER NOT NULL,
                tipo TEXT NOT NULL DEFAULT 'Reloj',
                archivo TEXT NOT NULL,
                fecha TEXT NOT NULL,
                observacion TEXT DEFAULT '',
                FOREIGN KEY (cliente_id) REFERENCES clientes(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_clientes_busqueda ON clientes(mesa_num, senor, ciudad, lugar);
            CREATE INDEX IF NOT EXISTS idx_lecturas_cliente ON lecturas(cliente_id, id);
            CREATE INDEX IF NOT EXISTS idx_mant_cliente ON mantenimientos(cliente_id, fecha);
            CREATE INDEX IF NOT EXISTS idx_fotos_cliente ON fotos_cliente(cliente_id, id);
        """)

        cols = [r["name"] for r in conn.execute("PRAGMA table_info(clientes)").fetchall()]
        if "maps_url" not in cols:
            conn.execute("ALTER TABLE clientes ADD COLUMN maps_url TEXT DEFAULT ''")
        if "lat" not in cols:
            conn.execute("ALTER TABLE clientes ADD COLUMN lat REAL DEFAULT NULL")
        if "lng" not in cols:
            conn.execute("ALTER TABLE clientes ADD COLUMN lng REAL DEFAULT NULL")

    crear_backup_automatico()


def recalcular_cadena(conn, cliente_id):
    cliente = conn.execute("SELECT tarifa FROM clientes WHERE id = ?", (cliente_id,)).fetchone()
    if not cliente:
        return
    tarifa = cliente["tarifa"]
    filas = conn.execute(
        "SELECT id, reloj, cant_jug, entrega FROM lecturas WHERE cliente_id = ? ORDER BY id ASC",
        (cliente_id,)
    ).fetchall()

    saldo_acum = 0
    for idx, f in enumerate(filas):
        if idx == 0:
            cant = f["cant_jug"] if f["cant_jug"] > 0 else 0
        else:
            anterior = filas[idx - 1]["reloj"]
            cant = max(0, f["reloj"] - anterior)
        total = cant * tarifa
        saldo_acum = saldo_acum + total - (f["entrega"] or 0)
        conn.execute(
            "UPDATE lecturas SET cant_jug = ?, total_gs = ?, saldo_resultante = ? WHERE id = ?",
            (cant, total, saldo_acum, f["id"])
        )


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        u = request.form.get("username", "").strip()
        p = request.form.get("password", "").strip()
        if u == ADMIN_USER and p == ADMIN_PASS:
            session["logged_in"] = True
            session["role"] = "admin"
            return redirect(url_for("index"))
        if u == COBRADOR_USER and p == COBRADOR_PASS:
            session["logged_in"] = True
            session["role"] = "cobrador"
            return redirect(url_for("vista_cobrador"))
        error = "Usuario o contraseña incorrectos"
    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    if session.get("role") == "cobrador":
        return redirect(url_for("vista_cobrador"))
    return render_template("index.html")


@app.route("/cobrador")
@login_required
def vista_cobrador():
    return render_template("cobrador.html")


@app.route("/cobrador/qr-etiquetas")
@login_required
def qr_etiquetas():
    with get_db() as conn:
        mesas = [
            dict(r) for r in conn.execute(
                """SELECT id, mesa_num, senor, ciudad, lugar
                   FROM clientes
                   WHERE activo = 1
                   ORDER BY CAST(mesa_num AS INTEGER) ASC, mesa_num ASC"""
            ).fetchall()
        ]
    return render_template_string(QR_ETIQUETAS_HTML, mesas=mesas)


@app.route("/uploads/<path:filename>")
@login_required
def servir_foto(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/cobrador/cargar", methods=["POST"])
@login_required
def cobrador_cargar_lectura():
    cid = int(request.form.get("cliente_id"))
    fecha = request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    reloj = int(request.form.get("reloj"))
    entrega = int(request.form.get("entrega") or 0)
    obs = request.form.get("observacion", "").strip()
    lat = request.form.get("lat", "").strip()
    lng = request.form.get("lng", "").strip()

    with get_db() as conn:
        ultima = conn.execute(
            "SELECT reloj FROM lecturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()
        if ultima and reloj < ultima["reloj"]:
            return jsonify({"error": f"El reloj ({reloj}) no puede ser menor al anterior ({ultima['reloj']})"}), 400

        conn.execute(
            "INSERT INTO lecturas (cliente_id, fecha, reloj, entrega, observacion) VALUES (?, ?, ?, ?, ?)",
            (cid, fecha, reloj, entrega, obs)
        )
        recalcular_cadena(conn, cid)

        archivo = request.files.get("foto")
        if archivo and archivo.filename:
            ext = os.path.splitext(archivo.filename)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                ext = ".jpg"
            nombre_unico = f"cli{cid}_{uuid.uuid4().hex[:10]}{ext}"
            archivo.save(os.path.join(UPLOAD_DIR, nombre_unico))
            conn.execute(
                "INSERT INTO fotos_cliente (cliente_id, tipo, archivo, fecha, observacion) VALUES (?, ?, ?, ?, ?)",
                (cid, "Reloj", nombre_unico, fecha, f"Reloj {reloj} (Cobrador)")
            )

        if lat and lng:
            cli = conn.execute("SELECT maps_url, lat, lng FROM clientes WHERE id = ?", (cid,)).fetchone()
            if cli and (cli["lat"] is None or cli["lng"] is None):
                url_maps = f"https://www.google.com/maps?q={lat},{lng}"
                conn.execute(
                    "UPDATE clientes SET lat=?, lng=?, maps_url=CASE WHEN maps_url='' THEN ? ELSE maps_url END WHERE id=?",
                    (float(lat), float(lng), url_maps, cid)
                )

        nueva = conn.execute(
            "SELECT * FROM lecturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()

    crear_backup_automatico()
    return jsonify({"ok": True, "lectura": dict(nueva)})


@app.route("/api/cobrador/rendicion", methods=["GET"])
@login_required
def cobrador_rendicion_hoy():
    hoy = datetime.now().strftime("%Y-%m-%d")
    with get_db() as conn:
        cobros = [dict(r) for r in conn.execute("""
            SELECT l.id, l.fecha, l.reloj, l.cant_jug, l.total_gs, l.entrega, l.saldo_resultante, l.observacion,
                   c.mesa_num, c.senor, c.ciudad
            FROM lecturas l
            JOIN clientes c ON c.id = l.cliente_id
            WHERE l.fecha = ?
            ORDER BY l.id DESC
        """, (hoy,)).fetchall()]

        gastos = [dict(r) for r in conn.execute(
            "SELECT * FROM gastos_gira WHERE fecha = ? ORDER BY id DESC", (hoy,)
        ).fetchall()]

    total_cobrado = sum(c["entrega"] for c in cobros)
    total_gastos = sum(g["monto"] for g in gastos)
    return jsonify({
        "fecha": hoy,
        "total_cobrado": total_cobrado,
        "total_gastos": total_gastos,
        "neto_a_rendir": total_cobrado - total_gastos,
        "cobros": cobros,
        "gastos": gastos
    })


@app.route("/api/clientes", methods=["GET"])
@login_required
def listar_clientes():
    q = request.args.get("q", "").strip()
    ciudad = request.args.get("ciudad", "").strip()
    solo_deuda = request.args.get("solo_deuda", "0") == "1"
    solo_sin_gps = request.args.get("sin_gps", "0") == "1"

    sql = """
        SELECT c.*,
               COALESCE((SELECT reloj FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS ultimo_reloj,
               COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
               COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual,
               (SELECT COUNT(*) FROM lecturas WHERE cliente_id = c.id) AS total_visitas
        FROM clientes c
        WHERE c.activo = 1
    """
    params = []
    if q:
        sql += " AND (c.mesa_num LIKE ? OR c.senor LIKE ? OR c.lugar LIKE ? OR c.calle LIKE ? OR c.ciudad LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like, like, like, like])
    if ciudad:
        sql += " AND c.ciudad = ?"
        params.append(ciudad)

    sql += " ORDER BY CAST(c.mesa_num AS INTEGER) ASC, c.mesa_num ASC"

    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
        ciudades = [
            r["ciudad"] for r in conn.execute(
                "SELECT DISTINCT ciudad FROM clientes WHERE activo = 1 AND ciudad != '' ORDER BY ciudad"
            ).fetchall()
        ]

    if solo_deuda:
        rows = [r for r in rows if r["saldo_actual"] > 0]
    if solo_sin_gps:
        rows = [r for r in rows if not (r.get("maps_url") or "").strip()]

    total_cartera = sum(r["saldo_actual"] for r in rows if r["saldo_actual"] > 0)
    con_gps = sum(1 for r in rows if (r.get("maps_url") or "").strip())
    sin_gps = len(rows) - con_gps

    return jsonify({
        "clientes": rows,
        "ciudades": ciudades,
        "resumen": {
            "total_mesas": len(rows),
            "con_saldo": sum(1 for r in rows if r["saldo_actual"] > 0),
            "total_a_cobrar": total_cartera,
            "con_gps": con_gps,
            "sin_gps": sin_gps
        }
    })


@app.route("/api/cola-whatsapp", methods=["GET"])
@admin_required
def cola_whatsapp():
    sql = """
        SELECT c.id, c.mesa_num, c.senor, c.ciudad, c.lugar, c.calle, c.maps_url,
               COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual,
               COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha
        FROM clientes c
        WHERE c.activo = 1
        ORDER BY c.ciudad ASC, CAST(c.mesa_num AS INTEGER) ASC
    """
    with get_db() as conn:
        rows = [dict(r) for r in conn.execute(sql).fetchall()]

    con_saldo = [r for r in rows if r["saldo_actual"] > 0]
    sin_gps = [r for r in rows if not (r.get("maps_url") or "").strip()]
    return jsonify({"con_saldo": con_saldo, "sin_gps": sin_gps})


@app.route("/api/inventario", methods=["GET", "POST"])
@admin_required
def gestionar_inventario():
    with get_db() as conn:
        if request.method == "GET":
            items = [dict(r) for r in conn.execute(
                "SELECT * FROM inventario_mesas ORDER BY id DESC"
            ).fetchall()]
            alquiladas = conn.execute("SELECT COUNT(*) FROM clientes WHERE activo = 1").fetchone()[0]
            en_deposito = sum(1 for i in items if i["estado"] == "Depósito")
            en_reparacion = sum(1 for i in items if i["estado"] == "En Reparación")
            vendidas = sum(1 for i in items if i["estado"] == "Vendida")
            total_ventas = sum(i["precio"] for i in items if i["estado"] == "Vendida")
            pendiente_ventas = sum(max(0, i["precio"] - i["pagado"]) for i in items if i["estado"] == "Vendida")
            return jsonify({
                "items": items,
                "resumen": {
                    "alquiladas": alquiladas,
                    "en_deposito": en_deposito,
                    "en_reparacion": en_reparacion,
                    "vendidas": vendidas,
                    "total_flota": alquiladas + en_deposito + en_reparacion,
                    "total_ventas": total_ventas,
                    "pendiente_ventas": pendiente_ventas
                }
            })

        data = request.json
        conn.execute(
            """INSERT INTO inventario_mesas (mesa_num, estado, modelo, comprador, telefono, precio, pagado, fecha, observacion)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("mesa_num", "").strip(),
                data.get("estado", "Depósito").strip(),
                data.get("modelo", "").strip(),
                data.get("comprador", "").strip(),
                data.get("telefono", "").strip(),
                int(data.get("precio") or 0),
                int(data.get("pagado") or 0),
                data.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                data.get("observacion", "").strip()
            )
        )
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/inventario/<int:iid>", methods=["PUT", "DELETE"])
@admin_required
def editar_inventario(iid):
    with get_db() as conn:
        if request.method == "DELETE":
            conn.execute("DELETE FROM inventario_mesas WHERE id = ?", (iid,))
        else:
            data = request.json
            conn.execute(
                """UPDATE inventario_mesas
                   SET mesa_num=?, estado=?, modelo=?, comprador=?, telefono=?, precio=?, pagado=?, fecha=?, observacion=?
                   WHERE id=?""",
                (
                    data.get("mesa_num", "").strip(),
                    data.get("estado", "Depósito").strip(),
                    data.get("modelo", "").strip(),
                    data.get("comprador", "").strip(),
                    data.get("telefono", "").strip(),
                    int(data.get("precio") or 0),
                    int(data.get("pagado") or 0),
                    data.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                    data.get("observacion", "").strip(),
                    iid
                )
            )
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/clientes/<int:cid>/fotos", methods=["GET", "POST"])
@login_required
def fotos_cliente(cid):
    with get_db() as conn:
        if request.method == "GET":
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM fotos_cliente WHERE cliente_id = ? ORDER BY id DESC", (cid,)
            ).fetchall()]
            return jsonify({"fotos": rows})

        archivo = request.files.get("foto")
        if not archivo or not archivo.filename:
            return jsonify({"error": "Selecciona una imagen"}), 400
        ext = os.path.splitext(archivo.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            ext = ".jpg"
        nombre_unico = f"cli{cid}_{uuid.uuid4().hex[:10]}{ext}"
        archivo.save(os.path.join(UPLOAD_DIR, nombre_unico))

        tipo = request.form.get("tipo", "Reloj").strip()
        obs = request.form.get("observacion", "").strip()
        fecha = request.form.get("fecha") or datetime.now().strftime("%Y-%m-%d")
        conn.execute(
            "INSERT INTO fotos_cliente (cliente_id, tipo, archivo, fecha, observacion) VALUES (?, ?, ?, ?, ?)",
            (cid, tipo, nombre_unico, fecha, obs)
        )
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/fotos/<int:fid>", methods=["DELETE"])
@admin_required
def borrar_foto(fid):
    with get_db() as conn:
        row = conn.execute("SELECT archivo FROM fotos_cliente WHERE id = ?", (fid,)).fetchone()
        if row:
            ruta = os.path.join(UPLOAD_DIR, row["archivo"])
            if os.path.exists(ruta):
                os.remove(ruta)
            conn.execute("DELETE FROM fotos_cliente WHERE id = ?", (fid,))
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/dashboard", methods=["GET"])
@admin_required
def dashboard():
    hoy = datetime.now().date()
    hoy_str = hoy.strftime("%Y-%m-%d")
    inicio_semana = (hoy - timedelta(days=hoy.weekday())).strftime("%Y-%m-%d")
    inicio_mes = hoy.replace(day=1).strftime("%Y-%m-%d")
    limite_2m = (hoy - timedelta(days=60)).strftime("%Y-%m-%d")
    limite_3m = (hoy - timedelta(days=90)).strftime("%Y-%m-%d")

    with get_db() as conn:
        rec_hoy = conn.execute(
            "SELECT COALESCE(SUM(entrega), 0) FROM lecturas WHERE fecha = ?", (hoy_str,)
        ).fetchone()[0]
        rec_semana = conn.execute(
            "SELECT COALESCE(SUM(entrega), 0) FROM lecturas WHERE fecha >= ?", (inicio_semana,)
        ).fetchone()[0]
        rec_mes = conn.execute(
            "SELECT COALESCE(SUM(entrega), 0) FROM lecturas WHERE fecha >= ?", (inicio_mes,)
        ).fetchone()[0]

        por_ciudad_mes = [
            dict(r) for r in conn.execute("""
                SELECT CASE WHEN TRIM(c.ciudad) = '' THEN 'Sin Ciudad' ELSE TRIM(c.ciudad) END AS ciudad,
                       COALESCE(SUM(l.entrega), 0) AS total
                FROM lecturas l
                JOIN clientes c ON c.id = l.cliente_id
                WHERE l.fecha >= ? AND l.entrega > 0
                GROUP BY ciudad
                ORDER BY total DESC
            """, (inicio_mes,)).fetchall()
        ]

        gastos_mes = conn.execute(
            "SELECT COALESCE(SUM(monto), 0) FROM gastos_gira WHERE fecha >= ?", (inicio_mes,)
        ).fetchone()[0]

        mant_mes = conn.execute(
            "SELECT COALESCE(SUM(costo), 0) FROM mantenimientos WHERE fecha >= ?", (inicio_mes,)
        ).fetchone()[0]

        gastos_lista = [
            dict(r) for r in conn.execute(
                "SELECT * FROM gastos_gira ORDER BY fecha DESC, id DESC LIMIT 40"
            ).fetchall()
        ]

        filas_ranking = [
            dict(r) for r in conn.execute("""
                SELECT c.id, c.mesa_num, c.senor, c.ciudad, c.lugar,
                       COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
                       COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual,
                       COALESCE((SELECT SUM(cant_jug) FROM lecturas WHERE cliente_id = c.id AND fecha >= ?), 0) AS juegos_3m,
                       COALESCE((SELECT SUM(entrega) FROM lecturas WHERE cliente_id = c.id AND fecha >= ?), 0) AS cobrado_3m
                FROM clientes c
                WHERE c.activo = 1
            """, (limite_3m, limite_3m)).fetchall()
        ]

    top_mesas = sorted(
        [f for f in filas_ranking if f["juegos_3m"] > 0],
        key=lambda x: x["juegos_3m"],
        reverse=True
    )[:10]

    para_retirar = [
        f for f in filas_ranking
        if f["juegos_3m"] < 50 and (f["saldo_actual"] > 0 or (not f["ultima_fecha"]) or f["ultima_fecha"] <= limite_2m)
    ]
    para_retirar.sort(key=lambda x: (x["juegos_3m"], -x["saldo_actual"]))

    return jsonify({
        "recaudacion": {
            "hoy": rec_hoy,
            "semana": rec_semana,
            "mes": rec_mes,
            "por_ciudad_mes": por_ciudad_mes
        },
        "gastos": {
            "gira_mes": gastos_mes,
            "mant_mes": mant_mes,
            "total_mes": gastos_mes + mant_mes,
            "lista": gastos_lista
        },
        "ganancia_neta_mes": rec_mes - (gastos_mes + mant_mes),
        "top_mesas": top_mesas,
        "para_retirar": para_retirar[:25]
    })


@app.route("/api/gastos", methods=["POST"])
@login_required
def agregar_gasto():
    data = request.json
    with get_db() as conn:
        conn.execute(
            "INSERT INTO gastos_gira (fecha, categoria, ciudad, monto, descripcion) VALUES (?, ?, ?, ?, ?)",
            (
                data.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                data.get("categoria", "Combustible").strip(),
                data.get("ciudad", "").strip(),
                int(data.get("monto") or 0),
                data.get("descripcion", "").strip()
            )
        )
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/gastos/<int:gid>", methods=["DELETE"])
@admin_required
def borrar_gasto(gid):
    with get_db() as conn:
        conn.execute("DELETE FROM gastos_gira WHERE id = ?", (gid,))
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/clientes/<int:cid>/mantenimientos", methods=["GET", "POST"])
@admin_required
def mantenimientos_cliente(cid):
    with get_db() as conn:
        if request.method == "GET":
            rows = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM mantenimientos WHERE cliente_id = ? ORDER BY fecha DESC, id DESC", (cid,)
                ).fetchall()
            ]
            return jsonify({"mantenimientos": rows})

        data = request.json
        conn.execute(
            "INSERT INTO mantenimientos (cliente_id, fecha, tipo, costo, observacion) VALUES (?, ?, ?, ?, ?)",
            (
                cid,
                data.get("fecha") or datetime.now().strftime("%Y-%m-%d"),
                data.get("tipo", "Repuesto / Servicio").strip(),
                int(data.get("costo") or 0),
                data.get("observacion", "").strip()
            )
        )
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/mantenimientos/<int:mid>", methods=["DELETE"])
@admin_required
def borrar_mantenimiento(mid):
    with get_db() as conn:
        conn.execute("DELETE FROM mantenimientos WHERE id = ?", (mid,))
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/exportar-excel", methods=["GET"])
@admin_required
def exportar_excel():
    limite_3m = (datetime.now().date() - timedelta(days=90)).strftime("%Y-%m-%d")
    with get_db() as conn:
        rows = conn.execute("""
            SELECT c.mesa_num, c.senor, c.ciudad, c.lugar, c.calle, c.ci, c.tarifa, c.maps_url,
                   COALESCE((SELECT reloj FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS ultimo_reloj,
                   COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
                   COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual,
                   COALESCE((SELECT SUM(cant_jug) FROM lecturas WHERE cliente_id = c.id AND fecha >= ?), 0) AS juegos_3m
            FROM clientes c
            WHERE c.activo = 1
            ORDER BY c.ciudad ASC, CAST(c.mesa_num AS INTEGER) ASC
        """, (limite_3m,)).fetchall()

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output, delimiter=";")
    writer.writerow([
        "Mesa N°", "Cliente", "Ciudad", "Lugar", "Calle / Celular", "C.I.",
        "Tarifa Gs.", "Último Reloj", "Última Visita", "Saldo a Cobrar Gs.",
        "Juegos (Últimos 3m)", "Link Google Maps"
    ])
    for r in rows:
        writer.writerow([
            r["mesa_num"], r["senor"], r["ciudad"], r["lugar"], r["calle"], r["ci"],
            r["tarifa"], r["ultimo_reloj"], r["ultima_fecha"], r["saldo_actual"],
            r["juegos_3m"], r["maps_url"]
        ])

    nombre = f"JuegosPatri_Reporte_{datetime.now().strftime('%Y-%m-%d')}.csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={nombre}"}
    )


@app.route("/api/mapa-clientes", methods=["GET"])
@login_required
def mapa_clientes():
    hoy = datetime.now().date()
    limite_2_meses = (hoy - timedelta(days=60)).strftime("%Y-%m-%d")

    sql = """
        SELECT c.*,
               COALESCE((SELECT reloj FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS ultimo_reloj,
               COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
               COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual
        FROM clientes c
        WHERE c.activo = 1
        ORDER BY c.ciudad ASC, CAST(c.mesa_num AS INTEGER) ASC, c.mesa_num ASC
    """

    with get_db() as conn:
        filas = [dict(r) for r in conn.execute(sql).fetchall()]

    con_coords = []
    pendientes_sync = 0
    ciudades = set()

    for f in filas:
        if f.get("ciudad") and f["ciudad"].strip():
            ciudades.add(f["ciudad"].strip())
        f["sin_visita_2m"] = (not f["ultima_fecha"]) or (f["ultima_fecha"] <= limite_2_meses)
        if f.get("lat") is not None and f.get("lng") is not None:
            con_coords.append(f)
        elif (f.get("maps_url") or "").strip():
            pendientes_sync += 1

    return jsonify({
        "clientes": con_coords,
        "ciudades": sorted(ciudades, key=lambda x: x.lower()),
        "pendientes_sync": pendientes_sync
    })


@app.route("/api/sincronizar-gps", methods=["POST"])
@admin_required
def sincronizar_gps():
    actualizados = 0
    fallidos = 0
    with get_db() as conn:
        filas = conn.execute(
            "SELECT id, maps_url FROM clientes WHERE activo = 1 AND maps_url != '' AND (lat IS NULL OR lng IS NULL)"
        ).fetchall()
        for f in filas:
            lat, lng = extraer_coordenadas_maps(f["maps_url"])
            if lat is not None and lng is not None:
                conn.execute("UPDATE clientes SET lat=?, lng=? WHERE id=?", (lat, lng, f["id"]))
                actualizados += 1
            else:
                fallidos += 1
    if actualizados > 0:
        crear_backup_automatico()
    return jsonify({"ok": True, "actualizados": actualizados, "fallidos": fallidos})


@app.route("/api/ciudades-resumen", methods=["GET"])
@admin_required
def resumen_ciudades():
    umbral_juegos = int(request.args.get("umbral_juegos", 60))
    hoy = datetime.now().date()
    limite_2_meses = (hoy - timedelta(days=60)).strftime("%Y-%m-%d")
    limite_3_meses = (hoy - timedelta(days=90)).strftime("%Y-%m-%d")

    sql = """
        SELECT c.*,
               COALESCE((SELECT reloj FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS ultimo_reloj,
               COALESCE((SELECT fecha FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), '') AS ultima_fecha,
               COALESCE((SELECT saldo_resultante FROM lecturas WHERE cliente_id = c.id ORDER BY id DESC LIMIT 1), 0) AS saldo_actual,
               COALESCE((
                   SELECT SUM(cant_jug)
                   FROM lecturas
                   WHERE cliente_id = c.id AND fecha >= ?
               ), 0) AS juegos_3m
        FROM clientes c
        WHERE c.activo = 1
        ORDER BY c.ciudad ASC, CAST(c.mesa_num AS INTEGER) ASC, c.mesa_num ASC
    """

    with get_db() as conn:
        filas = [dict(r) for r in conn.execute(sql, (limite_3_meses,)).fetchall()]

    grupos = {}
    for f in filas:
        ciudad_nombre = f["ciudad"].strip() if f["ciudad"] and f["ciudad"].strip() else "Sin Ciudad Especificada"
        sin_visita_2m = (not f["ultima_fecha"]) or (f["ultima_fecha"] <= limite_2_meses)
        tiene_pendiente = f["saldo_actual"] > 0
        baja_rotacion_3m = int(f["juegos_3m"] or 0) < umbral_juegos

        f["sin_visita_2m"] = sin_visita_2m
        f["tiene_pendiente"] = tiene_pendiente
        f["baja_rotacion_3m"] = baja_rotacion_3m

        if ciudad_nombre not in grupos:
            grupos[ciudad_nombre] = {
                "ciudad": ciudad_nombre,
                "total_mesas": 0,
                "pendientes": [],
                "sin_visita_2m": [],
                "baja_rotacion_3m": [],
                "al_dia": [],
                "total_a_cobrar": 0
            }

        g = grupos[ciudad_nombre]
        g["total_mesas"] += 1
        if tiene_pendiente:
            g["pendientes"].append(f)
            g["total_a_cobrar"] += f["saldo_actual"]
        if sin_visita_2m:
            g["sin_visita_2m"].append(f)
        if baja_rotacion_3m:
            g["baja_rotacion_3m"].append(f)
        if not tiene_pendiente and not sin_visita_2m and not baja_rotacion_3m:
            g["al_dia"].append(f)

    lista_ciudades = sorted(grupos.values(), key=lambda x: x["ciudad"].lower())
    return jsonify({
        "ciudades": lista_ciudades,
        "umbral_juegos": umbral_juegos,
        "limite_2_meses": limite_2_meses,
        "limite_3_meses": limite_3_meses
    })


@app.route("/api/clientes", methods=["POST"])
@login_required
def crear_cliente():
    data = request.json
    maps_url = data.get("maps_url", "").strip()
    lat, lng = extraer_coordenadas_maps(maps_url)
    if lat is None and data.get("lat") not in (None, "") and data.get("lng") not in (None, ""):
        try:
            lat = float(data["lat"])
            lng = float(data["lng"])
            if not maps_url:
                maps_url = f"https://www.google.com/maps?q={lat},{lng}"
        except ValueError:
            lat, lng = None, None
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO clientes (mesa_num, senor, ciudad, calle, lugar, ci, tarifa, maps_url, lat, lng, notas)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                data.get("mesa_num", "").strip(),
                data.get("senor", "").strip(),
                data.get("ciudad", "").strip(),
                data.get("calle", "").strip(),
                data.get("lugar", "").strip(),
                data.get("ci", "").strip(),
                int(data.get("tarifa", 1000)),
                maps_url,
                lat,
                lng,
                data.get("notas", "").strip()
            )
        )
        cid = cur.lastrowid
        reloj_inicial = data.get("reloj_inicial")
        if reloj_inicial not in (None, ""):
            conn.execute(
                "INSERT INTO lecturas (cliente_id, fecha, reloj, cant_jug, total_gs, entrega, saldo_resultante) VALUES (?, ?, ?, 0, 0, 0, 0)",
                (cid, data.get("fecha_inicial") or datetime.now().strftime("%Y-%m-%d"), int(reloj_inicial))
            )
    crear_backup_automatico()
    return jsonify({"ok": True, "id": cid})


@app.route("/api/clientes/<int:cid>", methods=["GET", "PUT", "DELETE"])
@login_required
def detalle_cliente(cid):
    if request.method in ("PUT", "DELETE") and session.get("role") != "admin":
        return jsonify({"error": "Solo administrador"}), 403

    with get_db() as conn:
        if request.method == "GET":
            c = conn.execute("SELECT * FROM clientes WHERE id = ?", (cid,)).fetchone()
            if not c:
                return jsonify({"error": "No encontrado"}), 404
            lecturas = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM lecturas WHERE cliente_id = ? ORDER BY id ASC", (cid,)
                ).fetchall()
            ]
            mantenimientos = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM mantenimientos WHERE cliente_id = ? ORDER BY fecha DESC, id DESC", (cid,)
                ).fetchall()
            ]
            fotos = [
                dict(r) for r in conn.execute(
                    "SELECT * FROM fotos_cliente WHERE cliente_id = ? ORDER BY id DESC", (cid,)
                ).fetchall()
            ]
            return jsonify({
                "cliente": dict(c),
                "lecturas": lecturas,
                "mantenimientos": mantenimientos,
                "fotos": fotos
            })

        if request.method == "PUT":
            data = request.json
            maps_url = data.get("maps_url", "").strip()
            lat, lng = extraer_coordenadas_maps(maps_url)
            conn.execute(
                """UPDATE clientes
                   SET mesa_num=?, senor=?, ciudad=?, calle=?, lugar=?, ci=?, tarifa=?, maps_url=?, lat=?, lng=?, notas=?
                   WHERE id=?""",
                (
                    data.get("mesa_num", "").strip(),
                    data.get("senor", "").strip(),
                    data.get("ciudad", "").strip(),
                    data.get("calle", "").strip(),
                    data.get("lugar", "").strip(),
                    data.get("ci", "").strip(),
                    int(data.get("tarifa", 1000)),
                    maps_url,
                    lat,
                    lng,
                    data.get("notas", "").strip(),
                    cid
                )
            )
            recalcular_cadena(conn, cid)
            crear_backup_automatico()
            return jsonify({"ok": True})

        if request.method == "DELETE":
            conn.execute("UPDATE clientes SET activo = 0 WHERE id = ?", (cid,))
            crear_backup_automatico()
            return jsonify({"ok": True})


@app.route("/api/clientes/<int:cid>/lecturas", methods=["POST"])
@login_required
def agregar_lectura(cid):
    data = request.json
    fecha = data.get("fecha") or datetime.now().strftime("%Y-%m-%d")
    reloj = int(data["reloj"])
    entrega = int(data.get("entrega") or 0)
    obs = data.get("observacion", "").strip()

    with get_db() as conn:
        ultima = conn.execute(
            "SELECT reloj FROM lecturas WHERE cliente_id = ? ORDER BY id DESC LIMIT 1", (cid,)
        ).fetchone()
        if ultima and reloj < ultima["reloj"]:
            return jsonify({"error": f"El reloj ({reloj}) no puede ser menor al anterior ({ultima['reloj']})"}), 400

        conn.execute(
            "INSERT INTO lecturas (cliente_id, fecha, reloj, entrega, observacion) VALUES (?, ?, ?, ?, ?)",
            (cid, fecha, reloj, entrega, obs)
        )
        recalcular_cadena(conn, cid)
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/lecturas/<int:lid>", methods=["PUT", "DELETE"])
@admin_required
def editar_lectura(lid):
    with get_db() as conn:
        row = conn.execute("SELECT cliente_id FROM lecturas WHERE id = ?", (lid,)).fetchone()
        if not row:
            return jsonify({"error": "No encontrado"}), 404
        cid = row["cliente_id"]

        if request.method == "DELETE":
            conn.execute("DELETE FROM lecturas WHERE id = ?", (lid,))
        else:
            data = request.json
            conn.execute(
                "UPDATE lecturas SET fecha=?, reloj=?, entrega=?, observacion=? WHERE id=?",
                (data["fecha"], int(data["reloj"]), int(data.get("entrega") or 0), data.get("observacion", ""), lid)
            )
        recalcular_cadena(conn, cid)
    crear_backup_automatico()
    return jsonify({"ok": True})


@app.route("/api/descargar-db")
@admin_required
def descargar_db():
    crear_backup_automatico()
    nombre = f"JuegosPatri_Respaldo_{datetime.now().strftime('%Y-%m-%d_%H%M')}.db"
    return send_file(DB_PATH, as_attachment=True, download_name=nombre)


init_db()

if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5050))
    es_nube = bool(os.environ.get("RENDER") or os.environ.get("PORT"))
    if not es_nube:
        Timer(1.2, lambda: webbrowser.open(f"http://127.0.0.1:{puerto}")).start()
    app.run(host="0.0.0.0", port=puerto, debug=False)