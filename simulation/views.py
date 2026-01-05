"""
Views for Cerelia Simulation
Includes both API viewsets and template views
"""

from django.shortcuts import render
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view
from rest_framework.response import Response

from .models import (
    Site, ProductCategory, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast, LineConfigOverride,
    LabCategory, LabLine, LabClient, LabProduct, LabForecast
)
from .serializers import (
    SiteSerializer, ProductCategorySerializer, ShiftConfigurationSerializer,
    ProductionLineSerializer, ClientSerializer, ProductSerializer,
    LineProductAssignmentSerializer, DemandForecastSerializer,
    LineSimulationRequestSerializer,
    NewClientSimulationRequestSerializer, LostClientSimulationRequestSerializer,
    LineConfigOverrideSerializer,
    LabCategorySerializer, LabLineSerializer, LabClientSerializer,
    LabProductSerializer, LabForecastSerializer, LabSimulationRequestSerializer
)
from .services import (
    run_line_simulation,
    run_new_client_simulation, run_lost_client_simulation,
    run_lab_simulation
)


# =============================================================================
# Template Views (Dashboard Pages)
# =============================================================================

def dashboard_home(request):
    """Main dashboard page"""
    return render(request, 'simulation/dashboard.html')


def line_simulation_view(request):
    """Line simulation dashboard (Dashboard 1)"""
    return render(request, 'simulation/line_simulation.html')


def line_configuration_view(request):
    """Line configuration page for manual adjustments"""
    return render(request, 'simulation/line_configuration.html')


# =============================================================================
# Lab Template Views
# =============================================================================

def lab_line_view(request):
    """Lab Line management page"""
    return render(request, 'simulation/lab_line.html')


def lab_client_view(request):
    """Lab Client management page"""
    return render(request, 'simulation/lab_client.html')


def lab_product_view(request):
    """Lab Product management page"""
    return render(request, 'simulation/lab_product.html')


def lab_category_view(request):
    """Lab Category management page"""
    return render(request, 'simulation/lab_category.html')


def lab_forecast_view(request):
    """Lab Forecast management page"""
    return render(request, 'simulation/lab_forecast.html')


def lab_simulation_view(request):
    """Lab Simulation page (combines real and lab data)"""
    return render(request, 'simulation/lab_simulation.html')


# =============================================================================
# API ViewSets
# =============================================================================

class SiteViewSet(viewsets.ModelViewSet):
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    search_fields = ['name', 'code']


class ProductCategoryViewSet(viewsets.ModelViewSet):
    queryset = ProductCategory.objects.all()
    serializer_class = ProductCategorySerializer
    search_fields = ['name']


class ShiftConfigurationViewSet(viewsets.ModelViewSet):
    queryset = ShiftConfiguration.objects.all()
    serializer_class = ShiftConfigurationSerializer


class ProductionLineViewSet(viewsets.ModelViewSet):
    queryset = ProductionLine.objects.filter(is_active=True)
    serializer_class = ProductionLineSerializer
    filterset_fields = ['site', 'is_active']
    search_fields = ['name', 'code']
    
    @action(detail=False, methods=['get'])
    def by_site(self, request):
        """Get lines grouped by site"""
        site_id = request.query_params.get('site_id')
        if site_id:
            lines = self.queryset.filter(site_id=site_id)
        else:
            lines = self.queryset.all()
        serializer = self.get_serializer(lines, many=True)
        return Response(serializer.data)


class ClientViewSet(viewsets.ModelViewSet):
    queryset = Client.objects.filter(is_active=True)
    serializer_class = ClientSerializer
    filterset_fields = ['is_active', 'code']
    search_fields = ['name', 'code']


class ProductViewSet(viewsets.ModelViewSet):
    queryset = Product.objects.filter(is_active=True)
    serializer_class = ProductSerializer
    filterset_fields = ['category', 'is_active']
    search_fields = ['code', 'name']
    
    @action(detail=False, methods=['get'])
    def by_category(self, request):
        """Get products filtered by category"""
        category_id = request.query_params.get('category_id')
        if category_id:
            products = self.queryset.filter(category_id=category_id)
        else:
            products = self.queryset.all()
        serializer = self.get_serializer(products, many=True)
        return Response(serializer.data)


class LineProductAssignmentViewSet(viewsets.ModelViewSet):
    queryset = LineProductAssignment.objects.all()
    serializer_class = LineProductAssignmentSerializer
    filterset_fields = ['line', 'product', 'is_default']


class DemandForecastViewSet(viewsets.ModelViewSet):
    queryset = DemandForecast.objects.all()
    serializer_class = DemandForecastSerializer
    filterset_fields = ['client', 'product', 'year', 'week_number']
    
    @action(detail=False, methods=['get'])
    def by_date_range(self, request):
        """Get forecasts within a date range"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        client_id = request.query_params.get('client_id')
        product_id = request.query_params.get('product_id')
        
        queryset = self.queryset
        
        if start_date:
            queryset = queryset.filter(week_start_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(week_start_date__lte=end_date)
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        if product_id:
            queryset = queryset.filter(product_id=product_id)
        
        serializer = self.get_serializer(queryset[:500], many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def products_by_client(self, request):
        """Get products that have forecasts for a specific client"""
        client_id = request.query_params.get('client_id')
        if not client_id:
            return Response({'error': 'client_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Get distinct product IDs from forecasts for this client
        product_ids = DemandForecast.objects.filter(
            client_id=client_id
        ).values_list('product_id', flat=True).distinct()
        
        # Get the product details
        products = Product.objects.filter(id__in=product_ids).order_by('name')
        serializer = ProductSerializer(products, many=True)
        return Response(serializer.data)


class LineConfigOverrideViewSet(viewsets.ModelViewSet):
    """ViewSet for managing line configuration overrides"""
    queryset = LineConfigOverride.objects.all()
    serializer_class = LineConfigOverrideSerializer
    filterset_fields = ['line', 'is_active']
    
    @action(detail=False, methods=['get'])
    def by_line(self, request):
        """Get all overrides for a specific line"""
        line_id = request.query_params.get('line_id')
        if not line_id:
            return Response({'error': 'line_id is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        overrides = self.queryset.filter(line_id=line_id).order_by('-start_date')
        serializer = self.get_serializer(overrides, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get all currently active overrides (today falls within date range)"""
        from datetime import date
        today = date.today()
        overrides = self.queryset.filter(
            is_active=True,
            start_date__lte=today,
            end_date__gte=today
        )
        serializer = self.get_serializer(overrides, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def upcoming(self, request):
        """Get all upcoming and active overrides"""
        from datetime import date
        today = date.today()
        overrides = self.queryset.filter(
            is_active=True,
            end_date__gte=today
        ).order_by('start_date')
        serializer = self.get_serializer(overrides, many=True)
        return Response(serializer.data)


# =============================================================================
# Simulation API Endpoints
# =============================================================================

@api_view(['POST'])
def simulate_line(request):
    """
    Line Simulation API (Dashboard 1)
    Analyze demand vs capacity for selected production lines
    """
    serializer = LineSimulationRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    result = run_line_simulation(
        line_ids=data['line_ids'],
        shift_configs=data['shift_configs'],
        start_date=data['start_date'],
        end_date=data['end_date'],
        client_codes=data.get('client_codes'),
        category_id=data.get('category_id'),
        product_code=data.get('product_code'),
        overlay_client_codes=data.get('overlay_client_codes', []),
        granularity=data.get('granularity', 'week'),
        demand_modifications=data.get('demand_modifications')
    )
    
    return Response(result)


@api_view(['POST'])
def simulate_new_client(request):
    """
    New Client Simulation API (Dashboard 3)
    Analyze impact of adding a new client
    """
    serializer = NewClientSimulationRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    result = run_new_client_simulation(
        line_ids=data['line_ids'],
        shift_configs=data['shift_configs'],
        start_date=data['start_date'],
        end_date=data['end_date'],
        new_client_demand=data['new_client_demand'],
        remove_client_id=data.get('remove_client_id')
    )
    
    return Response(result)


@api_view(['POST'])
def simulate_lost_client(request):
    """
    Lost Client Simulation API (Dashboard 4)
    Analyze impact of losing a client
    """
    serializer = LostClientSimulationRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    result = run_lost_client_simulation(
        line_ids=data['line_ids'],
        shift_configs=data['shift_configs'],
        start_date=data['start_date'],
        end_date=data['end_date'],
        lost_client_id=data['lost_client_id']
    )
    
    return Response(result)


@api_view(['POST', 'PATCH'])
def update_line_config(request, pk):
    """
    Update line default configuration (shift config, capacity, efficiency)
    For temporary overrides, use the LineConfigOverride API instead.
    """
    from decimal import Decimal
    
    try:
        line = ProductionLine.objects.get(pk=pk)
    except ProductionLine.DoesNotExist:
        return Response({'error': 'Line not found'}, status=status.HTTP_404_NOT_FOUND)
    
    data = request.data
    
    # Update shift configuration preset
    if 'default_shift_config' in data:
        if data['default_shift_config']:
            try:
                shift_config = ShiftConfiguration.objects.get(pk=data['default_shift_config'])
                line.default_shift_config = shift_config
            except ShiftConfiguration.DoesNotExist:
                return Response({'error': 'Shift configuration not found'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            line.default_shift_config = None
    
    # Update base capacity per hour
    if 'base_capacity_per_hour' in data:
        line.base_capacity_per_hour = Decimal(str(data['base_capacity_per_hour']))
    
    # Update efficiency factor
    if 'efficiency_factor' in data:
        line.efficiency_factor = Decimal(str(data['efficiency_factor']))
    
    line.save()
    
    serializer = ProductionLineSerializer(line)
    return Response(serializer.data)


# =============================================================================
# Lab API ViewSets
# =============================================================================

class LabCategoryViewSet(viewsets.ModelViewSet):
    queryset = LabCategory.objects.all()
    serializer_class = LabCategorySerializer
    search_fields = ['name', 'code']


class LabLineViewSet(viewsets.ModelViewSet):
    queryset = LabLine.objects.all()
    serializer_class = LabLineSerializer
    filterset_fields = ['site']
    search_fields = ['name', 'code']


class LabClientViewSet(viewsets.ModelViewSet):
    queryset = LabClient.objects.all()
    serializer_class = LabClientSerializer
    search_fields = ['name', 'code']


class LabProductViewSet(viewsets.ModelViewSet):
    queryset = LabProduct.objects.all()
    serializer_class = LabProductSerializer
    filterset_fields = ['category', 'lab_category', 'default_line', 'lab_default_line']
    search_fields = ['name', 'code']


class LabForecastViewSet(viewsets.ModelViewSet):
    queryset = LabForecast.objects.all()
    serializer_class = LabForecastSerializer
    filterset_fields = ['client', 'lab_client', 'product', 'lab_product']
    
    @action(detail=False, methods=['get'])
    def by_date_range(self, request):
        """Get lab forecasts within a date range"""
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        
        queryset = self.queryset
        
        if start_date:
            queryset = queryset.filter(start_date__lte=end_date, end_date__gte=start_date)
        
        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data)


# =============================================================================
# Lab Simulation API Endpoint
# =============================================================================

@api_view(['POST'])
def simulate_lab(request):
    """
    Lab Simulation API
    Combines real data with lab (fictive) data for simulation
    """
    serializer = LabSimulationRequestSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    data = serializer.validated_data
    
    result = run_lab_simulation(
        line_ids=data.get('line_ids', []),
        lab_line_ids=data.get('lab_line_ids', []),
        start_date=data['start_date'],
        end_date=data['end_date'],
        include_lab_forecasts=data.get('include_lab_forecasts', True),
        demand_modifications=data.get('demand_modifications')
    )
    
    return Response(result)

