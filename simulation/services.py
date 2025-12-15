"""
Simulation Services for Cerelia Production Planning
Core business logic for capacity and demand simulations
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional
from django.db.models import Sum, Q
from .models import (
    ProductionLine, ShiftConfiguration, Product, Client,
    ProductCategory, DemandForecast, LineProductAssignment
)


def get_week_start(date):
    """Get the Monday of the week containing the given date"""
    return date - timedelta(days=date.weekday())


def get_weeks_in_range(start_date, end_date):
    """Generate list of week start dates in the given range"""
    weeks = []
    current = get_week_start(start_date)
    while current <= end_date:
        weeks.append(current)
        current += timedelta(days=7)
    return weeks


def get_days_in_range(start_date, end_date):
    """Generate list of dates in the given range"""
    days = []
    current = start_date
    while current <= end_date:
        days.append(current)
        current += timedelta(days=1)
    return days


def calculate_daily_capacity(line_ids: list, shift_configs: dict, for_date) -> Decimal:
    """
    Calculate total daily capacity for given lines with their shift configurations
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        for_date: Date to calculate capacity for
    
    Returns:
        Total daily capacity in units
    """
    total_capacity = Decimal('0')
    day_of_week = for_date.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
    
    lines = ProductionLine.objects.filter(id__in=line_ids, is_active=True)
    
    for line in lines:
        shift_config_id = shift_configs.get(line.id)
        
        # Get the configuration to use
        if shift_config_id:
            try:
                config = ShiftConfiguration.objects.get(id=shift_config_id)
                shifts_per_day = config.shifts_per_day
                hours_per_shift = config.hours_per_shift
                includes_saturday = config.includes_saturday
                includes_sunday = config.includes_sunday
            except ShiftConfiguration.DoesNotExist:
                config_data = line.get_config_for_date(for_date)
                if config_data:
                    shifts_per_day = config_data['shifts_per_day']
                    hours_per_shift = config_data['hours_per_shift']
                    includes_saturday = config_data['include_saturday']
                    includes_sunday = config_data['include_sunday']
                else:
                    continue
        else:
            config_data = line.get_config_for_date(for_date)
            if config_data:
                shifts_per_day = config_data['shifts_per_day']
                hours_per_shift = config_data['hours_per_shift']
                includes_saturday = config_data['include_saturday']
                includes_sunday = config_data['include_sunday']
            else:
                continue
        
        # Check if this day is a working day
        is_working_day = True
        if day_of_week == 5 and not includes_saturday:  # Saturday
            is_working_day = False
        elif day_of_week == 6 and not includes_sunday:  # Sunday
            is_working_day = False
        
        if is_working_day:
            daily_hours = shifts_per_day * hours_per_shift
            daily_capacity = Decimal(str(line.base_capacity_per_hour)) * Decimal(str(daily_hours)) * Decimal(str(line.efficiency_factor))
            total_capacity += daily_capacity
    
    return total_capacity


def calculate_capacity_per_day(line_ids: list, shift_configs: dict, days: list) -> dict:
    """
    Calculate capacity for each day, considering LineConfigOverrides
    """
    capacity_by_day = {}
    
    for day in days:
        capacity = calculate_daily_capacity(line_ids, shift_configs, for_date=day)
        capacity_by_day[day] = capacity
    
    return capacity_by_day


def get_demand_for_lines_daily(line_ids: list, start_date, end_date,
                               client_id: Optional[int] = None,
                               category_id: Optional[int] = None,
                               product_id: Optional[int] = None) -> dict:
    """
    Get demand forecast for products on specified lines, distributed daily
    Distributes weekly demand evenly across working days (Mon-Fri by default)
    
    Returns:
        Dict mapping date -> daily_demand
    """
    # Get weekly demand first
    weekly_demand = get_demand_for_lines(line_ids, start_date, end_date, client_id, category_id, product_id)
    
    # Distribute weekly demand to daily (divide by 5 working days)
    daily_demand = {}
    for week_start, total_weekly in weekly_demand.items():
        # Distribute to Mon-Fri of that week
        for day_offset in range(5):  # Monday to Friday
            day = week_start + timedelta(days=day_offset)
            if start_date <= day <= end_date:
                daily_demand[day] = total_weekly / Decimal('5')
    
    return daily_demand


def get_client_demand_daily(client_id: int, line_ids: list, start_date, end_date) -> dict:
    """Get daily demand for a specific client on specified lines"""
    weekly_demand = get_client_demand(client_id, line_ids, start_date, end_date)
    
    daily_demand = {}
    for week_start, total_weekly in weekly_demand.items():
        for day_offset in range(5):  # Monday to Friday
            day = week_start + timedelta(days=day_offset)
            if start_date <= day <= end_date:
                daily_demand[day] = total_weekly / Decimal('5')
    
    return daily_demand


def calculate_weekly_capacity(line_ids: list, shift_configs: dict, for_date=None) -> Decimal:
    """
    Calculate total weekly capacity for given lines with their shift configurations
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        for_date: Optional date to check for LineConfigOverride entries
    
    Returns:
        Total weekly capacity in units
    """
    total_capacity = Decimal('0')
    
    lines = ProductionLine.objects.filter(id__in=line_ids, is_active=True)
    
    for line in lines:
        # First check if there's a UI-selected shift config override
        shift_config_id = shift_configs.get(line.id)
        
        if shift_config_id:
            # User explicitly selected a shift config in the simulation UI
            try:
                shift_config = ShiftConfiguration.objects.get(id=shift_config_id)
                weekly_capacity = line.get_weekly_capacity(shift_config)
            except ShiftConfiguration.DoesNotExist:
                weekly_capacity = line.get_weekly_capacity(for_date=for_date)
        else:
            # Use date-based override or default config
            weekly_capacity = line.get_weekly_capacity(for_date=for_date)
        
        total_capacity += Decimal(str(weekly_capacity))
    
    return total_capacity


def calculate_capacity_per_week(line_ids: list, shift_configs: dict, weeks: list) -> dict:
    """
    Calculate capacity for each week, considering LineConfigOverrides
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        weeks: List of week start dates
    
    Returns:
        Dict mapping week_start_date -> total_capacity
    """
    capacity_by_week = {}
    
    for week_start in weeks:
        # Use the middle of the week for override checking
        week_date = week_start + timedelta(days=3)
        capacity = calculate_weekly_capacity(line_ids, shift_configs, for_date=week_date)
        capacity_by_week[week_start] = capacity
    
    return capacity_by_week


def get_line_config_details(line_ids: list, for_date) -> list:
    """
    Get configuration details for lines for a specific date
    Shows which config is active (override or default)
    """
    lines = ProductionLine.objects.filter(id__in=line_ids, is_active=True)
    details = []
    
    for line in lines:
        config = line.get_config_for_date(for_date)
        if config:
            details.append({
                'line_id': line.id,
                'line_name': line.name,
                'site_name': line.site_name,
                'config_type': config['type'],
                'shifts_per_day': config['shifts_per_day'],
                'hours_per_shift': config['hours_per_shift'],
                'include_saturday': config['include_saturday'],
                'include_sunday': config['include_sunday'],
                'weekly_hours': config['weekly_hours'],
                'reason': config.get('reason'),
                'capacity_per_hour': float(line.base_capacity_per_hour),
                'efficiency': float(line.efficiency_factor),
                'weekly_capacity': line.get_weekly_capacity(for_date=for_date)
            })
    
    return details


def get_demand_for_lines(line_ids: list, week_start, week_end,
                         client_id: Optional[int] = None,
                         category_id: Optional[int] = None,
                         product_id: Optional[int] = None) -> dict:
    """
    Get demand forecast aggregated by week for products on specified lines
    
    Returns:
        Dict mapping week_start_date -> total_demand
    """
    # Get products assigned to these lines
    assignments = LineProductAssignment.objects.filter(
        line_id__in=line_ids
    ).values_list('product_id', flat=True)
    
    # Also get products with default_line in the selected lines
    default_products = Product.objects.filter(
        default_line_id__in=line_ids
    ).values_list('id', flat=True)
    
    product_ids = set(list(assignments) + list(default_products))
    
    # Build forecast query
    forecast_filter = Q(
        product_id__in=product_ids,
        week_start_date__gte=week_start,
        week_start_date__lte=week_end
    )
    
    if client_id:
        forecast_filter &= Q(client_id=client_id)
    
    if category_id:
        forecast_filter &= Q(product__category_id=category_id)
    
    if product_id:
        forecast_filter &= Q(product_id=product_id)
    
    # Aggregate demand by week
    forecasts = DemandForecast.objects.filter(forecast_filter).values(
        'week_start_date'
    ).annotate(
        total_demand=Sum('forecast_quantity')
    ).order_by('week_start_date')
    
    return {f['week_start_date']: f['total_demand'] for f in forecasts}


def get_demand_for_category(category_id: int, line_ids: list, 
                            week_start, week_end,
                            product_id: Optional[int] = None) -> dict:
    """
    Get demand forecast for a specific category on specified lines
    """
    # Get products in this category that can be produced on these lines
    category_products = Product.objects.filter(category_id=category_id)
    
    assignments = LineProductAssignment.objects.filter(
        line_id__in=line_ids,
        product__category_id=category_id
    ).values_list('product_id', flat=True)
    
    default_products = category_products.filter(
        default_line_id__in=line_ids
    ).values_list('id', flat=True)
    
    product_ids = set(list(assignments) + list(default_products))
    
    forecast_filter = Q(
        product_id__in=product_ids,
        week_start_date__gte=week_start,
        week_start_date__lte=week_end
    )
    
    if product_id:
        forecast_filter &= Q(product_id=product_id)
    
    forecasts = DemandForecast.objects.filter(forecast_filter).values(
        'week_start_date'
    ).annotate(
        total_demand=Sum('forecast_quantity')
    ).order_by('week_start_date')
    
    return {f['week_start_date']: f['total_demand'] for f in forecasts}


def get_client_demand(client_id: int, line_ids: list, week_start, week_end) -> dict:
    """Get demand for a specific client on specified lines"""
    assignments = LineProductAssignment.objects.filter(
        line_id__in=line_ids
    ).values_list('product_id', flat=True)
    
    default_products = Product.objects.filter(
        default_line_id__in=line_ids
    ).values_list('id', flat=True)
    
    product_ids = set(list(assignments) + list(default_products))
    
    forecasts = DemandForecast.objects.filter(
        client_id=client_id,
        product_id__in=product_ids,
        week_start_date__gte=week_start,
        week_start_date__lte=week_end
    ).values('week_start_date').annotate(
        total_demand=Sum('forecast_quantity')
    ).order_by('week_start_date')
    
    return {f['week_start_date']: f['total_demand'] for f in forecasts}


def run_line_simulation(line_ids: list, shift_configs: list,
                        start_date, end_date,
                        client_id: Optional[int] = None,
                        category_id: Optional[int] = None,
                        product_id: Optional[int] = None,
                        overlay_client_codes: list = None,
                        granularity: str = 'week') -> dict:
    """
    Run line simulation (Dashboard 1)
    Analyze demand vs capacity for selected lines
    Considers LineConfigOverrides for date-specific capacity
    Supports client demand overlays by code
    Supports both weekly and daily granularity
    """
    if overlay_client_codes is None:
        overlay_client_codes = []
    
    # Convert shift_configs to dict
    # When use_override is True, shift_config_id will be None to use date-based overrides
    config_dict = {}
    for sc in shift_configs:
        if sc.get('use_override', False):
            config_dict[sc['line_id']] = None  # Will trigger date-based override lookup
        else:
            config_dict[sc['line_id']] = sc.get('shift_config_id')
    
    # Get overlay data if filters are applied
    overlay_data = {}
    
    if client_id:
        client = Client.objects.filter(id=client_id).first()
        if client:
            overlay_data['client_name'] = client.name
    
    if product_id:
        product = Product.objects.filter(id=product_id).first()
        if product:
            overlay_data['product_name'] = f"{product.code} - {product.name}"
    
    if category_id:
        category = ProductCategory.objects.filter(id=category_id).first()
        if category:
            overlay_data['category_name'] = category.name
    
    # Process based on granularity
    if granularity == 'day':
        return _run_line_simulation_daily(
            line_ids, config_dict, start_date, end_date,
            client_id, category_id, product_id,
            overlay_client_codes, overlay_data
        )
    else:
        return _run_line_simulation_weekly(
            line_ids, config_dict, start_date, end_date,
            client_id, category_id, product_id,
            overlay_client_codes, overlay_data
        )


def _run_line_simulation_weekly(line_ids, config_dict, start_date, end_date,
                                 client_id, category_id, product_id,
                                 overlay_client_codes, overlay_data):
    """Weekly granularity simulation"""
    # Get weeks in range
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Calculate capacity per week (considers overrides)
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    # Get demand data
    demand_data = get_demand_for_lines(
        line_ids, start_date, end_date,
        client_id, category_id, product_id
    )
    
    # Get overlay demand if client filter is applied
    overlay_demand = {}
    if client_id:
        overlay_demand = get_client_demand(client_id, line_ids, start_date, end_date)
    
    # Get client overlay data by code
    client_overlays = {}
    for client_code in overlay_client_codes:
        client = Client.objects.filter(code__iexact=client_code).first()
        if client:
            client_demand = get_client_demand(client.id, line_ids, start_date, end_date)
            # Build data points for this client
            client_data_points = []
            for week_start in weeks:
                demand = client_demand.get(week_start, Decimal('0'))
                client_data_points.append({
                    'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
                    'week_start': week_start,
                    'demand': demand
                })
            client_overlays[client.code] = {
                'client_name': client.name,
                'client_id': client.id,
                'data_points': client_data_points,
                'total_demand': sum(dp['demand'] for dp in client_data_points)
            }
    
    # Build data points
    data_points = []
    total_demand = Decimal('0')
    total_capacity = Decimal('0')
    utilizations = []
    over_capacity_count = 0
    
    for week_start in weeks:
        demand = demand_data.get(week_start, Decimal('0'))
        weekly_capacity = capacity_by_week.get(week_start, Decimal('0'))
        
        total_demand += demand
        total_capacity += weekly_capacity
        
        if weekly_capacity > 0:
            utilization = (demand / weekly_capacity) * 100
        else:
            utilization = Decimal('0')
        
        utilizations.append(float(utilization))
        over_capacity = utilization > 100
        if over_capacity:
            over_capacity_count += 1
        
        # Get config details for this week to show override info
        week_date = week_start + timedelta(days=3)
        config_details = get_line_config_details(line_ids, week_date)
        has_override = any(c['config_type'] == 'override' for c in config_details)
        
        data_point = {
            'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
            'week_start': week_start,
            'demand': demand,
            'capacity': weekly_capacity,
            'utilization_percent': round(utilization, 1),
            'over_capacity': over_capacity,
            'has_override': has_override
        }
        
        if overlay_demand:
            data_point['overlay_demand'] = overlay_demand.get(week_start, Decimal('0'))
        
        data_points.append(data_point)
    
    # Calculate summary stats
    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    peak_utilization = max(utilizations) if utilizations else 0
    
    result = {
        'granularity': 'week',
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(peak_utilization, 1),
        'over_capacity_periods': over_capacity_count,
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'overlay_data': overlay_data if overlay_data else None
    }
    
    # Add client overlays if any
    if client_overlays:
        result['client_overlays'] = client_overlays
    
    return result


def _run_line_simulation_daily(line_ids, config_dict, start_date, end_date,
                                client_id, category_id, product_id,
                                overlay_client_codes, overlay_data):
    """Daily granularity simulation"""
    # Get days in range
    days = get_days_in_range(start_date, end_date)
    
    # Calculate capacity per day (considers overrides)
    capacity_by_day = calculate_capacity_per_day(line_ids, config_dict, days)
    
    # Get demand data (distributed daily)
    demand_data = get_demand_for_lines_daily(
        line_ids, start_date, end_date,
        client_id, category_id, product_id
    )
    
    # Get overlay demand if client filter is applied
    overlay_demand = {}
    if client_id:
        overlay_demand = get_client_demand_daily(client_id, line_ids, start_date, end_date)
    
    # Get client overlay data by code
    client_overlays = {}
    for client_code in overlay_client_codes:
        client = Client.objects.filter(code__iexact=client_code).first()
        if client:
            client_demand = get_client_demand_daily(client.id, line_ids, start_date, end_date)
            # Build data points for this client
            client_data_points = []
            for day in days:
                demand = client_demand.get(day, Decimal('0'))
                client_data_points.append({
                    'date': day.strftime('%Y-%m-%d'),
                    'day': day,
                    'demand': demand
                })
            client_overlays[client.code] = {
                'client_name': client.name,
                'client_id': client.id,
                'data_points': client_data_points,
                'total_demand': sum(dp['demand'] for dp in client_data_points)
            }
    
    # Build data points
    data_points = []
    total_demand = Decimal('0')
    total_capacity = Decimal('0')
    utilizations = []
    over_capacity_count = 0
    
    for day in days:
        demand = demand_data.get(day, Decimal('0'))
        daily_capacity = capacity_by_day.get(day, Decimal('0'))
        
        total_demand += demand
        total_capacity += daily_capacity
        
        if daily_capacity > 0:
            utilization = (demand / daily_capacity) * 100
        else:
            utilization = Decimal('0') if demand == 0 else Decimal('999')  # No capacity but has demand
        
        utilizations.append(float(utilization))
        over_capacity = utilization > 100
        if over_capacity:
            over_capacity_count += 1
        
        # Get config details for this day to show override info
        config_details = get_line_config_details(line_ids, day)
        has_override = any(c['config_type'] == 'override' for c in config_details)
        
        # Get day name for display
        day_name = day.strftime('%a')  # Mon, Tue, etc.
        
        data_point = {
            'date': day.strftime('%Y-%m-%d'),
            'date_display': f"{day_name} {day.strftime('%d/%m')}",
            'day': day,
            'demand': demand,
            'capacity': daily_capacity,
            'utilization_percent': round(utilization, 1) if utilization < 999 else 'N/A',
            'over_capacity': over_capacity,
            'has_override': has_override,
            'is_weekend': day.weekday() >= 5
        }
        
        if overlay_demand:
            data_point['overlay_demand'] = overlay_demand.get(day, Decimal('0'))
        
        data_points.append(data_point)
    
    # Calculate summary stats (exclude days with no capacity for avg)
    valid_utilizations = [u for u in utilizations if u < 999]
    avg_utilization = sum(valid_utilizations) / len(valid_utilizations) if valid_utilizations else 0
    peak_utilization = max(valid_utilizations) if valid_utilizations else 0
    
    result = {
        'granularity': 'day',
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(peak_utilization, 1),
        'over_capacity_periods': over_capacity_count,
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'overlay_data': overlay_data if overlay_data else None
    }
    
    # Add client overlays if any
    if client_overlays:
        result['client_overlays'] = client_overlays
    
    return result


def run_category_simulation(category_id: int, line_ids: list, shift_configs: list,
                            start_date, end_date,
                            product_id: Optional[int] = None) -> dict:
    """
    Run category simulation (Dashboard 2)
    Analyze demand for a product category vs capacity
    Considers LineConfigOverrides for date-specific capacity
    """
    # Convert shift_configs to dict - handle use_override flag
    config_dict = {}
    for sc in shift_configs:
        if sc.get('use_override', False):
            config_dict[sc['line_id']] = None
        else:
            config_dict[sc['line_id']] = sc.get('shift_config_id')
    
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Calculate capacity per week (considers overrides)
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    # Get category info
    category = ProductCategory.objects.filter(id=category_id).first()
    overlay_data = {'category_name': category.name if category else 'Unknown'}
    
    # Get demand for category
    demand_data = get_demand_for_category(
        category_id, line_ids, start_date, end_date, product_id
    )
    
    if product_id:
        product = Product.objects.filter(id=product_id).first()
        if product:
            overlay_data['product_name'] = f"{product.code} - {product.name}"
    
    # Build data points
    data_points = []
    total_demand = Decimal('0')
    total_capacity = Decimal('0')
    utilizations = []
    over_capacity_count = 0
    
    for week_start in weeks:
        demand = demand_data.get(week_start, Decimal('0'))
        weekly_capacity = capacity_by_week.get(week_start, Decimal('0'))
        
        total_demand += demand
        total_capacity += weekly_capacity
        
        if weekly_capacity > 0:
            utilization = (demand / weekly_capacity) * 100
        else:
            utilization = Decimal('0')
        
        utilizations.append(float(utilization))
        over_capacity = utilization > 100
        if over_capacity:
            over_capacity_count += 1
        
        # Check for overrides
        week_date = week_start + timedelta(days=3)
        config_details = get_line_config_details(line_ids, week_date)
        has_override = any(c['config_type'] == 'override' for c in config_details)
        
        data_points.append({
            'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
            'week_start': week_start,
            'demand': demand,
            'capacity': weekly_capacity,
            'utilization_percent': round(utilization, 1),
            'over_capacity': over_capacity,
            'has_override': has_override
        })
    
    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    peak_utilization = max(utilizations) if utilizations else 0
    
    return {
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(peak_utilization, 1),
        'over_capacity_periods': over_capacity_count,
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'overlay_data': overlay_data
    }


def run_new_client_simulation(line_ids: list, shift_configs: list,
                              start_date, end_date,
                              new_client_demand: Decimal,
                              remove_client_id: Optional[int] = None) -> dict:
    """
    Run new client simulation (Dashboard 3)
    Analyze impact of adding a new client and optionally removing an existing one
    Considers LineConfigOverrides for date-specific capacity
    """
    # Convert shift_configs to dict - handle use_override flag
    config_dict = {}
    for sc in shift_configs:
        if sc.get('use_override', False):
            config_dict[sc['line_id']] = None
        else:
            config_dict[sc['line_id']] = sc.get('shift_config_id')
    
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Calculate capacity per week (considers overrides)
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    # Get base demand (all current demand)
    base_demand_data = get_demand_for_lines(line_ids, start_date, end_date)
    
    # Get demand to remove if specified
    removed_demand_data = {}
    overlay_data = {'new_client_weekly_demand': float(new_client_demand)}
    
    if remove_client_id:
        removed_demand_data = get_client_demand(
            remove_client_id, line_ids, start_date, end_date
        )
        client = Client.objects.filter(id=remove_client_id).first()
        if client:
            overlay_data['removed_client_name'] = client.name
    
    # Build data points
    data_points = []
    total_demand = Decimal('0')
    total_capacity = Decimal('0')
    utilizations = []
    over_capacity_count = 0
    
    for week_start in weeks:
        base_demand = base_demand_data.get(week_start, Decimal('0'))
        removed_demand = removed_demand_data.get(week_start, Decimal('0'))
        weekly_capacity = capacity_by_week.get(week_start, Decimal('0'))
        
        # New demand = base + new client - removed client
        demand = base_demand + new_client_demand - removed_demand
        total_demand += demand
        total_capacity += weekly_capacity
        
        if weekly_capacity > 0:
            utilization = (demand / weekly_capacity) * 100
        else:
            utilization = Decimal('0')
        
        utilizations.append(float(utilization))
        over_capacity = utilization > 100
        if over_capacity:
            over_capacity_count += 1
        
        # Check for overrides
        week_date = week_start + timedelta(days=3)
        config_details = get_line_config_details(line_ids, week_date)
        has_override = any(c['config_type'] == 'override' for c in config_details)
        
        data_points.append({
            'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
            'week_start': week_start,
            'base_demand': base_demand,
            'new_client_demand': new_client_demand,
            'removed_demand': removed_demand,
            'demand': demand,
            'capacity': weekly_capacity,
            'utilization_percent': round(utilization, 1),
            'over_capacity': over_capacity,
            'has_override': has_override
        })
    
    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    peak_utilization = max(utilizations) if utilizations else 0
    
    return {
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(peak_utilization, 1),
        'over_capacity_periods': over_capacity_count,
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'overlay_data': overlay_data
    }


def run_lost_client_simulation(line_ids: list, shift_configs: list,
                               start_date, end_date,
                               lost_client_id: int) -> dict:
    """
    Run lost client simulation (Dashboard 4)
    Analyze how capacity changes if a client leaves
    Considers LineConfigOverrides for date-specific capacity
    """
    # Convert shift_configs to dict - handle use_override flag
    config_dict = {}
    for sc in shift_configs:
        if sc.get('use_override', False):
            config_dict[sc['line_id']] = None
        else:
            config_dict[sc['line_id']] = sc.get('shift_config_id')
    
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Calculate capacity per week (considers overrides)
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    # Get base demand (all current demand)
    base_demand_data = get_demand_for_lines(line_ids, start_date, end_date)
    
    # Get lost client demand
    lost_demand_data = get_client_demand(lost_client_id, line_ids, start_date, end_date)
    
    client = Client.objects.filter(id=lost_client_id).first()
    total_lost_demand = sum(lost_demand_data.values()) if lost_demand_data else Decimal('0')
    
    overlay_data = {
        'lost_client_name': client.name if client else 'Unknown',
        'total_lost_demand': float(total_lost_demand)
    }
    
    # Build data points
    data_points = []
    total_demand = Decimal('0')
    total_capacity = Decimal('0')
    utilizations = []
    original_utilizations = []
    
    for week_start in weeks:
        base_demand = base_demand_data.get(week_start, Decimal('0'))
        lost_demand = lost_demand_data.get(week_start, Decimal('0'))
        weekly_capacity = capacity_by_week.get(week_start, Decimal('0'))
        
        # New demand = base - lost client
        demand = base_demand - lost_demand
        total_demand += demand
        total_capacity += weekly_capacity
        
        if weekly_capacity > 0:
            utilization = (demand / weekly_capacity) * 100
            original_utilization = (base_demand / weekly_capacity) * 100
        else:
            utilization = Decimal('0')
            original_utilization = Decimal('0')
        
        utilizations.append(float(utilization))
        original_utilizations.append(float(original_utilization))
        
        # Check for overrides
        week_date = week_start + timedelta(days=3)
        config_details = get_line_config_details(line_ids, week_date)
        has_override = any(c['config_type'] == 'override' for c in config_details)
        
        data_points.append({
            'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
            'week_start': week_start,
            'base_demand': base_demand,
            'lost_demand': lost_demand,
            'demand': demand,
            'capacity': weekly_capacity,
            'utilization_percent': round(utilization, 1),
            'original_utilization_percent': round(original_utilization, 1),
            'over_capacity': utilization > 100,
            'has_override': has_override
        })
    
    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    avg_original = sum(original_utilizations) / len(original_utilizations) if original_utilizations else 0
    
    overlay_data['freed_capacity_percent'] = round(avg_original - avg_utilization, 1)
    
    return {
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(max(utilizations), 1) if utilizations else 0,
        'over_capacity_periods': sum(1 for dp in data_points if dp['over_capacity']),
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'overlay_data': overlay_data
    }
