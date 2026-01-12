"""
Django Admin configuration for Cerelia Simulation
"""

from django.contrib import admin
from .models import (
    Site, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast,
    SimulationCategory, CustomShiftConfiguration, LineConfigOverride
)


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'is_active', 'created_at']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['name']


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
    list_display = ['code', 'name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['code', 'name']
    ordering = ['name']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'default_line', 'product_type', 'recipe_type', 'is_active']
    list_filter = ['is_active', 'product_type', 'recipe_type', 'material_type', 'packaging_type']
    search_fields = ['code', 'name', 'product_type', 'recipe_type']
    autocomplete_fields = ['default_line']


@admin.register(LineProductAssignment)
class LineProductAssignmentAdmin(admin.ModelAdmin):
    list_display = ['product', 'line', 'is_default', 'production_rate_per_hour']
    list_filter = ['is_default', 'line__site', 'line']
    search_fields = ['product__code', 'product__name', 'line__name']
    autocomplete_fields = ['line', 'product']


@admin.register(DemandForecast)
class DemandForecastAdmin(admin.ModelAdmin):
    list_display = ['client', 'product', 'year', 'week_number', 'week_start_date', 
                    'forecast_quantity']
    list_filter = ['year', 'client']
    search_fields = ['client__name', 'product__code', 'product__name']
    autocomplete_fields = ['client', 'product']
    date_hierarchy = 'week_start_date'
    ordering = ['-year', '-week_number']


@admin.register(SimulationCategory)
class SimulationCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'site', 'line_count', 'is_active', 'created_at']
    list_filter = ['is_active', 'site']
    search_fields = ['name', 'description']
    filter_horizontal = ['lines']
    
    def line_count(self, obj):
        return obj.lines.count()
    line_count.short_description = 'Lines'


@admin.register(CustomShiftConfiguration)
class CustomShiftConfigurationAdmin(admin.ModelAdmin):
    list_display = ['name', 'shifts_per_day', 'hours_per_shift', 'days_per_week',
                    'includes_saturday', 'includes_sunday', 'weekly_hours']
    list_filter = ['shifts_per_day', 'days_per_week', 'includes_saturday', 'includes_sunday']
    search_fields = ['name', 'description']


@admin.register(LineConfigOverride)
class LineConfigOverrideAdmin(admin.ModelAdmin):
    list_display = ['line', 'start_date', 'end_date', 'config_display', 
                    'reason', 'is_recurrent', 'is_active']
    list_filter = ['is_active', 'is_recurrent', 'line__site']
    search_fields = ['line__name', 'reason']
    autocomplete_fields = ['line']
    date_hierarchy = 'start_date'
