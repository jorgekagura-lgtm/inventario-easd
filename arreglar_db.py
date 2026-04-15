import sqlite3

# Conectamos a tu archivo local
conn = sqlite3.connect('inventario_easd.db')
cursor = conn.cursor()

try:
    print("Intentando añadir la columna...")
    cursor.execute("ALTER TABLE equipos ADD COLUMN preparado INTEGER DEFAULT 0")
    conn.commit()
    print("✅ ¡Éxito! Columna 'preparado' añadida correctamente.")
except sqlite3.OperationalError as e:
    print(f"❌ Error o aviso: {e}")
    print("Es posible que la columna ya exista.")
finally:
    conn.close()