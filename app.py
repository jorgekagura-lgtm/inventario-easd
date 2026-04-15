import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash

app = Flask(__name__)
# Render necesita una clave secreta. Si no existe en el entorno, usa una por defecto
app.secret_key = os.environ.get("SECRET_KEY", "clave_segura_por_defecto")

# CONFIGURACIÓN DE BASE DE DATOS (Neon)
# En Render, crearemos una variable de entorno llamada DATABASE_URL
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    # Nos conectamos a Neon usando la URL
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    # SQL optimizado para PostgreSQL
    cur.execute('''
        CREATE TABLE IF NOT EXISTS equipos (
            id SERIAL PRIMARY KEY,
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

# Inicializa la base de datos al arrancar
if DATABASE_URL:
    init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/sede/<nombre_sede>')
def ver_sede(nombre_sede):
    categoria = request.args.get('cat')
    estado = request.args.get('estado')
    
    if not categoria:
        return render_template('sede.html', sede=nombre_sede)

    if categoria == 'HP' and not estado:
        return render_template('seleccion_hp.html', sede=nombre_sede, categoria=categoria)
    
    if categoria == 'MACS' and not estado:
        return render_template('seleccion_macs.html', sede=nombre_sede, categoria=categoria)
    
    if categoria == 'OTROS' and not estado:
        return render_template('seleccion_otros.html', sede=nombre_sede, categoria=categoria)

    if categoria == 'APDS':
        estado = 'Retirada'
    elif not estado:
        estado = 'Activo'

    conn = get_db_connection()
    # Usamos RealDictCursor para que se comporte como el Row de sqlite3
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('''
        SELECT * FROM equipos 
        WHERE sede = %s AND categoria = %s AND estado = %s
        ORDER BY ubicacion ASC, id ASC
    ''', (nombre_sede, categoria, estado))
    equipos_db = cur.fetchall()
    cur.close()
    conn.close()
    
    return render_template('categoria.html', 
                           sede=nombre_sede, equipos=equipos_db, 
                           categoria=categoria, estado=estado)

@app.route('/formulario/<sede>/<categoria>')
def formulario_nuevo(sede, categoria):
    estado_defecto = request.args.get('estado', 'Activo')
    ultima_ubicacion = request.args.get('last_ub', '')
    
    if categoria == 'APDS':
        estado_defecto = 'Retirada'
        
    return render_template('nuevo_registro.html', 
                           sede=sede, 
                           categoria=categoria, 
                           equipo=None, 
                           estado=estado_defecto,
                           last_ub=ultima_ubicacion)

@app.route('/agregar_equipo', methods=['POST'])
def agregar_equipo():
    sede = request.form['sede']
    categoria = request.form['categoria']
    ubicacion = request.form['ubicacion'].strip()
    estado = request.form.get('estado', 'Activo')
    
    if categoria == 'APDS':
        estado = 'Retirada'
        valor_preparado = 1 if request.form.get('preparado') else 0
    else:
        valor_preparado = int(request.form.get('tipo_pantalla', 0))
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute('''
            INSERT INTO equipos (
                sede, categoria, ubicacion, ns_torre, id_inv_torre, 
                ns_monitor, id_inv_monitor, aplicaciones, anotaciones, 
                estado, preparado
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (sede, categoria, ubicacion, 
              request.form.get('ns_torre', '').strip(), 
              request.form.get('id_inv_torre', '').strip(), 
              request.form.get('ns_monitor', '').strip(), 
              request.form.get('id_inv_monitor', '').strip(), 
              request.form.get('aplicaciones', '').strip(), 
              request.form.get('anotaciones', '').strip(), 
              estado, valor_preparado))
        conn.commit()
        cur.close()
        conn.close()
        flash(f"¡Guardado con éxito!")
    except Exception as e:
        flash(f"Error al guardar: {str(e)}")

    return redirect(url_for('formulario_nuevo', sede=sede, categoria=categoria, estado=estado, last_ub=ubicacion))

@app.route('/editar_equipo/<int:id>')
def editar_equipo(id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT * FROM equipos WHERE id = %s', (id,))
    equipo = cur.fetchone()
    cur.close()
    conn.close()
    return render_template('nuevo_registro.html', 
                           equipo=equipo, 
                           sede=equipo['sede'], 
                           categoria=equipo['categoria'], 
                           estado=equipo['estado'])

@app.route('/actualizar_equipo', methods=['POST'])
def actualizar_equipo():
    id_equipo = request.form['id']
    sede = request.form['sede']
    categoria = request.form['categoria']
    estado = request.form.get('estado', 'Activo')

    if categoria == 'APDS':
        valor_preparado = 1 if request.form.get('preparado') else 0
    else:
        valor_preparado = int(request.form.get('tipo_pantalla', 0))
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        UPDATE equipos SET 
            ubicacion = %s, ns_torre = %s, id_inv_torre = %s, 
            ns_monitor = %s, id_inv_monitor = %s, 
            aplicaciones = %s, anotaciones = %s, estado = %s, preparado = %s
        WHERE id = %s
    ''', (request.form['ubicacion'].strip(), 
          request.form.get('ns_torre', '').strip(), 
          request.form.get('id_inv_torre', '').strip(), 
          request.form.get('ns_monitor', '').strip(), 
          request.form.get('id_inv_monitor', '').strip(), 
          request.form.get('aplicaciones', '').strip(), 
          request.form.get('anotaciones', '').strip(), 
          estado, valor_preparado, id_equipo))
    conn.commit()
    cur.close()
    conn.close()
    
    return redirect(url_for('ver_sede', nombre_sede=sede, cat=categoria, estado=estado))

@app.route('/eliminar_equipo/<int:id>/<sede>/<categoria>')
def eliminar_equipo(id, sede, categoria):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=RealDictCursor)
    cur.execute('SELECT estado FROM equipos WHERE id = %s', (id,))
    equipo = cur.fetchone()
    estado = equipo['estado'] if equipo else 'Activo'
    cur.execute('DELETE FROM equipos WHERE id = %s', (id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for('ver_sede', nombre_sede=sede, cat=categoria, estado=estado))

if __name__ == '__main__':
    # Importante para Render: el puerto se toma del entorno
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)