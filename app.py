import os
import sqlite3
import psycopg2
import re
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
# Usa la variable de entorno en la nube o una clave por defecto en local
app.secret_key = os.environ.get("SECRET_KEY", "inventario_easd_secret")

# --- DETECCIÓN DE ENTORNO ---
DATABASE_URL = os.environ.get('DATABASE_URL')
IS_HEROKU = DATABASE_URL is not None

def get_db_connection():
    if IS_HEROKU:
        # Configuración para Nube (PostgreSQL)
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        return conn
    else:
        # Configuración para Local (SQLite)
        conn = sqlite3.connect('inventario_easd.db')
        conn.row_factory = sqlite3.Row
        return conn

# --- LÓGICA DE ORDENACIÓN UNIFICADA (La más completa) ---
def obtener_prioridad(ubicacion):
    if not ubicacion:
        return (10, 0, 0)
    
    ubi = str(ubicacion).upper().strip()
    
    # 1. PRIORIDAD: Aulas estándar (Ej: "Aula 1.1", "1.10")
    match_num = re.search(r"(\d+)\.(\d+)", ubi)
    if match_num and "ENTRE" not in ubi:
        piso = int(match_num.group(1))
        aula = int(match_num.group(2))
        return (1, piso, aula)

    # 2. PRIORIDAD: Entre aulas
    if "ENTRE" in ubi:
        match_piso = re.search(r"(\d+)", ubi)
        piso = int(match_piso.group(1)) if match_piso else 0
        return (2, piso, ubi)

    # 3. PRIORIDAD: Planta Baja
    if 'B' in ubi and 'DPTO' not in ubi:
        num_b = re.search(r'\d+', ubi)
        val = int(num_b.group()) if num_b else 0
        return (3, val, 0)
        
    # 4. PRIORIDAD: Sótano
    if 'S' in ubi:
        num_s = re.search(r'\d+', ubi)
        val = int(num_s.group()) if num_s else 0
        return (4, val, 0)

    # 5. PRIORIDAD: Departamentos
    if 'DPTO' in ubi or 'DEPARTAMENTO' in ubi:
        return (5, 0, ubi)
        
    return (6, 0, ubi)

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # Sintaxis compatible con ambos (SERIAL en Postgres / AUTOINCREMENT en SQLite)
    id_type = "SERIAL PRIMARY KEY" if IS_HEROKU else "INTEGER PRIMARY KEY AUTOINCREMENT"
    
    cur.execute(f'''
        CREATE TABLE IF NOT EXISTS equipos (
            id {id_type},
            sede TEXT NOT NULL,
            categoria TEXT NOT NULL,
            ubicacion TEXT,
            ns_torre TEXT,
            id_inv_torre TEXT,
            ns_monitor TEXT,
            id_inv_monitor TEXT,
            aplicaciones TEXT,
            anotaciones TEXT, 
            estado TEXT DEFAULT 'Activo',
            preparado INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# Inicializar DB al arrancar
init_db()

# --- RUTAS ---

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/buscar_global')
def buscar_global():
    # Mantenemos tu lógica de limpiar el query
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))
    
    # Creamos una versión en minúsculas para la búsqueda
    query_low = query.lower()
    
    conn = get_db_connection()
    # Mantenemos el cursor según el entorno
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    
    search_pattern = f"%{query_low}%"
    
    if IS_HEROKU:
        # Añadimos ILIKE para la nube sin quitar tus campos de búsqueda original
        sql = '''
            SELECT * FROM equipos 
            WHERE ns_torre ILIKE %s 
               OR ns_monitor ILIKE %s 
               OR id_inv_torre ILIKE %s 
               OR id_inv_monitor ILIKE %s 
               OR ubicacion ILIKE %s
        '''
    else:
        # Usamos LOWER() para local sin cambiar tu estructura original
        sql = '''
            SELECT * FROM equipos 
            WHERE LOWER(ns_torre) LIKE ? 
               OR LOWER(ns_monitor) LIKE ? 
               OR LOWER(id_inv_torre) LIKE ? 
               OR LOWER(id_inv_monitor) LIKE ? 
               OR LOWER(ubicacion) LIKE ?
        '''
    
    cur.execute(sql, (search_pattern,)*5)
    resultados = cur.fetchall()
    conn.close()
    
    # Mantenemos tu conversión a diccionario y el render exacto de tu local
    equipos = [dict(r) for r in resultados]
    return render_template('resultados_busqueda.html', equipos=equipos, query=query)
def ver_todos(nombre_sede):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    
    sql = "SELECT * FROM equipos WHERE sede = %s" if IS_HEROKU else "SELECT * FROM equipos WHERE sede = ?"
    cur.execute(sql, (nombre_sede,))
    todos = cur.fetchall()
    conn.close()

    inventario = {}
    for equipo in todos:
        e_dict = dict(equipo)
        cat, est = e_dict['categoria'], e_dict['estado']
        if cat not in inventario: inventario[cat] = {}
        if est not in inventario[cat]: inventario[cat][est] = []
        inventario[cat][est].append(e_dict)

    for cat in inventario:
        for est in inventario[cat]:
            inventario[cat][est].sort(key=lambda x: obtener_prioridad(x['ubicacion']))

    return render_template('todo_velluters.html', sede=nombre_sede, inventario=inventario)

@app.route('/sede/<nombre_sede>')
def ver_sede(nombre_sede):
    categoria = request.args.get('cat')
    estado = request.args.get('estado', 'Activo')
    
    if not categoria:
        return render_template('sede.html', sede=nombre_sede)

    if categoria in ['HP', 'MACS', 'OTROS'] and not request.args.get('estado'):
        return render_template(f'seleccion_{categoria.lower()}.html', sede=nombre_sede, categoria=categoria)

    if categoria == 'APDS': estado = 'Retirada'

    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    
    sql = 'SELECT * FROM equipos WHERE sede=%s AND categoria=%s AND estado=%s' if IS_HEROKU else 'SELECT * FROM equipos WHERE sede=? AND categoria=? AND estado=?'
    cur.execute(sql, (nombre_sede, categoria, estado))
    equipos_db = cur.fetchall()
    conn.close()
    
    equipos_ordenados = sorted([dict(e) for e in equipos_db], key=lambda x: obtener_prioridad(x['ubicacion']))
    return render_template('categoria.html', sede=nombre_sede, equipos=equipos_ordenados, categoria=categoria, estado=estado)

@app.route('/formulario/<sede>/<categoria>')
def formulario_nuevo(sede, categoria):
    estado_defecto = request.args.get('estado', 'Activo')
    if categoria == 'APDS': estado_defecto = 'Retirada'
    return render_template('nuevo_registro.html', sede=sede, categoria=categoria, equipo=None, estado=estado_defecto, last_ub=request.args.get('last_ub', ''))

@app.route('/agregar_equipo', methods=['POST'])
def agregar_equipo():
    d = request.form
    conn = get_db_connection()
    cur = conn.cursor()
    
    ph = "%s" if IS_HEROKU else "?"
    sql = f'''INSERT INTO equipos (sede, categoria, ubicacion, ns_torre, id_inv_torre, ns_monitor, id_inv_monitor, aplicaciones, anotaciones, estado, preparado)
              VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})'''
    
    # Manejo de 'preparado' o 'tipo_pantalla' según lo que venga del form
    valor_preparado = d.get('preparado') or d.get('tipo_pantalla') or 0

    cur.execute(sql, (d['sede'], d['categoria'], d['ubicacion'].strip(), d.get('ns_torre',''), d.get('id_inv_torre',''), 
                      d.get('ns_monitor',''), d.get('id_inv_monitor',''), d.get('aplicaciones',''), d.get('anotaciones',''), 
                      d.get('estado', 'Activo'), valor_preparado))
    conn.commit()
    conn.close()
    flash("Guardado correctamente")
    return redirect(url_for('formulario_nuevo', sede=d['sede'], categoria=d['categoria'], estado=d.get('estado'), last_ub=d['ubicacion']))

@app.route('/editar_equipo/<int:id>')
def editar_equipo(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    sql = 'SELECT * FROM equipos WHERE id = %s' if IS_HEROKU else 'SELECT * FROM equipos WHERE id = ?'
    cur.execute(sql, (id,))
    equipo = cur.fetchone()
    conn.close()
    return render_template('nuevo_registro.html', equipo=dict(equipo), sede=equipo['sede'], categoria=equipo['categoria'], estado=equipo['estado'])

@app.route('/actualizar_equipo', methods=['POST'])
def actualizar_equipo():
    d = request.form
    conn = get_db_connection()
    cur = conn.cursor()
    
    valor_preparado = d.get('preparado') or d.get('tipo_pantalla') or 0
    ph = "%s" if IS_HEROKU else "?"
    
    sql = f'''UPDATE equipos SET ubicacion={ph}, ns_torre={ph}, id_inv_torre={ph}, ns_monitor={ph}, id_inv_monitor={ph}, 
              aplicaciones={ph}, anotaciones={ph}, estado={ph}, preparado={ph} WHERE id={ph}'''
    
    cur.execute(sql, (d['ubicacion'].strip(), d.get('ns_torre',''), d.get('id_inv_torre',''), d.get('ns_monitor',''), d.get('id_inv_monitor',''), 
                      d.get('aplicaciones',''), d.get('anotaciones',''), d.get('estado'), valor_preparado, d['id']))
    conn.commit()
    conn.close()
    return redirect(url_for('ver_sede', nombre_sede=d['sede'], cat=d['categoria'], estado=d.get('estado')))

@app.route('/eliminar_equipo/<int:id>/<sede>/<categoria>/<estado>')
def eliminar_equipo(id, sede, categoria, estado):
    conn = get_db_connection()
    cur = conn.cursor()
    sql = 'DELETE FROM equipos WHERE id = %s' if IS_HEROKU else 'DELETE FROM equipos WHERE id = ?'
    cur.execute(sql, (id,))
    conn.commit()
    conn.close()
    return redirect(url_for('ver_sede', nombre_sede=sede, cat=categoria, estado=estado))

if __name__ == '__main__':
    if IS_HEROKU:
        port = int(os.environ.get("PORT", 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        app.run(debug=True)
