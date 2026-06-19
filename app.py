import os
import sqlite3
import psycopg2
import re
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

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
    query = request.args.get('q', '').strip()
    if not query:
        return redirect(url_for('index'))
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()

    if query.startswith('\\'):
        search_term = query[1:].lower()
        search_pattern = f"%{search_term}"
    elif query.startswith('/') and query.endswith('/'):
        search_term = query[1:-1].lower()
        search_pattern = f"%{search_term}%"
    elif query.startswith('/'):
        search_term = query[1:].lower()
        search_pattern = f"{search_term}%"
    else:
        search_term = query.lower()
        search_pattern = f"%{search_term}%"

    if IS_HEROKU:
        sql = '''
            SELECT * FROM equipos 
            WHERE ns_torre ILIKE %s OR ns_monitor ILIKE %s OR id_inv_torre ILIKE %s OR id_inv_monitor ILIKE %s OR ubicacion ILIKE %s
        '''
    else:
        sql = '''
            SELECT * FROM equipos 
            WHERE LOWER(ns_torre) LIKE ? OR LOWER(ns_monitor) LIKE ? OR LOWER(id_inv_torre) LIKE ? OR LOWER(id_inv_monitor) LIKE ? OR LOWER(ubicacion) LIKE ?
        '''
    
    cur.execute(sql, (search_pattern,)*5)
    resultados = cur.fetchall()
    conn.close()
    
    equipos = [dict(r) for r in resultados]
    return render_template('resultados_busqueda.html', equipos=equipos, query=query)

@app.route('/sede/<nombre_sede>/todo')
@app.route('/sede/<nombre_sede>/todos') 
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

@app.route('/editar_equipo/<int:id>')
def editar_equipo(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    sql = 'SELECT * FROM equipos WHERE id = %s' if IS_HEROKU else 'SELECT * FROM equipos WHERE id = ?'
    cur.execute(sql, (id,))
    equipo = cur.fetchone()
    conn.close()
    
    if equipo:
        e_dict = dict(equipo)
        return render_template('nuevo_registro.html', sede=e_dict['sede'], categoria=e_dict['categoria'], equipo=e_dict, estado=e_dict['estado'], last_ub='')
    flash("Equipo no encontrado")
    return redirect(url_for('index'))

@app.route('/agregar_equipo', methods=['POST'])
def agregar_equipo():
    d = request.form
    ns_torre = d.get('ns_torre', '').strip()
    ns_monitor = d.get('ns_monitor', '').strip()
    ph = "%s" if IS_HEROKU else "?"
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    
    # 1. VERIFICACIÓN DE DUPLICADOS EN ALTAS
    equipo_duplicado = None
    if ns_torre or ns_monitor:
        sql_check = f"""
            SELECT * FROM equipos 
            WHERE 
                ({ph} != '' AND (ns_torre = {ph} OR ns_monitor = {ph}))
                OR 
                ({ph} != '' AND (ns_torre = {ph} OR ns_monitor = {ph}))
        """
        cur.execute(sql_check, (ns_torre, ns_torre, ns_torre, ns_monitor, ns_monitor, ns_monitor))
        res = cur.fetchone()
        if res:
            equipo_duplicado = dict(res)
            
    if equipo_duplicado:
        # En vez de hacer un return inmediato, lanzamos un flash de aviso ("warning") y permitimos que continue el flujo
        serie_chocado = ns_torre if (ns_torre and (equipo_duplicado['ns_torre'] == ns_torre or equipo_duplicado['ns_monitor'] == ns_torre)) else ns_monitor
        flash(f"⚠️ Advertencia: El número de serie '{serie_chocado}' está repetido. Ya existe en Sede: {equipo_duplicado['sede']} | Ubicación: {equipo_duplicado['ubicacion']} | Categoría: {equipo_duplicado['categoria']}.", "warning")
    
    # 2. PROCESADO DEL VALOR PREPARADO
    try:
        if d.get('preparado') == 'on':
            valor_preparado = 1
        else:
            valor_preparado = int(d.get('preparado', 0))
    except (ValueError, TypeError):
        valor_preparado = 0

    # Recogemos el valor de las aplicaciones (siempre en español)
    info_apps = d.get('aplicaciones', d.get('applications', ''))

    # 3. INSERCIÓN (Corregido a la columna "aplicaciones")
    try:
        sql = f'''INSERT INTO equipos (sede, categoria, ubicacion, ns_torre, id_inv_torre, ns_monitor, id_inv_monitor, aplicaciones, anotaciones, estado, preparado)
                  VALUES ({ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph},{ph})'''

        cur.execute(sql, (d['ubicacion'].strip(), ns_torre, d.get('id_inv_torre',''), 
                          ns_monitor, d.get('id_inv_monitor',''), info_apps, d.get('anotaciones',''), 
                          d.get('estado', 'Activo'), valor_preparado))
        conn.commit()
        flash("✅ Guardado correctamente en el sistema", "success")
    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Error Crítico de Base de Datos: {str(e)}", "danger")
    finally:
        cur.close()
        conn.close()

    return redirect(url_for('formulario_nuevo', sede=d['sede'], categoria=d['categoria'], estado=d.get('estado'), last_ub=d['ubicacion']))


@app.route('/actualizar_equipo', methods=['POST'])
def actualizar_equipo():
    d = request.form
    equipo_id = d['id']
    ns_torre = d.get('ns_torre', '').strip()
    ns_monitor = d.get('ns_monitor', '').strip()
    ph = "%s" if IS_HEROKU else "?"
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
    
    # 1. VERIFICACIÓN DE DUPLICADOS EN EDICIONES
    equipo_duplicado = None
    if ns_torre or ns_monitor:
        sql_check = f"""
            SELECT * FROM equipos 
            WHERE (
                ({ph} != '' AND (ns_torre = {ph} OR ns_monitor = {ph}))
                OR 
                ({ph} != '' AND (ns_torre = {ph} OR ns_monitor = {ph}))
            ) AND id != {ph}
        """
        cur.execute(sql_check, (ns_torre, ns_torre, ns_torre, ns_monitor, ns_monitor, ns_monitor, equipo_id))
        res = cur.fetchone()
        if res:
            equipo_duplicado = dict(res)
            
    if equipo_duplicado:
        # En vez de hacer un return inmediato, lanzamos un flash de aviso ("warning") y permitimos que continue el flujo
        serie_chocado = ns_torre if (ns_torre and (equipo_duplicado['ns_torre'] == ns_torre or equipo_duplicado['ns_monitor'] == ns_torre)) else ns_monitor
        flash(f"⚠️ Advertencia al actualizar: El número de serie '{serie_chocado}' se ha guardado repetido. También pertenece al equipo en Sede: {equipo_duplicado['sede']} | Ubicación: {equipo_duplicado['ubicacion']}.", "warning")

    # 2. PROCESADO DEL VALOR PREPARADO
    try:
        if d.get('preparado') == 'on':
            valor_preparado = 1
        else:
            valor_preparado = int(d.get('preparado', 0))
    except (ValueError, TypeError):
        valor_preparado = 0
        
    info_apps = d.get('aplicaciones', d.get('applications', ''))
        
    # 3. ACTUALIZACIÓN (Corregido a la columna "aplicaciones")
    try:
        sql = f'''UPDATE equipos SET ubicacion={ph}, ns_torre={ph}, id_inv_torre={ph}, ns_monitor={ph}, id_inv_monitor={ph}, 
                  aplicaciones={ph}, anotaciones={ph}, estado={ph}, preparado={ph} WHERE id={ph}'''
        
        cur.execute(sql, (d['ubicacion'].strip(), ns_torre, d.get('id_inv_torre',''), ns_monitor, d.get('id_inv_monitor',''), 
                          info_apps, d.get('anotaciones',''), d.get('estado'), valor_preparado, equipo_id))
        conn.commit()
        flash("✅ Equipo actualizado correctamente", "success")
    except Exception as e:
        conn.rollback()
        flash(f"⚠️ Error al actualizar en Base de Datos: {str(e)}", "danger")
    finally:
        cur.close()
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

# ==========================================
#   API PARA LA APLICACIÓN MÓVIL
# ==========================================

@app.route('/api/equipo/<serial>', methods=['GET'])
def api_consultar_equipo(serial):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor) if IS_HEROKU else conn.cursor()
        
        if IS_HEROKU:
            sql = "SELECT id, sede, categoria, ubicacion, ns_torre, ns_monitor, preparado FROM equipos WHERE ns_torre = %s OR ns_monitor = %s"
        else:
            sql = "SELECT id, sede, categoria, ubicacion, ns_torre, ns_monitor, preparado FROM equipos WHERE ns_torre = ? OR ns_monitor = ?"
            
        cur.execute(sql, (serial, serial))
        equipo = cur.fetchone()
        
        cur.close()
        conn.close()
        
        if equipo:
            return jsonify(dict(equipo)), 200
        else:
            return jsonify({"error": "El número de serie no existe en el sistema"}), 404
            
    except Exception as e:
        return jsonify({"error": f"Error de servidor: {str(e)}"}), 500

@app.route('/api/equipo/actualizar', methods=['POST'])
def api_actualizar_ubicacion():
    try:
        datos = request.get_json()
        equipo_id = datos.get('id')
        nueva_ubicacion = datos.get('nueva_ubicacion')
        
        if not equipo_id or not nueva_ubicacion:
            return jsonify({"error": "Faltan datos obligatorios (id o nueva_ubicacion)"}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        
        if IS_HEROKU:
            sql = "UPDATE equipos SET ubicacion = %s WHERE id = %s"
        else:
            sql = "UPDATE equipos SET ubicacion = ? WHERE id = ?"
            
        cur.execute(sql, (nueva_ubicacion.strip(), equipo_id))
        conn.commit()
        
        cur.close()
        conn.close()
        
        return jsonify({"mensaje": "Ubicación actualizada con éxito en tiempo real"}), 200
        
    except Exception as e:
        return jsonify({"error": f"No se pudo actualizar: {str(e)}"}), 500

if __name__ == '__main__':
    if IS_HEROKU:
        port = int(os.environ.get("PORT", 5000))
        app.run(host='0.0.0.0', port=port)
    else:
        app.run(debug=True)
