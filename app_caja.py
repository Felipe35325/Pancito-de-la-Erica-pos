import streamlit as st
import pandas as pd
from datetime import datetime
import pytz  
from sqlalchemy import text

st.set_page_config(page_title="Pancito de la Erica - POS", layout="wide")

# --- CONEXIÓN A LA NUBE (O LOCAL) ---
conn = st.connection("sqlite", type="sql", url="sqlite:///caja.db")

# --- ZONA HORARIA DE CHILE ---
zona_chile = pytz.timezone('America/Santiago')

# 1. CREACIÓN DE TABLAS BASE
with conn.session as s:
    s.execute(text('''CREATE TABLE IF NOT EXISTS productos (
                        codigo TEXT PRIMARY KEY, 
                        nombre TEXT, 
                        precio REAL, 
                        stock REAL)'''))
    
    s.execute(text('''CREATE TABLE IF NOT EXISTS ventas (
                        id SERIAL PRIMARY KEY, 
                        fecha TEXT, 
                        total REAL, 
                        detalle TEXT, 
                        metodo_pago TEXT)'''))
    
    s.execute(text('''CREATE TABLE IF NOT EXISTS usuarios (
                        username TEXT PRIMARY KEY, 
                        password TEXT, 
                        rol TEXT)'''))
    s.commit()

# 2. MIGRACIONES SEGURAS
with conn.session as s:
    try:
        s.execute(text("ALTER TABLE productos ADD COLUMN tipo_unidad TEXT DEFAULT 'Unidad'"))
        s.commit()
    except:
        s.rollback() 

with conn.session as s:
    try:
        s.execute(text("ALTER TABLE productos ALTER COLUMN stock TYPE REAL USING stock::real"))
        s.commit()
    except:
        s.rollback()

with conn.session as s:
    try:
        s.execute(text("ALTER TABLE ventas ADD COLUMN turno_cerrado BOOLEAN DEFAULT FALSE"))
        s.commit()
    except:
        s.rollback()

# 3. FORZAR USUARIOS OFICIALES
with conn.session as s:
    s.execute(text("DELETE FROM usuarios"))
    s.execute(text("INSERT INTO usuarios (username, password, rol) VALUES ('Jaime', 'jaimeconita321', 'jefe')"))
    s.execute(text("INSERT INTO usuarios (username, password, rol) VALUES ('Caja', 'vendedor2560', 'vendedor')"))
    s.commit()

# --- ESTADO DE LA SESIÓN ---
if 'carrito' not in st.session_state:
    st.session_state.carrito = []
if 'codigo_pendiente' not in st.session_state:
    st.session_state.codigo_pendiente = None
if 'peso_pendiente' not in st.session_state:
    st.session_state.peso_pendiente = None
if 'usuario_actual' not in st.session_state:
    st.session_state.usuario_actual = None
if 'rol_actual' not in st.session_state:
    st.session_state.rol_actual = None
if 'confirmar_cierre' not in st.session_state:
    st.session_state.confirmar_cierre = False

def formato_peso(monto):
    return f"${monto:,.0f}".replace(",", ".")

# ==========================================
# SISTEMA DE LOGIN Y AUTENTICACIÓN
# ==========================================
if st.session_state.rol_actual is None:
    st.title("🥖 Pancito de la Erica - Ingreso al Sistema")
    
    col1, col2, col3 = st.columns([1, 1, 1])
    with col2:
        st.markdown("### Por favor, identifíquese")
        with st.form("form_login"):
            usuario_input = st.text_input("Usuario")
            password_input = st.text_input("Contraseña", type="password")
            btn_ingresar = st.form_submit_button("Ingresar", type="primary", use_container_width=True)
            
            if btn_ingresar:
                df_user = conn.query("SELECT rol FROM usuarios WHERE username = :u AND password = :p", 
                                     params={"u": usuario_input, "p": password_input}, ttl=0)
                if not df_user.empty:
                    st.session_state.usuario_actual = usuario_input
                    st.session_state.rol_actual = df_user.iloc[0]['rol']
                    st.success("Ingreso exitoso. Cargando...")
                    st.rerun()
                else:
                    st.error("❌ Usuario o contraseña incorrectos.")
    st.stop()

# ==========================================
# APLICACIÓN PRINCIPAL
# ==========================================
with st.sidebar:
    st.markdown("### 👤 Sesión Activa")
    st.write(f"**Usuario:** {st.session_state.usuario_actual.capitalize()}")
    st.write(f"**Rol:** {st.session_state.rol_actual.capitalize()}")
    st.markdown("---")
    if st.button("🚪 Cerrar Sesión", use_container_width=True):
        st.session_state.usuario_actual = None
        st.session_state.rol_actual = None
        st.session_state.carrito = [] 
        st.session_state.confirmar_cierre = False
        st.rerun()

st.title("🛒 Sistema de Control de Stock y Ventas - Pancito de la Erica")

# --- CONTROL DE ACCESO ---
if st.session_state.rol_actual == 'jefe':
    tabs = st.tabs(["💳 Nueva Venta", "📦 Control de Stock y Precios", "🧾 Historial de Ventas", "📊 Análisis Semanal"])
    tab_venta = tabs[0]
    tab_stock = tabs[1]
    tab_historial = tabs[2]
    tab_analisis = tabs[3]
else:
    tabs = st.tabs(["💳 Nueva Venta"])
    tab_venta = tabs[0]
    tab_stock = None
    tab_historial = None
    tab_analisis = None

# ==========================================
# PESTAÑA 1: CAJA REGISTRADORA Y CIERRE DIARIO
# ==========================================
with tab_venta:
    st.subheader("Caja Registradora")
    
    # 1. BÚSQUEDA POR CÓDIGO Y MAGIA DE LA BALANZA
    with st.form("form_escaner", clear_on_submit=True):
        codigo_escaneado = st.text_input("Pistolear Código de Barras", key="escaner_input", help="Presiona Enter o deja que la pistola lo haga")
        btn_escanear = st.form_submit_button("Agregar al carrito")
        
        if btn_escanear and codigo_escaneado:
            codigo = codigo_escaneado.strip()
            
            # --- NUEVA INTELIGENCIA: CALCULAR KILOS AUTOMÁTICAMENTE ---
            if len(codigo) == 13 and codigo.startswith("20"):
                # Extraemos el código de 5 dígitos del producto (Ej: "11111")
                codigo_plu = codigo[2:7]
                # Por si la balanza le pone ceros a la izquierda (Ej: "00123" -> "123")
                codigo_plu_limpio = codigo_plu.lstrip("0") 
                if codigo_plu_limpio == "": codigo_plu_limpio = "0"
                
                precio_balanza = int(codigo[7:12])
                
                # Buscamos en el inventario a ver si existe ese pan
                df_producto = conn.query("SELECT codigo, nombre, precio, tipo_unidad FROM productos WHERE codigo = :c OR codigo = :cl", 
                                         params={"c": codigo_plu, "cl": codigo_plu_limpio}, ttl=0)
                
                if not df_producto.empty:
                    bd_codigo = df_producto.iloc[0]['codigo']
                    bd_nombre = df_producto.iloc[0]['nombre']
                    bd_precio_kilo = df_producto.iloc[0]['precio']
                    
                    # Cálculo matemático del peso
                    kilos_calculados = precio_balanza / bd_precio_kilo if bd_precio_kilo > 0 else 0
                    
                    st.session_state.carrito.append({
                        "codigo": bd_codigo, 
                        "nombre": bd_nombre, 
                        "precio": precio_balanza, 
                        "tipo": "Kilos", 
                        "cantidad": kilos_calculados
                    })
                else:
                    # Fallback de seguridad: Si no lo encuentra en BD, pasa el cobro pero sin descontar stock
                    st.session_state.carrito.append({
                        "codigo": codigo, 
                        "nombre": "Pan (Código Balanza no registrado)", 
                        "precio": precio_balanza, 
                        "tipo": "Unidad", 
                        "cantidad": 1
                    })
            # --- FIN DE LA MAGIA DE LA BALANZA ---
            
            else:
                # Lógica para códigos normales (Galletas, Bebidas, etc.)
                df_producto = conn.query("SELECT nombre, precio, tipo_unidad FROM productos WHERE codigo = :c", params={"c": codigo}, ttl=0)
                if not df_producto.empty:
                    nombre_prod = df_producto.iloc[0]['nombre']
                    precio_prod = df_producto.iloc[0]['precio']
                    tipo_u = df_producto.iloc[0]['tipo_unidad']
                    
                    if tipo_u == 'Kilos':
                        st.session_state.peso_pendiente = {
                            "codigo": codigo, "nombre": nombre_prod, "precio_kg": precio_prod
                        }
                    else:
                        st.session_state.carrito.append({
                            "codigo": codigo, "nombre": nombre_prod, 
                            "precio": precio_prod, "tipo": tipo_u, "cantidad": 1
                        })
                else:
                    st.session_state.codigo_pendiente = codigo

    # 2. PANTALLA EMERGENTE PARA PESO MANUAL (Solo si pasas un producto a granel sin balanza)
    if st.session_state.peso_pendiente:
        prod = st.session_state.peso_pendiente
        st.warning(f"⚖️ **{prod['nombre']}** se vende por kilo. (Precio base: {formato_peso(prod['precio_kg'])} / Kg)")
        
        with st.form("form_ingreso_peso"):
            col_p1, col_p2 = st.columns([2, 1])
            with col_p1:
                peso_ingresado = st.number_input("Ingrese el peso exacto en Kilos (Ej: 0.80)", min_value=0.01, step=0.05, value=1.00, format="%.2f")
            with col_p2:
                st.write("")
                st.write("")
                btn_peso = st.form_submit_button("✔️ Añadir al cobro", type="primary", use_container_width=True)
            
            if btn_peso:
                precio_final = prod['precio_kg'] * peso_ingresado
                st.session_state.carrito.append({
                    "codigo": prod['codigo'], 
                    "nombre": prod['nombre'], 
                    "precio": precio_final, 
                    "tipo": "Kilos", 
                    "cantidad": peso_ingresado
                })
                st.session_state.peso_pendiente = None
                st.rerun()
        
        if st.button("❌ Cancelar ingreso de este producto"):
            st.session_state.peso_pendiente = None
            st.rerun()

    # 3. REGISTRO RÁPIDO DE CÓDIGO NUEVO
    if st.session_state.codigo_pendiente and not st.session_state.peso_pendiente:
        st.error(f"⚠️ El código {st.session_state.codigo_pendiente} no está registrado.")
        with st.form("form_rapido_producto"):
            st.write("Regístralo rápido para continuar con esta venta:")
            col_n, col_p, col_b = st.columns([2, 1, 1])
            with col_n:
                nuevo_nombre = st.text_input("Nombre del producto")
            with col_p:
                nuevo_precio = st.number_input("Precio ($)", min_value=0.0, step=100.0)
            with col_b:
                st.write("") 
                st.write("")
                btn_guardar_rapido = st.form_submit_button("Guardar y sumar a la boleta")
            
            if btn_guardar_rapido and nuevo_nombre:
                with conn.session as s:
                    s.execute(text("INSERT INTO productos (codigo, nombre, precio, stock, tipo_unidad) VALUES (:c, :n, :p, :stk, :tu)"), 
                              {"c": st.session_state.codigo_pendiente, "n": nuevo_nombre, "p": nuevo_precio, "stk": 0.0, "tu": "Unidad"})
                    s.commit()
                
                st.session_state.carrito.append({
                    "codigo": st.session_state.codigo_pendiente, "nombre": nuevo_nombre, 
                    "precio": nuevo_precio, "tipo": "Unidad", "cantidad": 1
                })
                st.session_state.codigo_pendiente = None 
                st.rerun()

    st.markdown("---")
    col_tabla, col_boleta = st.columns([1.5, 1.2])
    
    with col_tabla:
        st.markdown("### 🛒 Registro de Escaneo")
        if st.session_state.carrito:
            df_carrito = pd.DataFrame(st.session_state.carrito)
            df_carrito['precio_fmt'] = df_carrito['precio'].apply(formato_peso)
            df_carrito['cant_visual'] = df_carrito.apply(lambda r: f"{r['cantidad']:.2f} Kg" if r['tipo'] == 'Kilos' else f"{int(r['cantidad'])} un", axis=1)
            
            df_vista = df_carrito[['codigo', 'nombre', 'cant_visual', 'precio_fmt']]
            df_vista.columns = ['Código', 'Producto', 'Cant.', 'Precio']
            st.dataframe(df_vista, use_container_width=True, hide_index=True)
            
            st.markdown("**Corregir error de escaneo:**")
            col_del1, col_del2 = st.columns([2, 1])
            with col_del1:
                nombres_en_carrito = list(set([item['nombre'] for item in st.session_state.carrito]))
                item_a_borrar = st.selectbox("Producto a descontar", ["Seleccionar..."] + nombres_en_carrito, label_visibility="collapsed")
            with col_del2:
                if st.button("➖ Eliminar último escaneo", use_container_width=True):
                    if item_a_borrar != "Seleccionar...":
                        for i in range(len(st.session_state.carrito)-1, -1, -1):
                            if st.session_state.carrito[i]['nombre'] == item_a_borrar:
                                st.session_state.carrito.pop(i)
                                st.rerun()
                                break
            
            if st.button("🗑️ Vaciar Carrito Completo", type="secondary", use_container_width=True):
                st.session_state.carrito = []
                st.rerun()
        else:
            st.info("Aún no has pistoleado ningún producto. Pasa un código de barras para agregarlo aquí.")

    with col_boleta:
        st.markdown("### 🧾 Resumen de Cobro")
        
        resumen_venta = {}
        total = 0
        for item in st.session_state.carrito:
            llave = item['codigo']
            if llave in resumen_venta:
                resumen_venta[llave]['cantidad'] += item['cantidad']
                resumen_venta[llave]['subtotal'] += item['precio']
            else:
                resumen_venta[llave] = {
                    'nombre': item['nombre'],
                    'cantidad': item['cantidad'],
                    'subtotal': item['precio'],
                    'tipo': item['tipo']
                }
            total += item['precio']

        html_ticket = "<div style='background-color: #1a1c23; padding: 25px; border-radius: 12px; border: 1px solid #333; box-shadow: 0px 8px 20px rgba(0,0,0,0.4); min-height: 250px;'>"
        html_ticket += "<h3 style='text-align: center; color: #f4f4f4; margin: 0; letter-spacing: 1px;'>PANCITO DE LA ERICA</h3>"
        html_ticket += "<p style='text-align: center; color: #888; font-size: 14px; margin-top: 5px; margin-bottom: 15px;'>Boleta de Venta</p>"
        html_ticket += "<hr style='border-top: 2px dashed #444; margin-bottom: 20px;'>"
        
        if st.session_state.carrito:
            for key, prod in resumen_venta.items():
                nombre = prod['nombre']
                cant = prod['cantidad']
                tipo = prod['tipo']
                subtotal = formato_peso(prod['subtotal'])
                
                if tipo == 'Kilos':
                    txt_cant = f"{cant:.2f} Kg"
                else:
                    txt_cant = f"x{int(cant)}"
                    
                html_ticket += f"<div style='display: flex; justify-content: space-between; color: #ddd; margin-bottom: 10px; font-size: 16px;'><span>{nombre} <b style='color:#3498db;'>{txt_cant}</b></span><span style='font-weight: bold;'>{subtotal}</span></div>"
        else:
            html_ticket += "<div style='text-align: center; color: #666; font-style: italic; margin-top: 30px; margin-bottom: 30px;'>Pistolee un producto para empezar...</div>"
            
        html_ticket += "<hr style='border-top: 2px dashed #444; margin-top: 20px; margin-bottom: 15px;'>"
        html_ticket += f"<div style='display: flex; justify-content: space-between; align-items: center;'><h3 style='color: #f4f4f4; margin: 0; font-size: 20px;'>TOTAL A COBRAR:</h3><h1 style='color: #2ecc71; margin: 0; font-size: 32px;'>{formato_peso(total)}</h1></div>"
        html_ticket += "</div>"

        st.markdown(html_ticket, unsafe_allow_html=True)
        st.markdown("<br>", unsafe_allow_html=True)
        
        if not st.session_state.carrito:
            st.warning("⚠️ El carrito está vacío. Pistolea un producto para habilitar el cobro.")
        else:
            st.markdown("#### Seleccione Método de Pago:")
            metodo_pago = st.radio(
                "Método de Pago", 
                ["💵 Efectivo", "💳 Débito", "💳 Crédito"], 
                horizontal=True, 
                label_visibility="collapsed"
            )
            
            pago_listo = True
            metodo_bd = ""
            
            if metodo_pago == "💵 Efectivo":
                st.markdown("<div style='background-color: #2b302c; border-left: 5px solid #2ecc71; padding: 15px; border-radius: 5px; margin-top: 10px;'><p style='margin:0; color:#fff; font-weight:bold;'>Calculadora de Vuelto Rápida</p></div>", unsafe_allow_html=True)
                
                monto_cliente = st.number_input("¿Con cuánto billete paga el cliente?", min_value=0, step=1000, value=int(total))
                vuelto = monto_cliente - total
                
                if monto_cliente < total:
                    st.error(f"❌ Faltan {formato_peso(total - monto_cliente)} para completar el pago.")
                    pago_listo = False 
                elif monto_cliente > total:
                    st.success(f"🟢 VUELTO A ENTREGAR AL CLIENTE: **{formato_peso(vuelto)}**")
                else:
                    st.info("Paga con el monto exacto. No hay vuelto que entregar.")
                
                metodo_bd = f"Efectivo (Pagó: {formato_peso(monto_cliente)} | Vuelto: {formato_peso(vuelto)})"
            else:
                metodo_bd = metodo_pago.replace("💳 ", "")
            
            st.markdown("<br>", unsafe_allow_html=True)
            
            if st.button("✅ Procesar Pago y Finalizar Venta", type="primary", use_container_width=True, disabled=not pago_listo):
                fecha_actual_chile = datetime.now(zona_chile).strftime("%Y-%m-%d %H:%M:%S")
                
                detalle_venta_lista = []
                for prod in resumen_venta.values():
                    if prod['tipo'] == 'Kilos':
                        detalle_venta_lista.append(f"{prod['nombre']} ({prod['cantidad']:.2f} Kg)")
                    else:
                        detalle_venta_lista.append(f"{prod['nombre']} (x{int(prod['cantidad'])})")
                detalle_venta_texto = ", ".join(detalle_venta_lista)
                
                with conn.session as s:
                    s.execute(text("INSERT INTO ventas (fecha, total, detalle, metodo_pago, turno_cerrado) VALUES (:f, :t, :d, :m, FALSE)"), 
                              {"f": fecha_actual_chile, "t": total, "d": detalle_venta_texto, "m": metodo_bd})
                    
                    for item in st.session_state.carrito:
                        if item['tipo'] in ['Unidad', 'Kilos']:
                            s.execute(text("UPDATE productos SET stock = stock - :cant WHERE codigo = :c"), {"cant": item['cantidad'], "c": item['codigo']})
                    s.commit()
                
                st.session_state.carrito = [] 
                st.success(f"¡Venta procesada a las {fecha_actual_chile}! Pago: {metodo_bd}.")
                st.rerun()

    # --- CIERRE DE CAJA Y RESETEO DE CONTADORES ---
    st.markdown("---")
    with st.expander("🔒 CIERRE DE CAJA DIARIO (Terminar Turno)", expanded=st.session_state.confirmar_cierre):
        fecha_hoy = datetime.now(zona_chile).strftime("%Y-%m-%d")
        
        df_hoy = conn.query(f"SELECT total, metodo_pago FROM ventas WHERE fecha LIKE '{fecha_hoy}%' AND turno_cerrado = FALSE", ttl=0)
        
        if df_hoy.empty:
            st.info("💰 La caja actual está en $0 (No hay ventas activas o el turno ya fue cerrado).")
        else:
            st.write(f"**Cuadratura de ventas activas para hoy: {fecha_hoy}**")
            
            df_hoy['Metodo_Limpio'] = df_hoy['metodo_pago'].apply(lambda x: 'Efectivo' if 'Efectivo' in x else x)
            totales = df_hoy.groupby('Metodo_Limpio')['total'].sum().to_dict()
            
            efectivo_total = totales.get('Efectivo', 0)
            debito_total = totales.get('Débito', 0)
            credito_total = totales.get('Crédito', 0)
            total_general = efectivo_total + debito_total + credito_total
            
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("💵 Total Efectivo (En Gaveta)", formato_peso(efectivo_total))
            c2.metric("💳 Total Débito (Transbank)", formato_peso(debito_total))
            c3.metric("💳 Total Crédito (Transbank)", formato_peso(credito_total))
            c4.metric("💰 RECAUDACIÓN TOTAL", formato_peso(total_general))
            
            if not st.session_state.confirmar_cierre:
                if st.button("✅ Confirmar Cuadratura y Terminar Día", type="primary"):
                    st.session_state.confirmar_cierre = True
                    st.rerun()
            else:
                st.warning("⚠️ **¿Estás seguro/a de cerrar la caja de hoy?**\n\nAl confirmar, los contadores de arriba se reiniciarán a $0 para el siguiente turno. Las ventas de hoy quedarán guardadas a salvo en tu Historial y Análisis Semanal.")
                col_si, col_no = st.columns(2)
                
                with col_si:
                    if st.button("✔️ SÍ, CERRAR CAJA Y REINICIAR CONTADOR", type="primary", use_container_width=True):
                        with conn.session as s:
                            s.execute(text(f"UPDATE ventas SET turno_cerrado = TRUE WHERE fecha LIKE '{fecha_hoy}%' AND turno_cerrado = FALSE"))
                            s.commit()
                        st.session_state.confirmar_cierre = False
                        st.rerun()
                
                with col_no:
                    if st.button("❌ NO, CANCELAR", use_container_width=True):
                        st.session_state.confirmar_cierre = False
                        st.rerun()

# ==========================================
# PESTAÑA 2: CONTROL DE STOCK Y PRECIOS (SOLO JEFE)
# ==========================================
if st.session_state.rol_actual == 'jefe' and tab_stock is not None:
    with tab_stock:
        st.subheader("Gestión de Inventario y Precios")
        col_ingreso, col_editar = st.columns(2)
        with col_ingreso:
            st.markdown("### ➕ Ingreso de Mercadería")
            tipo_unidad = st.radio("Se vende por:", ["Unidad", "Kilos"], horizontal=True)
            with st.form("form_nuevo_producto_stock", clear_on_submit=True):
                codigo_stock = st.text_input("Código de barras / SKU")
                nombre_stock = st.text_input("Nombre del producto")
                precio_stock = st.number_input("Precio de venta ($)", min_value=0.0, step=100.0)
                if tipo_unidad == "Unidad":
                    cantidad_stock = st.number_input("Cantidad a ingresar (Enteros)", min_value=1, step=1, value=1)
                else:
                    cantidad_stock = st.number_input("Cantidad a ingresar (Decimales)", min_value=0.01, step=0.10, value=1.00, format="%.2f")
                submit_stock = st.form_submit_button("Registrar en Inventario")
                
                if submit_stock and codigo_stock and nombre_stock:
                    df_check = conn.query("SELECT codigo FROM productos WHERE codigo = :c", params={"c": codigo_stock}, ttl=0)
                    with conn.session as s:
                        if not df_check.empty:
                            s.execute(text("UPDATE productos SET stock = stock + :cant, precio = :p, tipo_unidad = :tu WHERE codigo = :c"), 
                                      {"cant": cantidad_stock, "p": precio_stock, "tu": tipo_unidad, "c": codigo_stock})
                            st.info(f"Inventario actualizado. Se sumaron {cantidad_stock} a '{nombre_stock}'.")
                        else:
                            s.execute(text("INSERT INTO productos (codigo, nombre, precio, stock, tipo_unidad) VALUES (:c, :n, :p, :stk, :tu)"), 
                                      {"c": codigo_stock, "n": nombre_stock, "p": precio_stock, "stk": cantidad_stock, "tu": tipo_unidad})
                            st.success(f"Producto '{nombre_stock}' registrado con éxito.")
                        s.commit()
        
        with col_editar:
            st.markdown("### ✏️ Edición y Limpieza de Productos")
            st.info("Cambia precios, ajusta el stock o elimina productos que ya no venderás.")
            df_lista_prod = conn.query("SELECT codigo, nombre, precio, stock, tipo_unidad FROM productos ORDER BY nombre ASC", ttl=0)
            if not df_lista_prod.empty:
                opciones = df_lista_prod.apply(lambda row: f"{row['nombre']} - (Cód: {row['codigo']})", axis=1).tolist()
                seleccion = st.selectbox("Seleccione el producto a editar/eliminar:", opciones)
                codigo_seleccionado = seleccion.split("(Cód: ")[1].replace(")", "")
                datos_producto = df_lista_prod[df_lista_prod['codigo'] == codigo_seleccionado].iloc[0]
                
                with st.form("form_editar_precio"):
                    nuevo_precio = st.number_input("Nuevo Precio ($)", value=float(datos_producto['precio']), step=100.0)
                    if datos_producto['tipo_unidad'] == "Unidad":
                        nuevo_stock = st.number_input("Stock Ajustado (Enteros)", value=int(datos_producto['stock']), step=1)
                    else:
                        nuevo_stock = st.number_input("Stock Ajustado (Decimales)", value=float(datos_producto['stock']), step=0.10, format="%.2f")
                    
                    st.markdown("---")
                    st.write("**Opciones si el stock llega a 0 (o menos):**")
                    accion_cero = st.radio(
                        "¿Qué deseas hacer con este producto al guardar?",
                        ["Conservarlo en el sistema con stock 0", "Eliminarlo definitivamente de la base de datos"],
                        help="Esta opción solo se activará si el 'Stock Ajustado' es 0 o negativo."
                    )
                    btn_actualizar = st.form_submit_button("Guardar Cambios", type="primary")
                    
                    if btn_actualizar:
                        with conn.session as s:
                            if nuevo_stock <= 0 and "Eliminarlo" in accion_cero:
                                s.execute(text("DELETE FROM productos WHERE codigo = :c"), {"c": codigo_seleccionado})
                                msg = f"🗑️ El producto '{datos_producto['nombre']}' fue eliminado del sistema."
                            else:
                                s.execute(text("UPDATE productos SET precio = :p, stock = :stk WHERE codigo = :c"), 
                                          {"p": nuevo_precio, "stk": nuevo_stock, "c": codigo_seleccionado})
                                msg = f"✅ ¡Valores de '{datos_producto['nombre']}' actualizados!"
                            s.commit()
                        st.success(msg)
                        st.rerun()

                with st.expander("🚨 Eliminar producto directamente"):
                    st.warning(f"Si ya no traerás más **{datos_producto['nombre']}**, puedes borrarlo de inmediato aquí.")
                    if st.button(f"🗑️ Eliminar '{datos_producto['nombre']}' ahora", use_container_width=True):
                        with conn.session as s:
                            s.execute(text("DELETE FROM productos WHERE codigo = :c"), {"c": codigo_seleccionado})
                            s.commit()
                        st.success("Producto eliminado exitosamente.")
                        st.rerun()
            else:
                st.warning("No hay productos en la base de datos para editar.")

        st.markdown("---")
        st.markdown("### 📦 Stock Actual en Tienda")
        df_stock = conn.query('SELECT codigo as "Código", nombre as "Producto", tipo_unidad as "Tipo", precio as "Precio ($)", stock as "Unidades/Kg" FROM productos ORDER BY nombre ASC', ttl=0)
        if df_stock.empty:
            st.info("La base de datos de productos está vacía.")
        else:
            df_stock['Precio ($)'] = df_stock['Precio ($)'].apply(formato_peso)
            df_stock['Unidades/Kg'] = df_stock.apply(lambda r: f"{int(r['Unidades/Kg'])}" if r['Tipo'] == "Unidad" else f"{r['Unidades/Kg']:.2f}", axis=1)
            st.dataframe(df_stock, use_container_width=True, hide_index=True)

# ==========================================
# PESTAÑA 3: HISTORIAL DE VENTAS (SOLO JEFE)
# ==========================================
if st.session_state.rol_actual == 'jefe' and tab_historial is not None:
    with tab_historial:
        st.subheader("Registro Histórico de Transacciones")
        df_ventas = conn.query('SELECT id, fecha, total, metodo_pago, detalle FROM ventas ORDER BY id ASC', ttl=0)
        
        if df_ventas.empty:
            st.info("Aún no se han registrado ventas en el sistema.")
        else:
            df_ventas['fecha_dt'] = pd.to_datetime(df_ventas['fecha'])
            df_ventas['Solo_Fecha'] = df_ventas['fecha_dt'].dt.date
            df_ventas['Nº Venta del Día'] = df_ventas.groupby('Solo_Fecha').cumcount() + 1
            
            df_ventas = df_ventas.sort_values(by='fecha_dt', ascending=False).reset_index(drop=True)
            df_ventas["Total ($)"] = df_ventas["total"].apply(formato_peso)
            
            df_vista = df_ventas[['Nº Venta del Día', 'fecha', 'Total ($)', 'metodo_pago', 'detalle']]
            df_vista.columns = ['Nº Venta del Día', 'Fecha y Hora Exacta', 'Total ($)', 'Método de Pago', 'Productos Vendidos']
            
            st.dataframe(df_vista, use_container_width=True, hide_index=True)

# ==========================================
# PESTAÑA 4: ANÁLISIS SEMANAL (SOLO JEFE)
# ==========================================
if st.session_state.rol_actual == 'jefe' and tab_analisis is not None:
    with tab_analisis:
        st.subheader("📊 Análisis de Ventas por Día de la Semana")
        
        df_todas = conn.query('SELECT fecha, total FROM ventas', ttl=0)
        if df_todas.empty:
            st.info("Aún no hay datos suficientes para analizar el rendimiento.")
        else:
            df_todas['fecha_dt'] = pd.to_datetime(df_todas['fecha'])
            dias_espanol = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
            df_todas['Dia_Semana_Num'] = df_todas['fecha_dt'].dt.dayofweek
            df_todas['Día'] = df_todas['Dia_Semana_Num'].map(dias_espanol)
            
            dia_seleccionado = st.selectbox("Seleccione un día para analizar:", list(dias_espanol.values()))
            
            df_filtrado = df_todas[df_todas['Día'] == dia_seleccionado]
            
            cantidad_ventas = len(df_filtrado)
            ingreso_total = df_filtrado['total'].sum()
            
            col1, col2 = st.columns(2)
            col1.metric(f"Total de Boletas (Todos los {dia_seleccionado}s)", f"{cantidad_ventas} boletas")
            col2.metric(f"Dinero Histórico Recaudado ({dia_seleccionado}s)", formato_peso(ingreso_total))
            
            st.markdown("---")
            st.markdown(f"**Desglose histórico de todos los {dia_seleccionado}s registrados:**")
            if not df_filtrado.empty:
                df_mostrar = df_filtrado[['fecha', 'total']].copy()
                df_mostrar['total'] = df_mostrar['total'].apply(formato_peso)
                df_mostrar.columns = ['Fecha de Venta', 'Monto de la Boleta']
                df_mostrar = df_mostrar.sort_values(by='Fecha de Venta', ascending=False)
                st.dataframe(df_mostrar, use_container_width=True, hide_index=True)
            else:
                st.warning(f"Todavía no se ha registrado ninguna venta un día {dia_seleccionado}.")