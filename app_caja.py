import streamlit as st
import pandas as pd
from datetime import datetime
import sqlite3

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(page_title="Pancito de la Erica - POS", layout="wide")

# --- CONEXIÓN Y BASE DE DATOS ---
conn = sqlite3.connect('pancito_erica_web.db', check_same_thread=False)
c = conn.cursor()

# 1. Crear tablas base si no existen
c.execute('''CREATE TABLE IF NOT EXISTS productos 
             (codigo TEXT PRIMARY KEY, nombre TEXT, precio REAL, stock INTEGER)''')

c.execute('''CREATE TABLE IF NOT EXISTS ventas 
             (id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT, total REAL, detalle TEXT)''')

# 2. Migración automática (Agrega método de pago si no existe en tablas antiguas)
c.execute("PRAGMA table_info(ventas)")
columnas_ventas = [col[1] for col in c.fetchall()]

if 'metodo_pago' not in columnas_ventas:
    c.execute("ALTER TABLE ventas ADD COLUMN metodo_pago TEXT DEFAULT 'No registrado'")

conn.commit()

# --- ESTADO DE LA SESIÓN ---
if 'carrito' not in st.session_state:
    st.session_state.carrito = []
if 'codigo_pendiente' not in st.session_state:
    st.session_state.codigo_pendiente = None

# Función auxiliar para formatear dinero estilo chileno (ej: $1.500)
def formato_peso(monto):
    return f"${monto:,.0f}".replace(",", ".")

st.title("🛒 Sistema de Control de Stock y Ventas - Pancito de la Erica")

# --- ORDEN DE PESTAÑAS ---
tab_venta, tab_stock, tab_historial = st.tabs([
    "💳 Nueva Venta", 
    "📦 Control de Stock Diario", 
    "🧾 Historial de Ventas"
])

# ==========================================
# PESTAÑA 1: NUEVA VENTA (CAJA REGISTRADORA)
# ==========================================
with tab_venta:
    st.subheader("Caja Registradora")
    
    # 1. ZONA DE ESCÁNER (Siempre arriba)
    with st.form("form_escaner", clear_on_submit=True):
        codigo_escaneado = st.text_input("Pistolear Código de Barras", key="escaner_input", help="Presiona Enter o deja que la pistola lo haga automáticamente")
        btn_escanear = st.form_submit_button("Agregar al carrito")
        
        if btn_escanear and codigo_escaneado:
            codigo = codigo_escaneado.strip()
            
            # Lógica para pan pesado en balanza (códigos EAN-13 que empiezan con '20')
            if len(codigo) == 13 and codigo.startswith("20"):
                precio_balanza = int(codigo[7:12])
                st.session_state.carrito.append({
                    "codigo": codigo, 
                    "nombre": "Pan (Pesado en balanza)", 
                    "precio": precio_balanza, 
                    "tipo": "balanza"
                })
            else:
                # Búsqueda de producto normal
                c.execute("SELECT nombre, precio FROM productos WHERE codigo=?", (codigo,))
                res = c.fetchone()
                if res:
                    st.session_state.carrito.append({
                        "codigo": codigo, 
                        "nombre": res[0], 
                        "precio": res[1], 
                        "tipo": "unidad"
                    })
                else:
                    # Guardamos el código no encontrado para registro rápido
                    st.session_state.codigo_pendiente = codigo

    # 2. VÍA RÁPIDA PARA PRODUCTO NUEVO EN PLENA VENTA (Aparece solo si el código no existe)
    if st.session_state.codigo_pendiente:
        st.error(f"⚠️ El código {st.session_state.codigo_pendiente} no está registrado.")
        
        with st.form("form_rapido_producto"):
            st.write("Regístralo rápido para continuar con esta venta:")
            col_n, col_p, col_b = st.columns([2, 1, 1])
            with col_n:
                nuevo_nombre = st.text_input("Nombre del producto", key="n_nombre")
            with col_p:
                nuevo_precio = st.number_input("Precio ($)", min_value=0.0, step=100.0, key="n_precio")
            with col_b:
                st.write("") 
                st.write("")
                btn_guardar_rapido = st.form_submit_button("Guardar y sumar a la boleta")
            
            if btn_guardar_rapido and nuevo_nombre:
                c.execute("INSERT INTO productos VALUES (?, ?, ?, ?)", (st.session_state.codigo_pendiente, nuevo_nombre, nuevo_precio, 0))
                conn.commit()
                st.session_state.carrito.append({
                    "codigo": st.session_state.codigo_pendiente, 
                    "nombre": nuevo_nombre, 
                    "precio": nuevo_precio, 
                    "tipo": "unidad"
                })
                st.session_state.codigo_pendiente = None 
                st.rerun()

    st.markdown("---")

    # 3. INTERFAZ DE CAJA FIJA (A DOS COLUMNAS)
    col_tabla, col_boleta = st.columns([1.5, 1.2])
    
    # --- COLUMNA IZQUIERDA: LISTA DE PRODUCTOS ---
    with col_tabla:
        st.markdown("### 🛒 Productos en Carrito")
        
        if st.session_state.carrito:
            df_carrito = pd.DataFrame(st.session_state.carrito)
            
            # Formateamos visualmente para la tabla
            df_vista = df_carrito[['codigo', 'nombre', 'precio']].copy()
            df_vista['precio'] = df_vista['precio'].apply(formato_peso)
            df_vista.columns = ['Código', 'Producto', 'Precio']
            
            st.dataframe(df_vista, use_container_width=True, hide_index=True)
            
            if st.button("🗑️ Vaciar Carrito / Cancelar Venta"):
                st.session_state.carrito = []
                st.rerun()
        else:
            # Estado vacío para que la interfaz no desaparezca
            st.info("Aún no has pistoleado ningún producto. Pasa un código de barras para agregarlo aquí.")

    # --- COLUMNA DERECHA: BOLETA Y COBRO ---
    with col_boleta:
        st.markdown("### 🧾 Resumen de Cobro")
        
        # Diseño de ticket/boleta virtual usando HTML (Siempre visible)
        html_ticket = """
        <div style='background-color: #1e1e1e; padding: 20px; border-radius: 8px; border: 1px solid #333; min-height: 200px; display: flex; flex-direction: column;'>
            <h4 style='text-align: center; margin-bottom: 20px; color: #f4f4f4;'>Boleta de Venta</h4>
            <div style='flex-grow: 1;'>
        """
        
        total = 0
        if st.session_state.carrito:
            for idx, item in enumerate(st.session_state.carrito):
                precio_fmt = formato_peso(item['precio'])
                html_ticket += f"<div style='display: flex; justify-content: space-between; margin-bottom: 8px; color: #ccc;'><span>{idx+1}. {item['nombre']}</span><span>{precio_fmt}</span></div>"
                total += item['precio']
        else:
            html_ticket += "<div style='text-align: center; color: #777; font-style: italic; margin-top: 20px;'>No hay productos</div>"
            
        html_ticket += f"""
            </div>
            <hr style='border-color: #555; margin-top: 20px; margin-bottom: 10px;'/>
            <div style='display: flex; justify-content: space-between; align-items: center;'>
                <h3 style='color: #f4f4f4; margin: 0;'>TOTAL A COBRAR:</h3>
                <h1 style='color: #2ecc71; margin: 0;'>{formato_peso(total)}</h1>
            </div>
        </div>
        """
        
        st.markdown(html_ticket, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Opciones de pago fijas
        st.markdown("**Seleccione Método de Pago:**")
        metodo_pago = st.radio("Método de Pago", ["Efectivo", "Débito", "Crédito"], horizontal=True, label_visibility="collapsed")
        
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Botón de cobro
        if st.button("💰 Procesar Pago y Finalizar Venta", type="primary", use_container_width=True):
            if not st.session_state.carrito:
                st.warning("⚠️ No puedes cobrar un carrito vacío. Pistolea un producto primero.")
            else:
                fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                nombres_productos = [item['nombre'] for item in st.session_state.carrito]
                detalle_venta = ", ".join(nombres_productos)
                
                # Insertar en BD de ventas
                c.execute("INSERT INTO ventas (fecha, total, detalle, metodo_pago) VALUES (?, ?, ?, ?)", 
                          (fecha_actual, total, detalle_venta, metodo_pago))
                
                # Descontar stock (solo si no es de balanza)
                for item in st.session_state.carrito:
                    if item['tipo'] == 'unidad':
                        c.execute("UPDATE productos SET stock = stock - 1 WHERE codigo=?", (item['codigo'],))
                
                conn.commit()
                st.session_state.carrito = [] 
                st.success(f"✅ ¡Venta procesada correctamente! Pago recibido con {metodo_pago}.")
                st.rerun()

# ==========================================
# PESTAÑA 2: CONTROL DE STOCK DIARIO
# ==========================================
with tab_stock:
    st.subheader("Gestión de Inventario")
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.markdown("### ➕ Ingreso de Mercadería")
        with st.form("form_nuevo_producto_stock", clear_on_submit=True):
            codigo_stock = st.text_input("Código de barras / SKU")
            nombre_stock = st.text_input("Nombre del producto")
            precio_stock = st.number_input("Precio de venta ($)", min_value=0.0, step=100.0)
            cantidad_stock = st.number_input("Cantidad a ingresar", min_value=1, step=1)
            submit_stock = st.form_submit_button("Registrar en Inventario")
            
            if submit_stock and codigo_stock and nombre_stock:
                try:
                    c.execute("INSERT INTO productos VALUES (?, ?, ?, ?)", (codigo_stock, nombre_stock, precio_stock, cantidad_stock))
                    conn.commit()
                    st.success(f"Producto '{nombre_stock}' registrado con éxito.")
                except sqlite3.IntegrityError:
                    c.execute("UPDATE productos SET stock = stock + ?, precio = ? WHERE codigo = ?", (cantidad_stock, precio_stock, codigo_stock))
                    conn.commit()
                    st.info(f"Inventario actualizado. Se sumaron {cantidad_stock} unidades a '{nombre_stock}'.")

    with col2:
        st.markdown("### 📦 Stock Actual en Tienda")
        df_stock = pd.read_sql_query("SELECT codigo as 'Código', nombre as 'Producto', precio as 'Precio ($)', stock as 'Unidades' FROM productos", conn)
        
        if df_stock.empty:
            st.info("La base de datos de productos está vacía.")
        else:
            df_stock['Precio ($)'] = df_stock['Precio ($)'].apply(formato_peso)
            st.dataframe(df_stock, use_container_width=True, hide_index=True)

# ==========================================
# PESTAÑA 3: HISTORIAL DE VENTAS
# ==========================================
with tab_historial:
    st.subheader("Registro Histórico de Transacciones")
    
    df_ventas = pd.read_sql_query("SELECT id, fecha, total, metodo_pago, detalle FROM ventas ORDER BY id DESC", conn)
    
    if df_ventas.empty:
        st.info("Aún no se han registrado ventas en el sistema.")
    else:
        df_ventas.columns = ["Nº Transacción", "Fecha y Hora Exacta", "Total ($)", "Método de Pago", "Productos Vendidos"]
        df_ventas["Total ($)"] = df_ventas["Total ($)"].apply(formato_peso)
        
        st.dataframe(df_ventas, use_container_width=True, hide_index=True)