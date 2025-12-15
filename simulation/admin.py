"""
Django Admin configuration for Cerelia Simulation
"""

from django.contrib import admin
from .models import (
    Site, ProductCategory, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast
)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['name']


@admin.register(ProductCategory)
class ProductCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'color_code', 'product_count']
    search_fields = ['name']
    
    def product_count(self, obj):
        return obj.products.count()
    product_count.short_description = 'Products'


@admin.register(ShiftConfiguration)
class ShiftConfigurationAdmin(admin.ModelAdmin):
    list_display = ['name', 'shifts_per_day', 'hours_per_shift', 'days_per_week', 
                    'includes_saturday', 'includes_sunday', 'weekly_hours']
    list_filter = ['shifts_per_day', 'days_per_week', 'includes_saturday', 'includes_sunday']
    search_fields = ['name']


@admin.register(ProductionLine)
class ProductionLineAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'site', 'default_shift_config', 
                    'base_capacity_per_hour', 'efficiency_factor', 'is_active']
    list_filter = ['site', 'is_active', 'default_shift_config']
    search_fields = ['code', 'name', 'site__name']
    autocomplete_fields = ['site', 'default_shift_config']


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'priority', 'is_active', 'contract_start_date', 'contract_end_date']
    list_filter = ['priority', 'is_active']
    search_fields = ['code', 'name']
    ordering = ['priority', 'name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'category', 'default_line', 'is_fresh', 'is_active']
    list_filter = ['category', 'is_fresh', 'is_active']
    search_fields = ['code', 'name']
    autocomplete_fields = ['category', 'default_line']


@admin.register(LineProductAssignment)
class LineProductAssignmentAdmin(admin.ModelAdmin):
    list_display = ['product', 'line', 'is_default', 'production_rate_per_hour', 'changeover_time_minutes']
    list_filter = ['is_default', 'line__site', 'line']
    search_fields = ['product__code', 'product__name', 'line__name']
    autocomplete_fields = ['line', 'product']


@admin.register(DemandForecast)
class DemandForecastAdmin(admin.ModelAdmin):
    list_display = ['client', 'product', 'year', 'week_number', 'week_start_date', 
                    'forecast_quantity', 'actual_quantity']
    list_filter = ['year', 'client', 'product__category']
    search_fields = ['client__name', 'product__code', 'product__name']
    autocomplete_fields = ['client', 'product']
    date_hierarchy = 'week_start_date'
    ordering = ['-year', '-week_number']
