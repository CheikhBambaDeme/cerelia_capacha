"""
URL configuration for simulation app
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# API Router
router = DefaultRouter()
router.register(r'sites', views.SiteViewSet)
router.register(r'shift-configs', views.ShiftConfigurationViewSet)
router.register(r'lines', views.ProductionLineViewSet)
router.register(r'clients', views.ClientViewSet)
router.register(r'products', views.ProductViewSet)
router.register(r'line-assignments', views.LineProductAssignmentViewSet)
router.register(r'forecasts', views.DemandForecastViewSet)
router.register(r'line-overrides', views.LineConfigOverrideViewSet)

# Lab API Router
router.register(r'lab/categories', views.LabCategoryViewSet)
router.register(r'lab/lines', views.LabLineViewSet)
router.register(r'lab/clients', views.LabClientViewSet)
router.register(r'lab/products', views.LabProductViewSet)
router.register(r'lab/forecasts', views.LabForecastViewSet)

# Simulation Category and Custom Shift Config API Router
router.register(r'simulation-categories', views.SimulationCategoryViewSet)
router.register(r'custom-shift-configs', views.CustomShiftConfigurationViewSet)

urlpatterns = [
    # Template views (Dashboard pages)
    path('', views.dashboard_home, name='dashboard_home'),
    path('line-simulation/', views.line_simulation_view, name='line_simulation'),
    path('line-configuration/', views.line_configuration_view, name='line_configuration'),
    
    # New Category and Shift Management views
    path('categories/', views.simulation_category_view, name='simulation_category'),
    path('shift-management/', views.shift_management_view, name='shift_management'),
    
    # Lab template views
    path('lab/line/', views.lab_line_view, name='lab_line'),
    path('lab/client/', views.lab_client_view, name='lab_client'),
    path('lab/product/', views.lab_product_view, name='lab_product'),
    path('lab/category/', views.lab_category_view, name='lab_category'),
    path('lab/forecast/', views.lab_forecast_view, name='lab_forecast'),
    path('lab/simulation/', views.lab_simulation_view, name='lab_simulation'),
    
    # API endpoints
    path('api/', include(router.urls)),
    
    # Simulation API endpoints
    path('api/simulate/line/', views.simulate_line, name='api_simulate_line'),
    path('api/simulate/category/', views.simulate_category, name='api_simulate_category'),
    path('api/simulate/new-client/', views.simulate_new_client, name='api_simulate_new_client'),
    path('api/simulate/lost-client/', views.simulate_lost_client, name='api_simulate_lost_client'),
    path('api/simulate/lab/', views.simulate_lab, name='api_simulate_lab'),
    
    # Line configuration API
    path('api/lines/<int:pk>/update-config/', views.update_line_config, name='api_update_line_config'),
]
