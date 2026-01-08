"""
Simulation Services for Cerelia Production Planning
Core business logic for capacity and demand simulations
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, List, Set
from django.db.models import Sum, Q, Prefetch
from functools import lru_cache
from .models import (
    ProductionLine, ShiftConfiguration, Product, Client,
    DemandForecast, LineProductAssignment,
    LabLine, LabForecast, LabProduct, LineConfigOverride,
    LabClient, LabCategory
)


# Cache for frequently accessed data within a request
_line_cache = {}
_shift_config_cache = {}
_product_ids_cache = {}


def clear_caches():
    """Clear all service caches - call at the start of each request"""
    global _line_cache, _shift_config_cache, _product_ids_cache
    _line_cache = {}
    _shift_config_cache = {}
    _product_ids_cache = {}


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


def _get_lines_with_configs(line_ids: list, start_date=None, end_date=None) -> dict:
    """
    Batch load production lines with their configurations and overrides.
    Returns a dict mapping line_id -> line object with prefetched data.
    """
    cache_key = (tuple(sorted(line_ids)), start_date, end_date)
    if cache_key in _line_cache:
        return _line_cache[cache_key]
    
    # Build override filter if date range provided
    override_filter = Q(is_active=True)
    if start_date and end_date:
        override_filter &= Q(end_date__gte=start_date) & Q(start_date__lte=end_date)
    
    lines = ProductionLine.objects.filter(
        id__in=line_ids, 
        is_active=True
    ).select_related(
        'site',
        'default_shift_config'
    ).prefetch_related(
        Prefetch(
            'config_overrides',
            queryset=LineConfigOverride.objects.filter(override_filter).order_by('start_date'),
            to_attr='prefetched_overrides'
        )
    )
    
    result = {line.id: line for line in lines}
    _line_cache[cache_key] = result
    return result


def _get_shift_config(shift_config_id: int) -> Optional[ShiftConfiguration]:
    """Get shift config from cache or database"""
    if shift_config_id in _shift_config_cache:
        return _shift_config_cache[shift_config_id]
    
    try:
        config = ShiftConfiguration.objects.get(id=shift_config_id)
        _shift_config_cache[shift_config_id] = config
        return config
    except ShiftConfiguration.DoesNotExist:
        return None


def _get_config_for_date_from_prefetched(line, target_date, prefetched_overrides):
    """
    Get configuration for a date using prefetched overrides.
    Optimized version that doesn't hit the database.
    """
    from datetime import timedelta
    
    for override in prefetched_overrides:
        if override.start_date <= target_date <= override.end_date:
            # If it's a recurrent override, check if target_date falls on a valid recurrence week
            if override.is_recurrent and override.recurrence_weeks:
                days_since_start = (target_date - override.start_date).days
                weeks_since_start = days_since_start // 7
                if weeks_since_start % override.recurrence_weeks != 0:
                    continue
            
            return {
                'type': 'override',
                'override': override,
                'shifts_per_day': override.shifts_per_day,
                'hours_per_shift': float(override.hours_per_shift),
                'days_per_week': override.days_per_week,
                'include_saturday': override.include_saturday,
                'include_sunday': override.include_sunday,
                'weekly_hours': override.weekly_hours,
                'reason': override.reason
            }
    
    # No valid override found, use default
    if line.default_shift_config:
        return {
            'type': 'default',
            'override': None,
            'shifts_per_day': line.default_shift_config.shifts_per_day,
            'hours_per_shift': float(line.default_shift_config.hours_per_shift),
            'days_per_week': 5 + (1 if line.default_shift_config.includes_saturday else 0) + (1 if line.default_shift_config.includes_sunday else 0),
            'include_saturday': line.default_shift_config.includes_saturday,
            'include_sunday': line.default_shift_config.includes_sunday,
            'weekly_hours': line.default_shift_config.weekly_hours,
            'reason': None
        }
    return None


def _get_product_ids_for_lines(line_ids: list) -> Set[int]:
    """
    Get all product IDs that have the given lines as their DEFAULT production line.
    Only products with default_line set to one of the selected lines are included.
    Uses caching to avoid repeated queries.
    """
    cache_key = tuple(sorted(line_ids))
    if cache_key in _product_ids_cache:
        return _product_ids_cache[cache_key]
    
    # Only get products where the selected line is their DEFAULT line
    default_products = set(Product.objects.filter(
        default_line_id__in=line_ids,
        is_active=True
    ).values_list('id', flat=True))
    
    result = default_products
    _product_ids_cache[cache_key] = result
    return result


def calculate_daily_capacity(line_ids: list, shift_configs: dict, for_date, 
                             lines_dict: dict = None) -> Decimal:
    """
    Calculate total daily capacity for given lines with their shift configurations
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        for_date: Date to calculate capacity for
        lines_dict: Optional pre-loaded lines dictionary for batch processing
    
    Returns:
        Total daily capacity in units
    """
    total_capacity = Decimal('0')
    day_of_week = for_date.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
    
    # Use provided lines_dict or fetch if not provided
    if lines_dict is None:
        lines_dict = _get_lines_with_configs(line_ids, for_date, for_date)
    
    for line_id in line_ids:
        line = lines_dict.get(line_id)
        if not line:
            continue
            
        shift_config_id = shift_configs.get(line_id)
        
        # Get the configuration to use
        if shift_config_id:
            config = _get_shift_config(shift_config_id)
            if config:
                shifts_per_day = config.shifts_per_day
                hours_per_shift = config.hours_per_shift
                includes_saturday = config.includes_saturday
                includes_sunday = config.includes_sunday
            else:
                config_data = _get_config_for_date_from_prefetched(
                    line, for_date, getattr(line, 'prefetched_overrides', [])
                )
                if config_data:
                    shifts_per_day = config_data['shifts_per_day']
                    hours_per_shift = config_data['hours_per_shift']
                    includes_saturday = config_data['include_saturday']
                    includes_sunday = config_data['include_sunday']
                else:
                    continue
        else:
            config_data = _get_config_for_date_from_prefetched(
                line, for_date, getattr(line, 'prefetched_overrides', [])
            )
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
    Calculate capacity for each day, considering LineConfigOverrides.
    Optimized: Pre-loads all lines with configs once.
    """
    capacity_by_day = {}
    
    if not days:
        return capacity_by_day
    
    # Pre-load all lines with configs for the entire date range
    start_date = min(days)
    end_date = max(days)
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date)
    
    for day in days:
        capacity = calculate_daily_capacity(line_ids, shift_configs, for_date=day, lines_dict=lines_dict)
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


def calculate_weekly_capacity(line_ids: list, shift_configs: dict, for_date=None,
                               lines_dict: dict = None) -> Decimal:
    """
    Calculate total weekly capacity for given lines with their shift configurations
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        for_date: Optional date to check for LineConfigOverride entries
        lines_dict: Optional pre-loaded lines dictionary for batch processing
    
    Returns:
        Total weekly capacity in units
    """
    total_capacity = Decimal('0')
    
    # Use provided lines_dict or fetch if not provided
    if lines_dict is None:
        lines_dict = _get_lines_with_configs(line_ids, for_date, for_date)
    
    for line_id in line_ids:
        line = lines_dict.get(line_id)
        if not line:
            continue
        
        # First check if there's a UI-selected shift config override
        shift_config_id = shift_configs.get(line_id)
        
        if shift_config_id:
            # User explicitly selected a shift config in the simulation UI
            shift_config = _get_shift_config(shift_config_id)
            if shift_config:
                weekly_capacity = line.get_weekly_capacity(shift_config)
            else:
                weekly_capacity = line.get_weekly_capacity(for_date=for_date)
        else:
            # Use date-based override or default config
            weekly_capacity = line.get_weekly_capacity(for_date=for_date)
        
        total_capacity += Decimal(str(weekly_capacity))
    
    return total_capacity


def calculate_capacity_per_week(line_ids: list, shift_configs: dict, weeks: list) -> dict:
    """
    Calculate capacity for each week, considering LineConfigOverrides.
    Optimized: Pre-loads all lines with configs once.
    
    Args:
        line_ids: List of production line IDs
        shift_configs: Dict mapping line_id -> shift_config_id (manual override from UI)
        weeks: List of week start dates
    
    Returns:
        Dict mapping week_start_date -> total_capacity
    """
    capacity_by_week = {}
    
    if not weeks:
        return capacity_by_week
    
    # Pre-load all lines with configs for the entire date range
    start_date = min(weeks)
    end_date = max(weeks) + timedelta(days=6)  # Include the whole last week
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date)
    
    for week_start in weeks:
        # Use the middle of the week for override checking
        week_date = week_start + timedelta(days=3)
        capacity = calculate_weekly_capacity(line_ids, shift_configs, for_date=week_date, lines_dict=lines_dict)
        capacity_by_week[week_start] = capacity
    
    return capacity_by_week


def get_line_config_details(line_ids: list, for_date, lines_dict: dict = None) -> list:
    """
    Get configuration details for lines for a specific date
    Shows which config is active (override or default)
    Optimized: Uses pre-loaded lines if provided
    """
    if lines_dict is None:
        lines_dict = _get_lines_with_configs(line_ids, for_date, for_date)
    
    details = []
    
    for line_id in line_ids:
        line = lines_dict.get(line_id)
        if not line:
            continue
            
        config = _get_config_for_date_from_prefetched(
            line, for_date, getattr(line, 'prefetched_overrides', [])
        )
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
    Get demand forecast aggregated by week for products on specified lines.
    Optimized: Uses cached product IDs.
    
    Returns:
        Dict mapping week_start_date -> total_demand
    """
    # Get products assigned to these lines (cached)
    product_ids = _get_product_ids_for_lines(line_ids)
    
    if not product_ids:
        return {}
    
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
    Get demand forecast for a specific category on specified lines.
    Optimized: Uses cached product IDs and filters by category.
    """
    # Get all products for these lines
    all_product_ids = _get_product_ids_for_lines(line_ids)
    
    # Filter to only products in this category
    category_product_ids = set(Product.objects.filter(
        id__in=all_product_ids,
        category_id=category_id
    ).values_list('id', flat=True))
    
    if not category_product_ids:
        return {}
    
    forecast_filter = Q(
        product_id__in=category_product_ids,
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
    """Get demand for a specific client on specified lines. Optimized with caching."""
    product_ids = _get_product_ids_for_lines(line_ids)
    
    if not product_ids:
        return {}
    
    forecasts = DemandForecast.objects.filter(
        client_id=client_id,
        product_id__in=product_ids,
        week_start_date__gte=week_start,
        week_start_date__lte=week_end
    ).values('week_start_date').annotate(
        total_demand=Sum('forecast_quantity')
    ).order_by('week_start_date')
    
    return {f['week_start_date']: f['total_demand'] for f in forecasts}


def apply_demand_modifications_weekly(demand_data: dict, modifications: list, 
                                      line_ids: list, weeks: list) -> dict:
    """
    Apply demand modifications (percentage adjustments) to weekly demand data.
    Optimized: Uses cached product IDs.
    
    Args:
        demand_data: Dict mapping week_start -> demand value
        modifications: List of modification dicts with keys:
            - client_id: int
            - product_id: int (optional, if None applies to all client products)
            - start_date: date string (YYYY-MM-DD)
            - end_date: date string (YYYY-MM-DD)
            - percentage: float (-100 to +infinity, e.g., -50 means reduce by 50%, +20 means increase by 20%)
        line_ids: List of production line IDs to filter products
        weeks: List of week start dates
    
    Returns:
        Modified demand_data dict
    """
    if not modifications:
        return demand_data
    
    # Get products for the lines (cached)
    valid_product_ids = _get_product_ids_for_lines(line_ids)
    weeks_set = set(weeks)
    
    for mod in modifications:
        client_id = mod.get('client_id')
        product_id = mod.get('product_id')  # Can be None for all client products
        mod_start = mod.get('start_date')
        mod_end = mod.get('end_date')
        percentage = Decimal(str(mod.get('percentage', 0)))
        
        # Parse dates if they're strings
        if isinstance(mod_start, str):
            mod_start = datetime.strptime(mod_start, '%Y-%m-%d').date()
        if isinstance(mod_end, str):
            mod_end = datetime.strptime(mod_end, '%Y-%m-%d').date()
        
        # Calculate the modification factor (percentage/100)
        # e.g., -100% -> factor = -1 (remove all), +50% -> factor = 0.5 (add 50%)
        factor = percentage / Decimal('100')
        
        # Get affected forecasts for this client/product within the modification date range
        # First, find which weeks overlap with the modification period
        mod_start_week = get_week_start(mod_start)
        
        forecast_filter = Q(
            client_id=client_id,
            week_start_date__gte=mod_start_week,
            week_start_date__lte=mod_end
        )
        
        if product_id:
            forecast_filter &= Q(product_id=product_id)
        else:
            # Only products valid for these lines
            forecast_filter &= Q(product_id__in=valid_product_ids)
        
        affected_forecasts = DemandForecast.objects.filter(forecast_filter).values(
            'week_start_date'
        ).annotate(
            total_demand=Sum('forecast_quantity')
        )
        
        # Apply modification to demand_data
        for forecast in affected_forecasts:
            week_start = forecast['week_start_date']
            # Only process weeks that are in our simulation range
            if week_start in weeks_set:
                # Calculate modification amount
                modification_amount = forecast['total_demand'] * factor
                
                # Initialize the week if it doesn't exist in demand_data
                if week_start not in demand_data:
                    demand_data[week_start] = Decimal('0')
                
                demand_data[week_start] += modification_amount
                # Ensure demand doesn't go negative
                if demand_data[week_start] < 0:
                    demand_data[week_start] = Decimal('0')
    
    return demand_data


def apply_demand_modifications_daily(demand_data: dict, modifications: list,
                                     line_ids: list, days: list) -> dict:
    """
    Apply demand modifications (percentage adjustments) to daily demand data.
    Optimized: Uses cached product IDs.
    
    Args:
        demand_data: Dict mapping date -> demand value
        modifications: List of modification dicts (same format as weekly)
        line_ids: List of production line IDs to filter products
        days: List of dates
    
    Returns:
        Modified demand_data dict
    """
    if not modifications:
        return demand_data
    
    # Get products for the lines (cached)
    valid_product_ids = _get_product_ids_for_lines(line_ids)
    
    for mod in modifications:
        client_id = mod.get('client_id')
        product_id = mod.get('product_id')
        mod_start = mod.get('start_date')
        mod_end = mod.get('end_date')
        percentage = Decimal(str(mod.get('percentage', 0)))
        
        # Parse dates if they're strings
        if isinstance(mod_start, str):
            mod_start = datetime.strptime(mod_start, '%Y-%m-%d').date()
        if isinstance(mod_end, str):
            mod_end = datetime.strptime(mod_end, '%Y-%m-%d').date()
        
        factor = percentage / Decimal('100')
        
        # Get affected weekly forecasts
        forecast_filter = Q(
            client_id=client_id,
            week_start_date__gte=get_week_start(mod_start),
            week_start_date__lte=mod_end
        )
        
        if product_id:
            forecast_filter &= Q(product_id=product_id)
        else:
            forecast_filter &= Q(product_id__in=valid_product_ids)
        
        affected_forecasts = DemandForecast.objects.filter(forecast_filter).values(
            'week_start_date'
        ).annotate(
            total_demand=Sum('forecast_quantity')
        )
        
        # Distribute weekly modification to daily
        for forecast in affected_forecasts:
            week_start = forecast['week_start_date']
            weekly_modification = forecast['total_demand'] * factor
            daily_modification = weekly_modification / Decimal('5')  # Distribute to 5 working days
            
            # Apply to Mon-Fri of that week
            for day_offset in range(5):
                day = week_start + timedelta(days=day_offset)
                if mod_start <= day <= mod_end and day in demand_data:
                    demand_data[day] += daily_modification
                    if demand_data[day] < 0:
                        demand_data[day] = Decimal('0')
    
    return demand_data


def run_line_simulation(line_ids: list, shift_configs: list,
                        start_date, end_date,
                        client_codes: list = None,
                        category_id: Optional[int] = None,
                        product_code: str = None,
                        overlay_client_codes: list = None,
                        granularity: str = 'week',
                        demand_modifications: list = None) -> dict:
    """
    Run line simulation (Dashboard 1)
    Analyze demand vs capacity for selected lines
    Considers LineConfigOverrides for date-specific capacity
    Supports client demand overlays by code
    Supports both weekly and daily granularity
    Supports demand modifications (percentage adjustments per client/product)
    """
    if overlay_client_codes is None:
        overlay_client_codes = []
    if demand_modifications is None:
        demand_modifications = []

    # Resolve product_id from product_code if provided
    product_id = None
    if product_code:
        product = Product.objects.filter(code__iexact=product_code).first()
        if product:
            product_id = product.id

    # Resolve client_ids from client_codes if provided
    client_ids = []
    if client_codes:
        for code in client_codes:
            client = Client.objects.filter(code__iexact=code).first()
            if client:
                client_ids.append(client.id)

    # If multiple client_ids, combine their demand
    client_id = None
    combine_clients = False
    if client_ids:
        if len(client_ids) == 1:
            client_id = client_ids[0]
        else:
            combine_clients = True

    # If combining clients, demand aggregation will be handled below
    
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

    if client_ids:
        overlay_data['client_codes'] = client_codes
    if product_code:
        overlay_data['product_code'] = product_code
    if demand_modifications:
        overlay_data['demand_modifications'] = demand_modifications
    
    # Process based on granularity
    if granularity == 'day':
        return _run_line_simulation_daily(
            line_ids, config_dict, start_date, end_date,
            client_id, category_id, product_id,
            overlay_client_codes, overlay_data,
            combine_clients=combine_clients, client_ids=client_ids,
            demand_modifications=demand_modifications
        )
    else:
        return _run_line_simulation_weekly(
            line_ids, config_dict, start_date, end_date,
            client_id, category_id, product_id,
            overlay_client_codes, overlay_data,
            combine_clients=combine_clients, client_ids=client_ids,
            demand_modifications=demand_modifications
        )


def _run_line_simulation_weekly(line_ids, config_dict, start_date, end_date,
                                 client_id, category_id, product_id,
                                 overlay_client_codes, overlay_data,
                                 combine_clients=False, client_ids=None,
                                 demand_modifications=None):
    """Weekly granularity simulation. Optimized with batch loading."""
    # Get weeks in range
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Pre-load all lines with configs for the entire date range
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date + timedelta(days=6))
    
    # Calculate capacity per week (considers overrides)
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    # Get demand data
    if combine_clients and client_ids:
        # Sum demand for all client_ids
        demand_data = {}
        for cid in client_ids:
            client_demand = get_demand_for_lines(
                line_ids, start_date, end_date, cid, category_id, product_id
            )
            for week, val in client_demand.items():
                demand_data[week] = demand_data.get(week, Decimal('0')) + val
    else:
        demand_data = get_demand_for_lines(
            line_ids, start_date, end_date,
            client_id, category_id, product_id
        )
    
    # Apply demand modifications if any
    if demand_modifications:
        demand_data = apply_demand_modifications_weekly(
            demand_data, demand_modifications, line_ids, weeks
        )
    
    # Get overlay demand if client filter is applied
    overlay_demand = {}
    if client_id:
        overlay_demand = get_client_demand(client_id, line_ids, start_date, end_date)
    
    # Pre-fetch all overlay clients in one query
    client_overlays = {}
    if overlay_client_codes:
        # Use code__in for matching (case-sensitive, but codes should match)
        upper_codes = [code.upper() for code in overlay_client_codes]
        overlay_clients = Client.objects.filter(code__in=overlay_client_codes)
        # Fallback: fetch all and filter in Python for case-insensitive match
        if not overlay_clients.exists():
            all_clients = Client.objects.filter(is_active=True)
            overlay_clients = [c for c in all_clients if c.code.upper() in upper_codes]
        overlay_client_map = {c.code.upper(): c for c in overlay_clients}
        
        for client_code in overlay_client_codes:
            client = overlay_client_map.get(client_code.upper())
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
    
    # Build data points - calculate override status once per week using pre-loaded data
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
        
        # Check for overrides using pre-loaded data
        week_date = week_start + timedelta(days=3)
        has_override = False
        for line_id in line_ids:
            line = lines_dict.get(line_id)
            if line:
                config = _get_config_for_date_from_prefetched(
                    line, week_date, getattr(line, 'prefetched_overrides', [])
                )
                if config and config['type'] == 'override':
                    has_override = True
                    break
        
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
                                overlay_client_codes, overlay_data,
                                combine_clients=False, client_ids=None,
                                demand_modifications=None):
    """Daily granularity simulation. Optimized with batch loading."""
    # Get days in range
    days = get_days_in_range(start_date, end_date)
    
    # Pre-load all lines with configs for the entire date range
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date)
    
    # Calculate capacity per day (considers overrides)
    capacity_by_day = calculate_capacity_per_day(line_ids, config_dict, days)
    
    # Get demand data (distributed daily)
    if combine_clients and client_ids:
        demand_data = {}
        for cid in client_ids:
            client_demand = get_demand_for_lines_daily(
                line_ids, start_date, end_date, cid, category_id, product_id
            )
            for day, val in client_demand.items():
                demand_data[day] = demand_data.get(day, Decimal('0')) + val
    else:
        demand_data = get_demand_for_lines_daily(
            line_ids, start_date, end_date,
            client_id, category_id, product_id
        )
    
    # Apply demand modifications if any
    if demand_modifications:
        demand_data = apply_demand_modifications_daily(
            demand_data, demand_modifications, line_ids, days
        )
    
    # Get overlay demand if client filter is applied
    overlay_demand = {}
    if client_id:
        overlay_demand = get_client_demand_daily(client_id, line_ids, start_date, end_date)
    
    # Pre-fetch all overlay clients in one query
    client_overlays = {}
    if overlay_client_codes:
        # Use code__in with uppercase codes for case-insensitive matching
        upper_codes = [code.upper() for code in overlay_client_codes]
        overlay_clients = Client.objects.filter(code__in=overlay_client_codes)
        # Fallback: fetch all and filter in Python for case-insensitive match
        if not overlay_clients.exists():
            all_clients = Client.objects.filter(is_active=True)
            overlay_clients = [c for c in all_clients if c.code.upper() in upper_codes]
        overlay_client_map = {c.code.upper(): c for c in overlay_clients}
        
        for client_code in overlay_client_codes:
            client = overlay_client_map.get(client_code.upper())
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
        
        # Check for overrides using pre-loaded data
        has_override = False
        for line_id in line_ids:
            line = lines_dict.get(line_id)
            if line:
                config = _get_config_for_date_from_prefetched(
                    line, day, getattr(line, 'prefetched_overrides', [])
                )
                if config and config['type'] == 'override':
                    has_override = True
                    break
        
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


# =============================================================================
# LAB SIMULATION FUNCTIONS
# =============================================================================

def calculate_lab_line_weekly_capacity(lab_line, for_date=None) -> Decimal:
    """
    Calculate weekly capacity for a Lab Line
    
    Args:
        lab_line: LabLine instance
        for_date: Optional date (not used for lab lines - they have fixed config)
    
    Returns:
        Weekly capacity in units
    """
    # Calculate working days per week
    working_days = 5  # Mon-Fri
    if lab_line.include_saturday:
        working_days += 1
    if lab_line.include_sunday:
        working_days += 1
    
    # Calculate daily hours
    daily_hours = lab_line.shifts_per_day * lab_line.hours_per_shift
    
    # Calculate weekly capacity
    weekly_hours = daily_hours * working_days
    weekly_capacity = (
        Decimal(str(lab_line.base_capacity_per_hour)) * 
        Decimal(str(weekly_hours)) * 
        Decimal(str(lab_line.efficiency_factor))
    )
    
    return weekly_capacity


def calculate_lab_line_daily_capacity(lab_line, for_date) -> Decimal:
    """
    Calculate daily capacity for a Lab Line
    
    Args:
        lab_line: LabLine instance
        for_date: Date to calculate capacity for
    
    Returns:
        Daily capacity in units
    """
    day_of_week = for_date.weekday()  # 0=Monday, 5=Saturday, 6=Sunday
    
    # Check if this day is a working day
    is_working_day = True
    if day_of_week == 5 and not lab_line.include_saturday:  # Saturday
        is_working_day = False
    elif day_of_week == 6 and not lab_line.include_sunday:  # Sunday
        is_working_day = False
    
    if not is_working_day:
        return Decimal('0')
    
    daily_hours = lab_line.shifts_per_day * lab_line.hours_per_shift
    daily_capacity = (
        Decimal(str(lab_line.base_capacity_per_hour)) * 
        Decimal(str(daily_hours)) * 
        Decimal(str(lab_line.efficiency_factor))
    )
    
    return daily_capacity


def get_lab_forecasts_demand_weekly(lab_line_ids: list, start_date, end_date,
                                     lab_client_id: Optional[int] = None,
                                     lab_product_id: Optional[int] = None,
                                     lab_category_id: Optional[int] = None) -> dict:
    """
    Get weekly demand from Lab Forecasts that target lab lines
    Distributes annual demand using seasonality from reference product
    
    Args:
        lab_line_ids: List of LabLine IDs
        start_date: Simulation start date
        end_date: Simulation end date
        lab_client_id: Optional Lab Client ID to filter by
        lab_product_id: Optional Lab Product ID to filter by
        lab_category_id: Optional Lab Category ID to filter by
    
    Returns:
        Dict mapping week_start_date -> total_demand
    """
    from django.db.models import Q
    
    # Build filter for lab forecasts
    forecast_filter = Q(
        lab_product__lab_default_line_id__in=lab_line_ids,
        start_date__lte=end_date,
        end_date__gte=start_date
    )
    
    # Apply lab client filter
    if lab_client_id:
        forecast_filter &= Q(lab_client_id=lab_client_id)
    
    # Apply lab product filter
    if lab_product_id:
        forecast_filter &= Q(lab_product_id=lab_product_id)
    
    # Apply lab category filter
    if lab_category_id:
        forecast_filter &= Q(lab_product__lab_category_id=lab_category_id)
    
    lab_forecasts = LabForecast.objects.filter(forecast_filter).select_related('lab_product', 'reference_product')
    
    weekly_demand = {}
    weeks = get_weeks_in_range(start_date, end_date)
    
    for week_start in weeks:
        weekly_demand[week_start] = Decimal('0')
    
    for lab_forecast in lab_forecasts:
        # Get reference product for seasonality
        reference_product = lab_forecast.reference_product
        
        if reference_product:
            # Get seasonality pattern from real forecasts of reference product
            ref_forecasts = DemandForecast.objects.filter(
                product=reference_product
            ).values('week_start_date').annotate(
                total=Sum('forecast_quantity')
            )
            
            # Calculate yearly total for reference product to get proportions
            yearly_totals = {}
            for rf in ref_forecasts:
                year = rf['week_start_date'].year
                if year not in yearly_totals:
                    yearly_totals[year] = Decimal('0')
                yearly_totals[year] += rf['total']
            
            # Get weekly proportions
            weekly_proportions = {}
            for rf in ref_forecasts:
                week = rf['week_start_date']
                year = week.year
                if yearly_totals.get(year, Decimal('0')) > 0:
                    weekly_proportions[(week.isocalendar()[1], year)] = (
                        rf['total'] / yearly_totals[year]
                    )
            
            # Distribute lab forecast's annual demand based on seasonality
            for week_start in weeks:
                if lab_forecast.start_date <= week_start <= lab_forecast.end_date:
                    week_num = week_start.isocalendar()[1]
                    year = week_start.year
                    
                    # Look for proportion from reference product
                    proportion = weekly_proportions.get((week_num, year))
                    
                    if proportion is None:
                        # Try previous year's same week
                        for past_year in range(year - 1, year - 5, -1):
                            proportion = weekly_proportions.get((week_num, past_year))
                            if proportion is not None:
                                break
                    
                    if proportion is None:
                        # Default to equal distribution (52 weeks)
                        proportion = Decimal('1') / Decimal('52')
                    
                    weekly_amount = Decimal(str(lab_forecast.annual_demand)) * proportion
                    weekly_demand[week_start] += weekly_amount
        else:
            # No reference product - distribute evenly across weeks
            forecast_weeks = get_weeks_in_range(
                max(lab_forecast.start_date, start_date),
                min(lab_forecast.end_date, end_date)
            )
            
            if forecast_weeks:
                weeks_count = len(forecast_weeks)
                weekly_amount = Decimal(str(lab_forecast.annual_demand)) / Decimal('52')
                
                for week_start in forecast_weeks:
                    if week_start in weekly_demand:
                        weekly_demand[week_start] += weekly_amount
    
    return weekly_demand


def run_lab_simulation(line_ids: list, lab_line_ids: list,
                       start_date, end_date,
                       include_lab_forecasts: bool = True,
                       client_codes: list = None,
                       product_code: str = None,
                       category_id: Optional[int] = None,
                       lab_client_id: Optional[int] = None,
                       lab_product_code: str = None,
                       lab_category_id: Optional[int] = None,
                       overlay_client_codes: list = None,
                       demand_modifications: list = None) -> dict:
    """
    Run Lab Simulation - combines real and lab (fictive) data
    
    Args:
        line_ids: List of real ProductionLine IDs
        lab_line_ids: List of LabLine IDs
        start_date: Simulation start date
        end_date: Simulation end date
        include_lab_forecasts: Whether to include Lab Forecasts in demand
        client_codes: Optional list of client codes to filter real data
        product_code: Optional product code to filter real data
        category_id: Optional category ID to filter real data
        lab_client_id: Optional Lab Client ID to filter lab data
        lab_product_code: Optional Lab Product code to filter lab data
        lab_category_id: Optional Lab Category ID to filter lab data
        overlay_client_codes: Optional list of client codes for demand overlays
        demand_modifications: Optional list of demand modifications
    
    Returns:
        Simulation results with combined capacity and demand
    """
    if overlay_client_codes is None:
        overlay_client_codes = []
    if demand_modifications is None:
        demand_modifications = []
    
    weeks = get_weeks_in_range(start_date, end_date)
    
    # Resolve product_id from product_code if provided
    product_id = None
    if product_code:
        product = Product.objects.filter(code__iexact=product_code).first()
        if product:
            product_id = product.id
    
    # Resolve lab_product_id from lab_product_code if provided
    lab_product_id = None
    if lab_product_code:
        lab_product = LabProduct.objects.filter(code__iexact=lab_product_code).first()
        if lab_product:
            lab_product_id = lab_product.id
    
    # Resolve client_ids from client_codes if provided
    client_ids = []
    if client_codes:
        for code in client_codes:
            client = Client.objects.filter(code__iexact=code).first()
            if client:
                client_ids.append(client.id)
    
    # If multiple client_ids, combine their demand
    client_id = None
    combine_clients = False
    if client_ids:
        if len(client_ids) == 1:
            client_id = client_ids[0]
        else:
            combine_clients = True
    
    # Calculate capacity from real lines (using default config)
    real_capacity_by_week = {}
    if line_ids:
        real_capacity_by_week = calculate_capacity_per_week(line_ids, {}, weeks)
    
    # Calculate capacity from lab lines
    lab_capacity_by_week = {}
    lab_lines = LabLine.objects.filter(id__in=lab_line_ids)
    for week_start in weeks:
        lab_capacity_by_week[week_start] = Decimal('0')
        for lab_line in lab_lines:
            lab_capacity_by_week[week_start] += calculate_lab_line_weekly_capacity(lab_line)
    
    # Get real demand (with filters)
    real_demand_by_week = {}
    if line_ids:
        if combine_clients and client_ids:
            # Sum demand for all client_ids
            for cid in client_ids:
                client_demand = get_demand_for_lines(
                    line_ids, start_date, end_date, cid, category_id, product_id
                )
                for week, val in client_demand.items():
                    real_demand_by_week[week] = real_demand_by_week.get(week, Decimal('0')) + val
        else:
            real_demand_by_week = get_demand_for_lines(
                line_ids, start_date, end_date, client_id, category_id, product_id
            )
    
    # Get lab demand (from lab forecasts) with lab filters
    lab_demand_by_week = {}
    if include_lab_forecasts and lab_line_ids:
        lab_demand_by_week = get_lab_forecasts_demand_weekly(
            lab_line_ids, start_date, end_date,
            lab_client_id=lab_client_id,
            lab_product_id=lab_product_id,
            lab_category_id=lab_category_id
        )
    
    # Get overlay data if filters are applied
    overlay_data = {}
    if client_codes:
        overlay_data['client_codes'] = client_codes
    if product_code:
        overlay_data['product_code'] = product_code
    # Add lab filters to overlay data
    if lab_client_id:
        lab_client = LabClient.objects.filter(id=lab_client_id).first()
        if lab_client:
            overlay_data['lab_client_name'] = lab_client.name
    if lab_product_code:
        overlay_data['lab_product_code'] = lab_product_code
    if lab_category_id:
        lab_category = LabCategory.objects.filter(id=lab_category_id).first()
        if lab_category:
            overlay_data['lab_category_name'] = lab_category.name
    
    # Get client overlay data by code
    client_overlays = {}
    for client_code in overlay_client_codes:
        client = Client.objects.filter(code__iexact=client_code).first()
        if client and line_ids:
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
        # Combine capacities
        real_cap = real_capacity_by_week.get(week_start, Decimal('0'))
        lab_cap = lab_capacity_by_week.get(week_start, Decimal('0'))
        weekly_capacity = real_cap + lab_cap
        
        # Combine demands
        real_dem = real_demand_by_week.get(week_start, Decimal('0'))
        lab_dem = lab_demand_by_week.get(week_start, Decimal('0'))
        demand = real_dem + lab_dem
        
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
        
        data_points.append({
            'date': f"W{week_start.isocalendar()[1]}/{week_start.year}",
            'week_start': week_start,
            'real_demand': real_dem,
            'lab_demand': lab_dem,
            'demand': demand,
            'real_capacity': real_cap,
            'lab_capacity': lab_cap,
            'capacity': weekly_capacity,
            'utilization_percent': round(utilization, 1),
            'over_capacity': over_capacity
        })
    
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
        'real_lines_count': len(line_ids) if line_ids else 0,
        'lab_lines_count': len(lab_line_ids) if lab_line_ids else 0,
        'include_lab_forecasts': include_lab_forecasts,
        'overlay_data': overlay_data if overlay_data else None
    }
    
    # Add client overlays if any
    if client_overlays:
        result['client_overlays'] = client_overlays
    
    return result


def run_category_simulation(simulation_category_id: int, shift_configs: list,
                             start_date, end_date,
                             client_codes: list = None,
                             product_code: str = None,
                             overlay_client_codes: list = None,
                             granularity: str = 'week',
                             demand_modifications: list = None) -> dict:
    """
    Run simulation using a SimulationCategory (new workflow).
    The category defines which lines and product filters to use.
    
    Args:
        simulation_category_id: ID of the SimulationCategory to use
        shift_configs: List of shift config overrides per line
        start_date: Start date for simulation
        end_date: End date for simulation
        client_codes: Optional filter by client codes (must be in category's scope)
        product_code: Optional filter by product code (must match category's product filters)
        overlay_client_codes: Client codes for overlay curves
        granularity: 'week' or 'day'
        demand_modifications: List of demand adjustments
    
    Returns:
        Simulation result dictionary
    """
    from .models import SimulationCategory
    
    # Get the simulation category
    try:
        category = SimulationCategory.objects.prefetch_related('lines', 'site').get(id=simulation_category_id)
    except SimulationCategory.DoesNotExist:
        return {'error': f'Simulation category {simulation_category_id} not found'}
    
    # Get line IDs from the category
    line_ids = list(category.lines.values_list('id', flat=True))
    if not line_ids:
        return {'error': 'No lines defined in the simulation category'}
    
    # Get matching products for the category
    matching_products = category.get_matching_products()
    matching_product_ids = set(matching_products.values_list('id', flat=True))
    
    if not matching_product_ids:
        return {'error': 'No products match the category filters'}
    
    # Resolve product_id from product_code if provided (must be in matching products)
    product_id = None
    if product_code:
        product = Product.objects.filter(
            code__iexact=product_code,
            id__in=matching_product_ids
        ).first()
        if product:
            product_id = product.id
        else:
            return {'error': f'Product {product_code} not found or not in category scope'}
    
    # Resolve client_ids from client_codes if provided
    client_ids = []
    if client_codes:
        for code in client_codes:
            client = Client.objects.filter(code__iexact=code).first()
            if client:
                client_ids.append(client.id)
    
    client_id = None
    combine_clients = False
    if client_ids:
        if len(client_ids) == 1:
            client_id = client_ids[0]
        else:
            combine_clients = True
    
    # Convert shift_configs to dict
    config_dict = {}
    for sc in shift_configs:
        if sc.get('use_override', False):
            config_dict[sc['line_id']] = None
        else:
            config_dict[sc['line_id']] = sc.get('shift_config_id')
    
    # Build overlay data
    overlay_data = {
        'simulation_category_name': category.name,
        'simulation_category_id': category.id,
    }
    if client_codes:
        overlay_data['client_codes'] = client_codes
    if product_code:
        overlay_data['product_code'] = product_code
    if demand_modifications:
        overlay_data['demand_modifications'] = demand_modifications
    
    # Call the appropriate granularity function
    if granularity == 'day':
        return _run_category_simulation_daily(
            line_ids, config_dict, start_date, end_date,
            matching_product_ids, client_id, product_id,
            overlay_client_codes or [], overlay_data,
            combine_clients=combine_clients, client_ids=client_ids,
            demand_modifications=demand_modifications or []
        )
    else:
        return _run_category_simulation_weekly(
            line_ids, config_dict, start_date, end_date,
            matching_product_ids, client_id, product_id,
            overlay_client_codes or [], overlay_data,
            combine_clients=combine_clients, client_ids=client_ids,
            demand_modifications=demand_modifications or []
        )


def _get_demand_for_products(product_ids: set, week_start, week_end,
                              client_id: Optional[int] = None) -> dict:
    """
    Get demand forecast for specific product IDs.
    """
    forecast_filter = Q(
        product_id__in=product_ids,
        week_start_date__gte=week_start,
        week_start_date__lte=week_end
    )
    
    if client_id:
        forecast_filter &= Q(client_id=client_id)
    
    forecasts = DemandForecast.objects.filter(forecast_filter).values(
        'week_start_date'
    ).annotate(
        total_demand=Sum('forecast_quantity')
    ).order_by('week_start_date')
    
    return {f['week_start_date']: f['total_demand'] for f in forecasts}


def _run_category_simulation_weekly(line_ids, config_dict, start_date, end_date,
                                     matching_product_ids, client_id, product_id,
                                     overlay_client_codes, overlay_data,
                                     combine_clients=False, client_ids=None,
                                     demand_modifications=None):
    """Weekly granularity simulation for category-based workflow."""
    weeks = get_weeks_in_range(start_date, end_date)
    
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date + timedelta(days=6))
    capacity_by_week = calculate_capacity_per_week(line_ids, config_dict, weeks)
    
    query_product_ids = matching_product_ids
    if product_id:
        query_product_ids = {product_id}
    
    # Get demand data
    if combine_clients and client_ids:
        demand_data = {}
        for cid in client_ids:
            client_demand = _get_demand_for_products(query_product_ids, start_date, end_date, cid)
            for week, val in client_demand.items():
                demand_data[week] = demand_data.get(week, Decimal('0')) + val
    else:
        demand_data = _get_demand_for_products(query_product_ids, start_date, end_date, client_id)
    
    # Apply demand modifications
    if demand_modifications:
        demand_data = _apply_category_demand_modifications(
            demand_data, demand_modifications, query_product_ids, weeks
        )
    
    # Get overlay demand
    overlay_demand = {}
    if client_id:
        overlay_demand = _get_demand_for_products(query_product_ids, start_date, end_date, client_id)
    
    # Process client overlays
    client_overlays = {}
    if overlay_client_codes:
        overlay_clients = Client.objects.filter(code__in=overlay_client_codes)
        for client in overlay_clients:
            client_demand = _get_demand_for_products(query_product_ids, start_date, end_date, client.id)
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
        
        week_date = week_start + timedelta(days=3)
        has_override = False
        for line_id in line_ids:
            line = lines_dict.get(line_id)
            if line:
                config = _get_config_for_date_from_prefetched(
                    line, week_date, getattr(line, 'prefetched_overrides', [])
                )
                if config and config['type'] == 'override':
                    has_override = True
                    break
        
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
        'line_count': len(line_ids),
        'product_count': len(matching_product_ids),
        'overlay_data': overlay_data if overlay_data else None
    }
    
    if client_overlays:
        result['client_overlays'] = client_overlays
    
    return result


def _run_category_simulation_daily(line_ids, config_dict, start_date, end_date,
                                    matching_product_ids, client_id, product_id,
                                    overlay_client_codes, overlay_data,
                                    combine_clients=False, client_ids=None,
                                    demand_modifications=None):
    """Daily granularity simulation for category-based workflow."""
    days = get_days_in_range(start_date, end_date)
    
    lines_dict = _get_lines_with_configs(line_ids, start_date, end_date)
    capacity_by_day = calculate_capacity_per_day(line_ids, config_dict, days)
    
    query_product_ids = matching_product_ids
    if product_id:
        query_product_ids = {product_id}
    
    if combine_clients and client_ids:
        weekly_demand_data = {}
        for cid in client_ids:
            client_demand = _get_demand_for_products(query_product_ids, start_date, end_date, cid)
            for week, val in client_demand.items():
                weekly_demand_data[week] = weekly_demand_data.get(week, Decimal('0')) + val
    else:
        weekly_demand_data = _get_demand_for_products(query_product_ids, start_date, end_date, client_id)
    
    demand_data = {}
    for week_start, total_weekly in weekly_demand_data.items():
        for day_offset in range(5):
            day = week_start + timedelta(days=day_offset)
            if start_date <= day <= end_date:
                demand_data[day] = total_weekly / Decimal('5')
    
    if demand_modifications:
        demand_data = _apply_category_demand_modifications_daily(
            demand_data, demand_modifications, query_product_ids, days
        )
    
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
            utilization = Decimal('0')
        
        utilizations.append(float(utilization))
        over_capacity = utilization > 100
        if over_capacity:
            over_capacity_count += 1
        
        has_override = False
        for line_id in line_ids:
            line = lines_dict.get(line_id)
            if line:
                config = _get_config_for_date_from_prefetched(
                    line, day, getattr(line, 'prefetched_overrides', [])
                )
                if config and config['type'] == 'override':
                    has_override = True
                    break
        
        data_points.append({
            'date': day.strftime('%Y-%m-%d'),
            'day_date': day,
            'demand': demand,
            'capacity': daily_capacity,
            'utilization_percent': round(utilization, 1),
            'over_capacity': over_capacity,
            'has_override': has_override,
            'day_name': day.strftime('%A')
        })
    
    avg_utilization = sum(utilizations) / len(utilizations) if utilizations else 0
    peak_utilization = max(utilizations) if utilizations else 0
    
    return {
        'granularity': 'day',
        'average_utilization': round(avg_utilization, 1),
        'peak_utilization': round(peak_utilization, 1),
        'over_capacity_periods': over_capacity_count,
        'total_capacity': total_capacity,
        'total_demand': total_demand,
        'data_points': data_points,
        'line_count': len(line_ids),
        'product_count': len(matching_product_ids),
        'overlay_data': overlay_data if overlay_data else None
    }


def _apply_category_demand_modifications(demand_data: dict, modifications: list,
                                          product_ids: set, weeks: list) -> dict:
    """Apply demand modifications for category simulation (weekly)."""
    if not modifications:
        return demand_data
    
    weeks_set = set(weeks)
    
    for mod in modifications:
        client_id = mod.get('client_id')
        product_id = mod.get('product_id')
        mod_start = mod.get('start_date')
        mod_end = mod.get('end_date')
        percentage = Decimal(str(mod.get('percentage', 0)))
        
        if isinstance(mod_start, str):
            mod_start = datetime.strptime(mod_start, '%Y-%m-%d').date()
        if isinstance(mod_end, str):
            mod_end = datetime.strptime(mod_end, '%Y-%m-%d').date()
        
        factor = percentage / Decimal('100')
        mod_start_week = get_week_start(mod_start)
        
        forecast_filter = Q(
            client_id=client_id,
            week_start_date__gte=mod_start_week,
            week_start_date__lte=mod_end
        )
        
        if product_id:
            forecast_filter &= Q(product_id=product_id)
        else:
            forecast_filter &= Q(product_id__in=product_ids)
        
        affected_forecasts = DemandForecast.objects.filter(forecast_filter).values(
            'week_start_date'
        ).annotate(
            total_demand=Sum('forecast_quantity')
        )
        
        for forecast in affected_forecasts:
            week_start = forecast['week_start_date']
            if week_start in weeks_set:
                modification_amount = forecast['total_demand'] * factor
                if week_start not in demand_data:
                    demand_data[week_start] = Decimal('0')
                demand_data[week_start] += modification_amount
                if demand_data[week_start] < 0:
                    demand_data[week_start] = Decimal('0')
    
    return demand_data


def _apply_category_demand_modifications_daily(demand_data: dict, modifications: list,
                                                product_ids: set, days: list) -> dict:
    """Apply demand modifications for category simulation (daily)."""
    if not modifications:
        return demand_data
    
    for mod in modifications:
        client_id = mod.get('client_id')
        product_id = mod.get('product_id')
        mod_start = mod.get('start_date')
        mod_end = mod.get('end_date')
        percentage = Decimal(str(mod.get('percentage', 0)))
        
        if isinstance(mod_start, str):
            mod_start = datetime.strptime(mod_start, '%Y-%m-%d').date()
        if isinstance(mod_end, str):
            mod_end = datetime.strptime(mod_end, '%Y-%m-%d').date()
        
        factor = percentage / Decimal('100')
        
        forecast_filter = Q(
            client_id=client_id,
            week_start_date__gte=get_week_start(mod_start),
            week_start_date__lte=mod_end
        )
        
        if product_id:
            forecast_filter &= Q(product_id=product_id)
        else:
            forecast_filter &= Q(product_id__in=product_ids)
        
        affected_forecasts = DemandForecast.objects.filter(forecast_filter).values(
            'week_start_date'
        ).annotate(
            total_demand=Sum('forecast_quantity')
        )
        
        for forecast in affected_forecasts:
            week_start = forecast['week_start_date']
            weekly_modification = forecast['total_demand'] * factor
            daily_modification = weekly_modification / Decimal('5')
            
            for day_offset in range(5):
                day = week_start + timedelta(days=day_offset)
                if mod_start <= day <= mod_end and day in demand_data:
                    demand_data[day] += daily_modification
                    if demand_data[day] < 0:
                        demand_data[day] = Decimal('0')
    
    return demand_data
