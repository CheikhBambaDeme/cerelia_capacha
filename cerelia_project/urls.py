"""
URL configuration for cerelia_project project.
Cerelia Production Simulation Tool
"""

from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('simulation.urls')),
]
