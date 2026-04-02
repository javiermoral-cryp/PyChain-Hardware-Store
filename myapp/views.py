import json
import stripe

from django.http import JsonResponse
from .models import CryptoPayment

from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.db.models.functions import Coalesce
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth import login, logout, authenticate
from django.urls import reverse
from django.views.decorators.csrf import ensure_csrf_cookie, csrf_protect
from django.views.decorators.http import require_POST, require_GET

from .models import Perfil, Producto, Venta, Proveedor, CompraProveedor, Pedido, DetallePedido, Categoria, \
    SolicitudReposicion
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from .forms import RegistroClienteForm, RegistroAdminForm
from django.db.models import Sum, F, FloatField, Value, DecimalField
from datetime import timedelta
from django.utils import timezone


# ---------- Auth & Registro ----------
def registro_cliente(request):
    if request.method == 'POST':
        form = RegistroClienteForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login_cliente')
    else:
        form = RegistroClienteForm()
    return render(request, 'registro_cliente.html', {'form': form})

def registro_admin(request):
    if request.method == 'POST':
        form = RegistroAdminForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('login_admin')
    else:
        form = RegistroAdminForm()
    return render(request, 'registro_admin.html', {'form': form})

def login_cliente(request):
    error = None
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            error = "Este usuario no existe"
            return render(request, 'login_cliente.html', {'error': error})

        # Validar que NO sea admin
        try:
            perfil = Perfil.objects.get(user=user)
            if perfil.administrador_negocio:
                error = "Este usuario no es un cliente."
                return render(request, 'login_cliente.html', {'error': error})
        except Perfil.DoesNotExist:
            error = "Este usuario no es un cliente."
            return render(request, 'login_cliente.html', {'error': error})

        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('vista_cliente')
        else:
            error = "Usuario o contraseña incorrecta"
    return render(request, 'login_cliente.html', {"error": error})

def login_admin_negocio(request):
    error = None
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']

        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            error = "Este usuario no existe"
            return render(request, 'login_admin.html', {'error': error})

        # Validar que sí sea admin
        try:
            perfil = Perfil.objects.get(user=user)
            if not perfil.administrador_negocio:
                error = "Este usuario no es administrador."
                return render(request, 'login_admin.html', {'error': error})
        except Perfil.DoesNotExist:
            error = "Este usuario no es administrador."
            return render(request, 'login_admin.html', {'error': error})

        user = authenticate(username=username, password=password)
        if user is not None:
            login(request, user)
            # Mejor redirigir a la vista que prepara el contexto
            return redirect('panel_admin_negocio')
        else:
            error = "Usuario o contraseña incorrecta"
    return render(request, 'login_admin.html', {"error": error})

def solo_admin_negocio(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login_admin')
        if not hasattr(request.user, 'perfil') or not request.user.perfil.administrador_negocio:
            return render(request, 'error.html', {'mensaje': 'No tienes permiso para acceder a esta página.'})
        return view_func(request, *args, **kwargs)
    return wrapper

def cerrar_sesion(request):
    logout(request)
    return redirect('inicio')

def inicio(request):
    return redirect('vista_cliente')

def inicio_cuenta(request):
    # para el botón "Mi cuenta"
    return render(request, 'inicio.html')


# ---------- Tienda ----------
def vista_cliente(request):
    productos = Producto.objects.all().select_related('proveedor', 'categoria')
    proveedores = Proveedor.objects.all()
    categorias = Categoria.objects.all()

    # Parámetros
    q = request.GET.get("q")
    categoria = request.GET.get("categoria", "")
    precio_max = request.GET.get("precio_max")
    orden = request.GET.get("orden")
    proveedor = request.GET.get("proveedor", "")
    orden_seleccionado = orden or ""

    # Búsqueda por nombre
    if q:
        productos = productos.filter(nombre__icontains=q)

    # Filtro por categoría (FK -> usa categoria_id)
    if categoria:
        productos = productos.filter(categoria_id=categoria)

    # Filtro por proveedor (usa nombre_empresa)
    if proveedor:
        productos = productos.filter(proveedor__nombre_empresa=proveedor)

    # Precio máximo
    if precio_max:
        try:
            precio_float = float(precio_max)
            productos = productos.filter(precio__lte=precio_float)
        except ValueError:
            pass

    # Ordenamientos
    if orden == "recientes":
        productos = productos.order_by("-id")
    elif orden == "antiguos":
        productos = productos.order_by("id")
    elif orden == "mas_vendidos":
        productos = productos.annotate(total_vendido=Sum("venta__cantidad")).order_by("-total_vendido")
    elif orden == "ofertas":
        productos = productos.filter(oferta=True)

    # Marcar categoría seleccionada para el select
    for cat in categorias:
        cat.seleccionada = (str(cat.id) == categoria)

    context = {
        "productos": productos,
        "proveedores": proveedores,
        "categorias": categorias,
        "categoria_seleccionada": categoria,
        "orden_recientes": orden_seleccionado == "recientes",
        "orden_antiguos": orden_seleccionado == "antiguos",
        "orden_mas_vendidos": orden_seleccionado == "mas_vendidos",
        "orden_ofertas": orden_seleccionado == "ofertas",
    }
    return render(request, 'tienda.html', context)


@solo_admin_negocio
@ensure_csrf_cookie
def panel_admin_negocio(request):
    productos = Producto.objects.all()
    productos_bajo_stock = [p for p in productos if p.necesita_reponer]

    #historial
    compras = (CompraProveedor.objects
               .select_related('proveedor', 'producto')
               .order_by('-fecha'))  # últimas primero

    ventas = (Venta.objects
              .select_related('producto', 'cliente')
              .order_by('-fecha'))

    return render(request, 'panel_admin.html', {
        'productos': productos,
        'productos_bajo_stock': productos_bajo_stock,
        'compras': compras,
        'ventas': ventas,
    })


# ---------- API datos para gráfico ----------

def datos_ventas_cliente(request):
    # Rango: '1m' (30 días), '3m' (90 días), '1y' (365 días)
    r = request.GET.get('range', '3m')
    days_map = {'1m': 30, '3m': 90, '1y': 365}
    days = days_map.get(r, 90)

    hasta = timezone.now()
    desde = hasta - timedelta(days=days)

    top_ventas = (
        Venta.objects
        .filter(fecha__gte=desde)
        .values('producto__nombre')
        .annotate(total_vendido=Sum('cantidad'))
        .order_by('-total_vendido')[:5]
    )

    data = {
        'labels': [v['producto__nombre'] for v in top_ventas],
        'data': [v['total_vendido'] for v in top_ventas],
        'desde': desde.strftime('%d/%m/%Y'),
        'hasta': timezone.now().strftime('%d/%m/%Y'),
        'range': r,
    }
    return JsonResponse(data)


# ---------- Producto / Carrito / Compra ----------

def detalle_producto(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    return render(request, 'detalle_producto.html', {'producto': producto})


def añadir_carrito(request, producto_id):
    producto = get_object_or_404(Producto, id=producto_id)
    cantidad = int(request.POST.get('cantidad', 1))

    carrito = request.session.get('carrito', {})

    if str(producto_id) in carrito:
        carrito[str(producto_id)]["cantidad"] += cantidad
    else:
        carrito[str(producto_id)] = {
            "producto_id": producto.id,
            "nombre": producto.nombre,
            "precio": D(producto.precio),
            "cantidad": cantidad
        }

    request.session['carrito'] = carrito
    request.session.modified = True
    return redirect(f"{reverse('detalle_producto', args=[producto.id])}?added=1")


def ver_carrito(request):
    carrito = request.session.get('carrito', {})

    productos = []
    total = 0
    for item in carrito.values():
        subtotal = item["precio"] * item["cantidad"]
        total += subtotal
        productos.append({
            "producto_id": item["producto_id"],
            "nombre": item["nombre"],
            "precio": item["precio"],
            "cantidad": item["cantidad"],
            "subtotal": subtotal
        })

    context = {"carrito": productos, "total": total}
    return render(request, "carrito.html", context)


def aumentar_cantidad(request, producto_id):
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        carrito[str(producto_id)]["cantidad"] += 1
    request.session['carrito'] = carrito
    request.session.modified = True
    return redirect('ver_carrito')


def disminuir_cantidad(request, producto_id):
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        if carrito[str(producto_id)]["cantidad"] > 1:
            carrito[str(producto_id)]["cantidad"] -= 1
        else:
            del carrito[str(producto_id)]
    request.session['carrito'] = carrito
    request.session.modified = True
    return redirect('ver_carrito')


def eliminar_del_carrito(request, producto_id):
    carrito = request.session.get('carrito', {})
    if str(producto_id) in carrito:
        del carrito[str(producto_id)]
        request.session['carrito'] = carrito
    return redirect('ver_carrito')

@login_required
def realizar_compra(request):
    carrito = request.session.get("carrito", {})
    if not carrito:
        messages.error(request, "Tu carrito está vacío.")
        return redirect("ver_carrito")

    # IDs de productos en el carrito
    ids = [item["producto_id"] for item in carrito.values()]

    try:
        with transaction.atomic():
            # 1) Bloquear filas de productos para esta transacción
            productos_bloqueados = (Producto.objects
                                    .select_for_update()
                                    .filter(id__in=ids))
            productos_map = {p.id: p for p in productos_bloqueados}

            # 2) Revalidar stock con valores bloqueados
            faltantes = []
            for item in carrito.values():
                pid = item["producto_id"]
                qty = int(item["cantidad"])
                producto = productos_map.get(pid)
                if producto is None:
                    faltantes.append(f"Producto #{pid} no encontrado")
                    continue
                if qty > producto.cantidad:
                    faltantes.append(f"{producto.nombre} (disponibles: {producto.cantidad})")

            if faltantes:
                # Cualquier insuficiencia aborta la transacción
                messages.error(request, "Stock insuficiente para: " + ", ".join(faltantes))
                # Levantar excepción o devolver antes de crear pedido
                raise ValueError("Stock insuficiente")

            # 3) Calcular total con precios del carrito (o usa producto.precio si prefieres)
            total = sum(D(item["precio"]) * int(item["cantidad"]) for item in carrito.values())

            # 4) Crear pedido
            pedido = Pedido.objects.create(cliente=request.user, total=total)

            # 5) Crear detalles, ventas y restar stock de forma atómica
            for item in carrito.values():
                pid = item["producto_id"]
                qty = int(item["cantidad"])
                pu = D(item["precio"])
                producto = productos_map[pid]

                # Detalle de pedido
                DetallePedido.objects.create(
                    pedido=pedido,
                    producto=producto,
                    cantidad=qty,
                    precio_unitario=pu,
                    subtotal=pu * qty
                )

                # Registrar la venta (para tu gráfica)
                Venta.objects.create(
                    cliente=request.user,
                    producto=producto,
                    cantidad=qty,
                    precio_unitario=pu
                )

                # Restar stock de manera segura con F()
                Producto.objects.filter(id=producto.id).update(cantidad=F('cantidad') - qty)

            # 6) Vaciar carrito
            request.session["carrito"] = {}
            request.session.modified = True

    except ValueError:
        # Ya mostramos messages.error arriba
        return redirect("ver_carrito")
    except Exception as e:
        # Cualquier otro fallo revierte la compra
        messages.error(request, "No se pudo completar la compra. Inténtalo de nuevo.")
        return redirect("ver_carrito")

    messages.success(request, f"✅ ¡Compra realizada! Tu pedido #{pedido.id} ha sido registrado.")
    return redirect("vista_cliente")

@solo_admin_negocio
@require_POST
def enviar_mensaje_proveedor(request):
    try:
        proveedor_id = int(request.POST.get('proveedor_id', '0'))
        producto_id = int(request.POST.get('producto_id', '0'))
        cantidad = int(request.POST.get('cantidad', '0'))
        mensaje = (request.POST.get('mensaje') or '').strip()

        if not proveedor_id or not producto_id or cantidad <= 0 or not mensaje:
            return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

        proveedor = get_object_or_404(Proveedor, id=proveedor_id)
        producto = get_object_or_404(Producto, id=producto_id)

        # Crear registro en BD como 'pendiente'
        solicitud = SolicitudReposicion.objects.create(
            proveedor=proveedor,
            producto=producto,
            cantidad_solicitada=cantidad,
            mensaje=mensaje,
            estado='pendiente'
        )

        # Enviar email
        asunto = f"Solicitud de reposición - {producto.nombre}"
        cuerpo = (
            f"Proveedor: {proveedor.nombre_empresa}\n"
            f"Producto: {producto.nombre}\n"
            f"Cantidad solicitada: {cantidad}\n\n"
            f"Mensaje:\n{mensaje}\n\n"
            f"Enviado por: {request.user.get_username()}"
        )
        destinatarios = [proveedor.email] if proveedor.email else []

        if not destinatarios:
            solicitud.estado = 'error'
            solicitud.save(update_fields=['estado'])
            return JsonResponse({'ok': False, 'error': 'El proveedor no tiene email configurado.'}, status=400)

        send_mail(
            subject=asunto,
            message=cuerpo,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', None),
            recipient_list=destinatarios,
            fail_silently=False,
        )

        # Marcar como enviada
        solicitud.estado = 'enviada'
        solicitud.fecha_envio = timezone.now()
        solicitud.save(update_fields=['estado', 'fecha_envio'])

        return JsonResponse({'ok': True, 'message': 'Solicitud enviada correctamente.'})

    except Exception as e:
        # Registrar fallo
        try:
            solicitud.estado = 'error'  # si existe
            solicitud.save(update_fields=['estado'])
        except Exception:
            pass
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@solo_admin_negocio
@require_POST
def admin_actualizar_producto(request):
    try:
        producto_id = int(request.POST.get('producto_id', '0'))
        accion = request.POST.get('accion')  # 'entrada' o 'salida'
        cantidad = int(request.POST.get('cantidad', '0'))
        precio_unitario_proveedor = request.POST.get('precio_unitario_proveedor')  # puede venir vacío
        proveedor_id = request.POST.get('proveedor_id')  # opcional, si quieres forzar proveedor concreto
        nuevo_precio = request.POST.get('nuevo_precio')  # puede venir vacío
        oferta = request.POST.get('oferta') == 'true'

        if producto_id <= 0 or accion not in ('entrada', 'salida') or cantidad <= 0:
            return JsonResponse({'ok': False, 'error': 'Datos inválidos.'}, status=400)

        with transaction.atomic():
            producto = get_object_or_404(Producto.objects.select_for_update(), id=producto_id)

            # Cambios de precio/oferta (opcionales)
            cambios = []
            if nuevo_precio:
                try:
                    precio_decimal = D(nuevo_precio)  # usa tu helper D(x)
                    if precio_decimal > 0:
                        producto.precio = precio_decimal
                        cambios.append('precio')
                except (ValueError, InvalidOperation):
                    return JsonResponse({'ok': False, 'error': 'Precio nuevo inválido.'}, status=400)
            producto.oferta = oferta
            if 'precio' in cambios or oferta != producto.oferta:
                producto.save()

            # Movimiento de stock
            if accion == 'salida':
                # Restar stock de forma segura
                if producto.cantidad < cantidad:
                    return JsonResponse({'ok': False, 'error': f'Stock insuficiente. Disponibles: {producto.cantidad}.'}, status=400)
                Producto.objects.filter(id=producto.id).update(cantidad=F('cantidad') - cantidad)

            else:  # 'entrada' -> sumar stock y registrar compra proveedor
                # Sumar stock
                Producto.objects.filter(id=producto.id).update(cantidad=F('cantidad') + cantidad)

                # Registrar compra si tenemos precio proveedor
                if precio_unitario_proveedor:
                    try:
                        p_u = D(precio_unitario_proveedor)
                        if p_u <= 0:
                            return JsonResponse({'ok': False, 'error': 'Precio proveedor inválido.'}, status=400)
                    except ValueError:
                        return JsonResponse({'ok': False, 'error': 'Precio proveedor inválido.'}, status=400)

                    # proveedor: usamos el del producto
                    prov = producto.proveedor
                    # Si quieres permitir elegir otro, valida proveedor_id aquí

                    CompraProveedor.objects.create(
                        proveedor=prov,
                        producto=producto,
                        cantidad=cantidad,
                        precio_unitario=p_u
                    )
                # Si no hay precio proveedor, no registramos compra (pero se suma stock)

        return JsonResponse({'ok': True})

    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


# helpers Decimal
ONE = Decimal('1')
ZERO = Decimal('0')
HUNDRED = Decimal('100')

def D(x):
    """Convierte a Decimal de forma segura."""
    if x is None:
        return ZERO
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))

def pct(x):
    """Devuelve porcentaje como factor (p.e. 21 -> 0.21) en Decimal."""
    return D(x) / HUNDRED

def to2f(x):
    """Redondea Decimal a 2 decimales y devuelve float para JSON."""
    return float(D(x).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


@solo_admin_negocio
@require_GET
def admin_analytics_data(request):
    """
    Datos para gráfica tipo bolsa (línea de beneficio):
      GET:
        range: '1m'|'6m'|'all'   (por defecto 'all')
        group: 'producto'|'proveedor' (por defecto 'producto')
        mode:  'top5'|'bottom5'|'recent5' (por defecto 'top5')
    """
    r = request.GET.get('range', 'all')
    group = request.GET.get('group', 'producto')
    mode = request.GET.get('mode', 'top5')

    hasta = timezone.now()
    if mode == 'recent5':
        # Siempre últimos 3 meses
        desde = hasta - timedelta(days=90)
    else:
        if r == '1m':
            desde = hasta - timedelta(days=30)
        elif r == '6m':
            desde = hasta - timedelta(days=180)
        else:
            desde = None  # all

    # Base QS
    ventas_qs = Venta.objects.all()
    compras_qs = (CompraProveedor.objects
                  .select_related('proveedor', 'producto', 'producto__proveedor'))

    # Filtro por rango si aplica
    if desde:
        ventas_qs = ventas_qs.filter(fecha__gte=desde, fecha__lte=hasta)
        compras_qs = compras_qs.filter(fecha__gte=desde, fecha__lte=hasta)

    # Construcción de mapa nombre -> (ventas, coste) en Decimal
    rows_map = {}  # nombre -> {'ventas': Decimal, 'coste': Decimal}
    def add_row(nombre, vent_inc=ZERO, cost_inc=ZERO):
        info = rows_map.get(nombre)
        if not info:
            info = {'ventas': ZERO, 'coste': ZERO}
        info['ventas'] += vent_inc
        info['coste'] += cost_inc
        rows_map[nombre] = info

    # === Ventas agrupadas ===
    if group == 'proveedor':
        v_group = (ventas_qs
                   .values(nombre=F('producto__proveedor__nombre_empresa'))
                   .annotate(
                       vent=Coalesce(
                           Sum(F('cantidad') * F('precio_unitario'), output_field=DecimalField()),
                           ZERO
                       )
                   ))
        for v in v_group:
            nombre = v['nombre'] or '—'
            add_row(nombre, D(v['vent']), ZERO)

        # Costes por proveedor (desc/IVA del proveedor)
        for c in compras_qs:
            nombre = c.proveedor.nombre_empresa or '—'
            desc = pct(c.proveedor.porcentaje_descuento)
            iva  = pct(c.proveedor.iva)
            coste = (D(c.cantidad) * D(c.precio_unitario)) * (ONE - desc) * (ONE + iva)
            add_row(nombre, ZERO, coste)

    else:
        # group == 'producto'
        v_group = (ventas_qs
                   .values(nombre=F('producto__nombre'))
                   .annotate(
                       vent=Coalesce(
                           Sum(F('cantidad') * F('precio_unitario'), output_field=DecimalField()),
                           ZERO
                       )
                   ))
        for v in v_group:
            nombre = v['nombre'] or '—'
            add_row(nombre, D(v['vent']), ZERO)

        # Costes por producto (desc/IVA del proveedor del producto)
        for c in compras_qs:
            nombre = c.producto.nombre or '—'
            desc = pct(c.producto.proveedor.porcentaje_descuento)
            iva  = pct(c.producto.proveedor.iva)
            coste = (D(c.cantidad) * D(c.precio_unitario)) * (ONE - desc) * (ONE + iva)
            add_row(nombre, ZERO, coste)

    # Pasar a lista con beneficio
    rows = []
    for nombre, info in rows_map.items():
        vent = info['ventas']
        cost = info['coste']
        ben  = vent - cost
        rows.append((nombre, vent, cost, ben))

    # Orden según modo
    if mode == 'bottom5':
        rows.sort(key=lambda x: x[3])  # beneficio asc
        rows = rows[:5]
    else:
        # top5 (por defecto) y recent5
        rows.sort(key=lambda x: x[3], reverse=True)  # beneficio desc
        rows = rows[:5]

    # Etiquetas de fechas para el UI
    if desde:
        desde_label = desde.strftime('%d/%m/%Y')
    else:
        # 'all': si hay ventas, usa la primera fecha; si no, si hay compras; si no, hoy
        if Venta.objects.exists():
            desde_label = Venta.objects.order_by('fecha').first().fecha.strftime('%d/%m/%Y')
        elif CompraProveedor.objects.exists():
            desde_label = CompraProveedor.objects.order_by('fecha').first().fecha.strftime('%d/%m/%Y')
        else:
            desde_label = hasta.strftime('%d/%m/%Y')

    data = {
        'labels': [name for (name, _, __, ___) in rows],
        'ventas': [to2f(v) for (_, v, __, ___) in rows],
        'costes': [to2f(c) for (_, __, c, ___) in rows],
        'beneficio': [to2f(b) for (_, __, ___, b) in rows],
        'desde': desde_label,
        'hasta': hasta.strftime('%d/%m/%Y'),
        'group': group,
        'range': r,
        'mode': mode,
    }
    return JsonResponse(data)


@solo_admin_negocio
@require_GET
def admin_analytics_stats(request):
    """
    Estadísticas resumidas y Top 5 por beneficio en el rango/grupo indicados.
    GET:
      range: '1m'|'6m'|'all' (por defecto 'all')
      group: 'producto'|'proveedor' (por defecto 'producto')
    """
    r = request.GET.get('range', 'all')
    group = request.GET.get('group', 'producto')

    hasta = timezone.now()
    if r == '1m':
        desde = hasta - timedelta(days=30)
    elif r == '6m':
        desde = hasta - timedelta(days=180)
    else:
        desde = None  # all (histórico completo)

    # Base QS
    ventas_qs = Venta.objects.all()
    compras_qs = CompraProveedor.objects.select_related('proveedor', 'producto', 'producto__proveedor')

    # Filtro por fechas (si aplica)
    if desde:
        ventas_qs = ventas_qs.filter(fecha__gte=desde, fecha__lte=hasta)
        compras_qs = compras_qs.filter(fecha__gte=desde, fecha__lte=hasta)

    # ==== Totales (Decimal) =====
    total_ventas_dec = D(
        ventas_qs.aggregate(v=Coalesce(Sum(F('cantidad') * F('precio_unitario')), ZERO))['v']
        or ZERO
    )

    total_coste_dec = ZERO
    for c in compras_qs:
        # coste = cantidad * precio_unit * (1 - desc) * (1 + iva)
        if group == 'proveedor':
            desc = pct(c.proveedor.porcentaje_descuento)
            iva  = pct(c.proveedor.iva)
        else:
            # por producto: desc/iva del proveedor del producto
            desc = pct(c.producto.proveedor.porcentaje_descuento)
            iva  = pct(c.producto.proveedor.iva)

        total_coste_dec += (D(c.cantidad) * D(c.precio_unitario)) * (ONE - desc) * (ONE + iva)

    total_beneficio_dec = total_ventas_dec - total_coste_dec

    # ==== Top 5 por beneficio (mismo criterio que admin_analytics_data) ====
    rows_map = {}  # nombre -> {'ventas': Decimal, 'coste': Decimal}
    def add_row(nombre, vent_inc=ZERO, cost_inc=ZERO):
        info = rows_map.get(nombre)
        if not info:
            info = {'ventas': ZERO, 'coste': ZERO}
        info['ventas'] += vent_inc
        info['coste'] += cost_inc
        rows_map[nombre] = info

    # Ventas agrupadas
    if group == 'proveedor':
        v_group = (ventas_qs
                   .values(nombre=F('producto__proveedor__nombre_empresa'))
                   .annotate(vent=Coalesce(Sum(F('cantidad') * F('precio_unitario')), ZERO)))
        for v in v_group:
            nombre = v['nombre'] or '—'
            add_row(nombre, D(v['vent']), ZERO)

        # Costes por proveedor
        for c in compras_qs:
            nombre = c.proveedor.nombre_empresa or '—'
            desc = pct(c.proveedor.porcentaje_descuento)
            iva  = pct(c.proveedor.iva)
            coste = (D(c.cantidad) * D(c.precio_unitario)) * (ONE - desc) * (ONE + iva)
            add_row(nombre, ZERO, coste)

    else:
        # group == 'producto'
        v_group = (ventas_qs
                   .values(nombre=F('producto__nombre'))
                   .annotate(vent=Coalesce(Sum(F('cantidad') * F('precio_unitario')), ZERO)))
        for v in v_group:
            nombre = v['nombre'] or '—'
            add_row(nombre, D(v['vent']), ZERO)

        # Costes por producto (desc/iva del proveedor del producto)
        for c in compras_qs:
            nombre = c.producto.nombre or '—'
            desc = pct(c.producto.proveedor.porcentaje_descuento)
            iva  = pct(c.producto.proveedor.iva)
            coste = (D(c.cantidad) * D(c.precio_unitario)) * (ONE - desc) * (ONE + iva)
            add_row(nombre, ZERO, coste)

    # Construir filas con beneficio
    rows = []
    for nombre, info in rows_map.items():
        vent = info['ventas']
        cost = info['coste']
        ben  = vent - cost
        rows.append((nombre, vent, cost, ben))

    # Top 5 por beneficio DESC
    rows.sort(key=lambda x: x[3], reverse=True)
    top_rows = rows[:5]

    # Etiquetas de 'desde'/'hasta' para mostrar
    if desde:
        desde_label = desde.strftime('%d/%m/%Y')
    else:
        # all: usa fecha de primera venta si existe, si no hoy
        if Venta.objects.exists():
            desde_label = Venta.objects.order_by('fecha').first().fecha.strftime('%d/%m/%Y')
        else:
            desde_label = hasta.strftime('%d/%m/%Y')

    stats = {
        'desde': desde_label,
        'hasta': hasta.strftime('%d/%m/%Y'),
        'total_ventas': to2f(total_ventas_dec),
        'total_coste': to2f(total_coste_dec),
        'total_beneficio': to2f(total_beneficio_dec),
        'top_labels': [name for (name, _, __, ___) in top_rows],
        'top_beneficio': [to2f(ben) for (_, __, ___, ben) in top_rows],
        'group': group,
        'range': r,
    }
    return JsonResponse(stats)

@solo_admin_negocio
@require_GET
def admin_historial_producto(request, producto_id: int):
    """
    Devuelve el historial unificado para un producto:
    - ventas a clientes
    - compras a proveedor
    Ordenado por fecha desc.
    """
    try:
        prod = Producto.objects.get(id=producto_id)
    except Producto.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Producto no encontrado'}, status=404)

    # Filtros opcionales (p. ej. ?range=1m|6m|all)
    r = request.GET.get('range', 'all')
    hasta = timezone.now()
    if r == '1m':
        desde = hasta - timedelta(days=30)
    elif r == '6m':
        desde = hasta - timedelta(days=180)
    else:
        desde = None

    ventas_qs = Venta.objects.filter(producto=prod).select_related('cliente')
    compras_qs = CompraProveedor.objects.filter(producto=prod).select_related('proveedor')

    if desde:
        ventas_qs = ventas_qs.filter(fecha__gte=desde, fecha__lte=hasta)
        compras_qs = compras_qs.filter(fecha__gte=desde, fecha__lte=hasta)

    filas = []

    # Ventas → tipo='venta'
    for v in ventas_qs:
        total = D(v.cantidad) * D(v.precio_unitario)
        filas.append({
            'tipo': 'venta',
            'fecha': v.fecha.strftime('%d/%m/%Y %H:%M'),
            'entidad': v.cliente.username if v.cliente_id else '—',
            'cantidad': int(v.cantidad),
            'precio_unit': to2f(v.precio_unitario),
            'total': to2f(total),
        })

    # Compras → tipo='compra'
    for c in compras_qs:
        total = D(c.cantidad) * D(c.precio_unitario)
        filas.append({
            'tipo': 'compra',
            'fecha': c.fecha.strftime('%d/%m/%Y %H:%M'),
            'entidad': c.proveedor.nombre_empresa if c.proveedor_id else '—',
            'cantidad': int(c.cantidad),
            'precio_unit': to2f(c.precio_unitario),
            'total': to2f(total),
        })

    # Ordenar por fecha desc (ya están como texto; mejor ordenar por obj)
    # Reordenamos parseando de nuevo (rápido y suficiente)
    from datetime import datetime
    def parse_f(d): return datetime.strptime(d, '%d/%m/%Y %H:%M')
    filas.sort(key=lambda x: parse_f(x['fecha']), reverse=True)

    # Totales simples
    total_ventas = to2f(sum(D(f['total']) for f in filas if f['tipo'] == 'venta'))
    total_compras = to2f(sum(D(f['total']) for f in filas if f['tipo'] == 'compra'))
    margen = to2f(D(total_ventas) - D(total_compras))

    return JsonResponse({
        'ok': True,
        'producto': {'id': prod.id, 'nombre': prod.nombre},
        'range': r,
        'filas': filas,
        'resumen': {
            'total_ventas': total_ventas,
            'total_compras': total_compras,
            'margen': margen
        }
    })

@login_required
def confirmar_compra(request):
    carrito = request.session.get("carrito", {})

    if not carrito:
        messages.error(request, "Tu carrito está vacío.")
        return redirect("ver_carrito")

    # Usar Decimal en vez de float
    total = sum(
        Decimal(str(item["precio"])) * int(item["cantidad"])
        for item in carrito.values()
    )

    # Pasar STRIPE_PUBLIC_KEY al template
    return render(request, "confirmar_compra.html", {
        "carrito": carrito,
        "total": total,
        "STRIPE_PUBLIC_KEY": settings.STRIPE_PUBLIC_KEY  # <- muy importante
    })

@csrf_protect
def save_crypto_payment(request):
    if request.method == "POST":
        data = json.loads(request.body)
        wallet = data.get("wallet")
        tx_hash = data.get("tx_hash")
        amount = data.get("amount")
        
        # Guardar pedido en DB
        pedido = Pedido.objects.create(
            usuario=request.user,  # requiere login
            wallet=wallet,
            tx_hash=tx_hash,
            total=amount,
            pagado=True
        )

        # Vaciar carrito
        request.session['carrito'] = {}

        return JsonResponse({"status": "ok", "tx_hash": tx_hash})


stripe.api_key = settings.STRIPE_SECRET_KEY

@csrf_protect
def crear_pago_tarjeta(request):
    if request.method == "POST":
        data = json.loads(request.body)
        total = Decimal(str(data.get("total")))  # DECIMAL seguro

        # Stripe espera centavos enteros
        amount = int(total * 100)

        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'eur',
                    'product_data': {'name': 'Compra en tu tienda'},
                    'unit_amount': amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url='http://127.0.0.1:8000/pago_exitoso/',
            cancel_url='http://127.0.0.1:8000/confirmar_compra/',
        )
        return JsonResponse({'id': session.id})

@login_required
def pago_exitoso(request):
    # Vaciar carrito
    request.session['carrito'] = {}

    # Mensaje de éxito
    return render(request, "pago_exitoso.html", {
        "mensaje": "¡Pago realizado con tarjeta correctamente! Tu carrito se ha vaciado."
    })