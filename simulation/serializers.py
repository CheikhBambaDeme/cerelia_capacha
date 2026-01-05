"""
Django REST Framework Serializers for Cerelia Simulation
"""

from rest_framework import serializers
from .models import (
    Site, ProductCategory, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast, LineConfigOverride
)


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ['id', 'name', 'code', 'is_active']


class ProductCategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductCategory
        fields = ['id', 'name', 'description', 'color_code', 'product_count']
    
    def get_product_count(self, obj):
        return obj.products.count()


class ShiftConfigurationSerializer(serializers.ModelSerializer):
    weekly_hours = serializers.ReadOnlyField()
    
    class Meta:
        model = ShiftConfiguration
        fields = ['id', 'name', 'description', 'shifts_per_day', 'hours_per_shift',
                  'days_per_week', 'includes_saturday', 'includes_sunday', 'weekly_hours']


class ProductionLineSerializer(serializers.ModelSerializer):
    site_name = serializers.ReadOnlyField()
    site_code = serializers.CharField(source='site.code', read_only=True)
    default_shift_config_name = serializers.CharField(
        source='default_shift_config.name', read_only=True
    )
    default_weekly_hours = serializers.ReadOnlyField()
    active_overrides_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ProductionLine
        fields = ['id', 'name', 'code', 'site', 'site_name', 'site_code', 'default_shift_config',
                  'default_shift_config_name', 'base_capacity_per_hour', 
                  'efficiency_factor', 'is_active', 'default_weekly_hours',
                  'active_overrides_count']
    
    def get_active_overrides_count(self, obj):
        from datetime import date
        return obj.config_overrides.filter(
            is_active=True,
            end_date__gte=date.today()
        ).count()


class LineConfigOverrideSerializer(serializers.ModelSerializer):
    line_name = serializers.CharField(source='line.name', read_only=True)
    site_name = serializers.CharField(source='line.site.name', read_only=True)
    config_display = serializers.ReadOnlyField()
    weekly_hours = serializers.ReadOnlyField()
    
    class Meta:
        model = LineConfigOverride
        fields = ['id', 'line', 'line_name', 'site_name', 'start_date', 'end_date',
                  'shifts_per_day', 'hours_per_shift', 'include_saturday', 
                  'include_sunday', 'reason', 'is_recurrent', 'recurrence_weeks', 'is_active', 'config_display', 
                  'weekly_hours', 'created_at']


class ClientSerializer(serializers.ModelSerializer):
    class Meta:
        model = Client
        fields = ['id', 'name', 'code', 'is_active', 'notes']


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    default_line_name = serializers.CharField(source='default_line.name', read_only=True)
    
    class Meta:
        model = Product
        fields = ['id', 'code', 'name', 'category', 'category_name', 
                  'default_line', 'default_line_name', 'unit_weight', 'is_active']


class LineProductAssignmentSerializer(serializers.ModelSerializer):
    line_name = serializers.CharField(source='line.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = LineProductAssignment
        fields = ['id', 'line', 'line_name', 'product', 'product_code', 
                  'product_name', 'is_default', 'production_rate_per_hour']


class DemandForecastSerializer(serializers.ModelSerializer):
    client_name = serializers.CharField(source='client.name', read_only=True)
    product_code = serializers.CharField(source='product.code', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    
    class Meta:
        model = DemandForecast
        fields = ['id', 'client', 'client_name', 'product', 'product_code',
                  'product_name', 'year', 'week_number', 'week_start_date',
                  'forecast_quantity']


# Simulation Request/Response Serializers

class LineShiftConfigSerializer(serializers.Serializer):
    """Per-line shift configuration for simulation"""
    line_id = serializers.IntegerField()
    shift_config_id = serializers.IntegerField(required=False, allow_null=True)
    use_override = serializers.BooleanField(required=False, default=False)


class DemandModificationSerializer(serializers.Serializer):
    """Demand modification for adjusting client/product demand by percentage"""
    client_id = serializers.IntegerField()
    product_id = serializers.IntegerField(required=False, allow_null=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    percentage = serializers.DecimalField(max_digits=8, decimal_places=2)  # -100 to +infinity


class LineSimulationRequestSerializer(serializers.Serializer):
    """Request for line simulation (Dashboard 1)"""
    line_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    shift_configs = LineShiftConfigSerializer(many=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    client_codes = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
        allow_null=True
    )
    product_code = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    category_id = serializers.IntegerField(required=False, allow_null=True)
    overlay_client_codes = serializers.ListField(
        child=serializers.CharField(max_length=20),
        required=False,
        default=list
    )
    granularity = serializers.ChoiceField(
        choices=['week', 'day'],
        required=False,
        default='week'
    )
    demand_modifications = DemandModificationSerializer(many=True, required=False, allow_null=True)


class NewClientSimulationRequestSerializer(serializers.Serializer):
    """Request for new client simulation (Dashboard 3)"""
    line_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    shift_configs = LineShiftConfigSerializer(many=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    new_client_demand = serializers.DecimalField(max_digits=12, decimal_places=2)
    remove_client_id = serializers.IntegerField(required=False, allow_null=True)


class LostClientSimulationRequestSerializer(serializers.Serializer):
    """Request for lost client simulation (Dashboard 4)"""
    line_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    shift_configs = LineShiftConfigSerializer(many=True)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    lost_client_id = serializers.IntegerField()


class SimulationDataPointSerializer(serializers.Serializer):
    """Single data point in simulation results"""
    date = serializers.CharField()  # Week label
    week_start = serializers.DateField()
    demand = serializers.DecimalField(max_digits=12, decimal_places=2)
    capacity = serializers.DecimalField(max_digits=12, decimal_places=2)
    utilization_percent = serializers.DecimalField(max_digits=5, decimal_places=1)
    over_capacity = serializers.BooleanField()
    # Optional overlay data
    overlay_demand = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    base_demand = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    new_client_demand = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    removed_demand = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)
    lost_demand = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)


class SimulationResultSerializer(serializers.Serializer):
    """Simulation result response"""
    average_utilization = serializers.DecimalField(max_digits=5, decimal_places=1)
    peak_utilization = serializers.DecimalField(max_digits=5, decimal_places=1)
    over_capacity_periods = serializers.IntegerField()
    total_capacity = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_demand = serializers.DecimalField(max_digits=12, decimal_places=2)
    data_points = SimulationDataPointSerializer(many=True)
    overlay_data = serializers.DictField(required=False)
