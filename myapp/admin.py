from django.contrib import admin
from .models import Perfil, Proveedor, Producto, CompraProveedor, Venta



class PerfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'administrador_negocio')

admin.site.register(Perfil, PerfilAdmin)
admin.site.register(Proveedor)
admin.site.register(Producto)
admin.site.register(CompraProveedor)
admin.site.register(Venta)