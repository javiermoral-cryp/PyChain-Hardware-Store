"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path

from django.contrib import admin
from django.urls import path
from myapp import views
from django.conf import settings
from django.conf.urls.static import  static

urlpatterns = [
    path('admin/', admin.site.urls),

    path('login/cliente/', views.login_cliente, name='login_cliente'),
    path('login/admin/', views.login_admin_negocio, name='login_admin'),
    path('tienda/', views.vista_cliente, name='vista_cliente'),
    path('panel/', views.panel_admin_negocio, name='panel_admin_negocio'),
    path('', views.vista_cliente, name='inicio'),
    path('cuenta/', views.inicio_cuenta, name='mi_cuenta'),
    path('registro/cliente/', views.registro_cliente, name='registro_cliente'),
    path('registro/admin/', views.registro_admin, name='registro_admin'),
    path('logout/', views.cerrar_sesion, name='logout'),

    path('datos/ventas/', views.datos_ventas_cliente, name='datos_ventas'),

    path('producto/<int:producto_id>/', views.detalle_producto, name='detalle_producto'),
    path('carrito/agregar/<int:producto_id>', views.añadir_carrito, name='añadir_carrito'),
    path('carrito/', views.ver_carrito, name='ver_carrito'),
    path('carrito/aumentar/<int:producto_id>/', views.aumentar_cantidad, name='aumentar_cantidad'),
    path('carrito/disminuir/<int:producto_id>/', views.disminuir_cantidad, name='disminuir_cantidad'),
    path('carrito/eliminar/<int:producto_id>/', views.eliminar_del_carrito, name='eliminar_del_carrito'),
    path("compra/", views.realizar_compra, name="realizar_compra"),
    path('proveedores/solicitar/', views.enviar_mensaje_proveedor, name='enviar_mensaje_proveedor'),
    path('panel/api/producto/actualizar/', views.admin_actualizar_producto, name='admin_actualizar_producto'),
    path('panel/api/analitica/', views.admin_analytics_data, name='admin_analytics_data'),
    path('panel/api/analitica/stats/', views.admin_analytics_stats, name='admin_analytics_stats'),
    path('panel/api/historial/producto/<int:producto_id>/', views.admin_historial_producto, name='admin_historial_producto'),
    path("confirmar-compra/", views.confirmar_compra, name="confirmar_compra"),
    path("realizar-compra/", views.realizar_compra, name="realizar_compra"),

    path('save-crypto-payment/', views.save_crypto_payment, name='save_crypto_payment'),
    path('crear_pago_tarjeta/', views.crear_pago_tarjeta, name='crear_pago_tarjeta'),
    path('pago_exitoso/', views.pago_exitoso, name='pago_exitoso'),

]
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
