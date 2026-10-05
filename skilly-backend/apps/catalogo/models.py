"""
Modelos de la app catalogo.

Ticket 0.15 (sprint actual) adelantado: se crea Categoria porque el comando
cargar_seed lo necesita. Servicio y Entregable son del Sprint 2 (tickets 2.2
y 2.3) y siguen pendientes.
"""


from django.db import models


class Categoria(models.Model):
    """
    Categoria de servicios. Publicar un servicio exige una categoria aprobada
    (ticket 2.1).
    """

    nombre = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=120, unique=True)
    # 0.15: las 5 categorias del seed entran ya aprobadas para que el flujo de
    # publicacion se pueda probar desde el Sprint 1.
    aprobada = models.BooleanField(default=False)
    activa = models.BooleanField(default=True)

    class Meta:
        verbose_name = "categoría"
        verbose_name_plural = "categorías"
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre