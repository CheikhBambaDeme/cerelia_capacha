"""
Cerelia Simulation Models
Database models for production planning and simulation
"""

from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator


class Site(models.Model):
    """Production site (factory location)"""
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.code} - {self.name}"


class ProductCategory(models.Model):
    """Product category (Pizza, Pastry, Pancakes, etc.)"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    color_code = models.CharField(max_length=7, default='#5e3e2f', help_text='Hex color for charts')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'Product Categories'
        ordering = ['name']

    def __str__(self):
        return self.name


class ShiftConfiguration(models.Model):
    """
    Shift configuration options
    Examples: 3x8 (3 shifts of 8 hours), 2x7 SS (2 shifts of 7 hours including Saturday/Sunday)
    """
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    shifts_per_day = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(4)])
    hours_per_shift = models.DecimalField(max_digits=4, decimal_places=2)
    days_per_week = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(7)])
    includes_saturday = models.BooleanField(default=False)
    includes_sunday = models.BooleanField(default=False)
    
    # Calculated weekly hours (for reference)
    @property
    def weekly_hours(self):
        return float(self.shifts_per_day * self.hours_per_shift * self.days_per_week)
    
    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.weekly_hours}h/week)"


class ProductionLine(models.Model):
    """Production line within a site"""
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='lines')
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20)
    
    # Default shift configuration
    default_shift_config = models.ForeignKey(
        ShiftConfiguration, 
        on_delete=models.SET_NULL, 
        null=True,
        related_name='default_lines'
    )
    
    # Base capacity per hour (units produced per hour at 100% efficiency)
    base_capacity_per_hour = models.DecimalField(
        max_digits=10, 
        decimal_places=2,
        validators=[MinValueValidator(0)],
        help_text='Units produced per hour at 100% efficiency'
    )
    
    # Efficiency factor (typically 0.7-0.95)
    efficiency_factor = models.DecimalField(
        max_digits=4, 
        decimal_places=2,
        default=0.85,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text='Production efficiency (0-1)'
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['site__name', 'name']
        unique_together = ['site', 'code']

    def __str__(self):
        return f"{self.site.code} - {self.name}"
    
    @property
    def site_name(self):
        return self.site.name
    
    @property
    def default_weekly_hours(self):
        """Get weekly hours from default shift config"""
        if self.default_shift_config:
            return self.default_shift_config.weekly_hours
        return 0
    
    def get_config_for_date(self, target_date):
        """
        Get the active configuration for a specific date.
        Returns override config if one exists for that date, otherwise returns default.
        """
        override = self.config_overrides.filter(
            start_date__lte=target_date,
            end_date__gte=target_date,
            is_active=True
        ).first()
        
        if override:
            return {
                'type': 'override',
                'override': override,
                'shifts_per_day': override.shifts_per_day,
                'hours_per_shift': float(override.hours_per_shift),
                'include_saturday': override.include_saturday,
                'include_sunday': override.include_sunday,
                'weekly_hours': override.weekly_hours,
                'reason': override.reason
            }
        elif self.default_shift_config:
            return {
                'type': 'default',
                'override': None,
                'shifts_per_day': self.default_shift_config.shifts_per_day,
                'hours_per_shift': float(self.default_shift_config.hours_per_shift),
                'include_saturday': self.default_shift_config.includes_saturday,
                'include_sunday': self.default_shift_config.includes_sunday,
                'weekly_hours': self.default_shift_config.weekly_hours,
                'reason': None
            }
        return None
    
    def get_weekly_capacity(self, shift_config=None, for_date=None):
        """Calculate weekly capacity based on shift configuration"""
        from decimal import Decimal
        
        # If a specific date is provided, check for overrides
        if for_date:
            config = self.get_config_for_date(for_date)
            if config:
                weekly_hours = Decimal(str(config['weekly_hours']))
                return float(self.base_capacity_per_hour * self.efficiency_factor * weekly_hours)
        
        # Otherwise use provided shift_config or default
        config = shift_config or self.default_shift_config
        if not config:
            return 0
        weekly_hours = Decimal(str(config.weekly_hours))
        return float(self.base_capacity_per_hour * self.efficiency_factor * weekly_hours)


class LineConfigOverride(models.Model):
    """
    Temporary configuration override for a production line.
    Allows setting custom shift configurations for specific date ranges.
    Examples: maintenance period, peak season, cleaning week
    """
    line = models.ForeignKey(
        ProductionLine,
        on_delete=models.CASCADE,
        related_name='config_overrides'
    )
    
    # Date range for this override
    start_date = models.DateField(help_text='First day of the override period')
    end_date = models.DateField(help_text='Last day of the override period')
    
    # Custom configuration
    shifts_per_day = models.IntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
        help_text='Number of shifts per day (1-4)'
    )
    hours_per_shift = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(12)],
        help_text='Hours per shift (0-12)'
    )
    include_saturday = models.BooleanField(
        default=False,
        help_text='Include Saturday in production'
    )
    include_sunday = models.BooleanField(
        default=False,
        help_text='Include Sunday in production'
    )
    
    # Metadata
    reason = models.CharField(
        max_length=200,
        blank=True,
        help_text='Reason for override (e.g., Maintenance, Peak Season, Cleaning)'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['line', 'start_date']
        indexes = [
            models.Index(fields=['line', 'start_date', 'end_date']),
        ]
    
    def __str__(self):
        return f"{self.line.name}: {self.config_display} ({self.start_date} to {self.end_date})"
    
    @property
    def config_display(self):
        """Display format like '2x4 S' or '3x8 SS'"""
        weekend = ''
        if self.include_saturday and self.include_sunday:
            weekend = ' SS'
        elif self.include_saturday:
            weekend = ' S'
        return f"{self.shifts_per_day}x{int(self.hours_per_shift)}{weekend}"
    
    @property
    def weekly_hours(self):
        """Calculate total weekly hours for this configuration"""
        days_per_week = 5  # Mon-Fri
        if self.include_saturday:
            days_per_week += 1
        if self.include_sunday:
            days_per_week += 1
        return float(self.shifts_per_day * self.hours_per_shift * days_per_week)


class Client(models.Model):
    """Customer/Client (Lidl, Auchan, Carrefour, etc.)"""
    PRIORITY_CHOICES = [
        (1, 'Critical - Never cut'),
        (2, 'High Priority'),
        (3, 'Medium Priority'),
        (4, 'Low Priority'),
        (5, 'Flexible - Can be reduced first'),
    ]
    
    name = models.CharField(max_length=200, unique=True)
    code = models.CharField(max_length=20, unique=True)
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=3)
    contact_email = models.EmailField(blank=True)
    contract_start_date = models.DateField(null=True, blank=True)
    contract_end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']

    def __str__(self):
        return f"{self.name} (P{self.priority})"


class Product(models.Model):
    """Individual product/article (~800 distinct products)"""
    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(
        ProductCategory, 
        on_delete=models.PROTECT, 
        related_name='products'
    )
    
    # Default production line for this product
    default_line = models.ForeignKey(
        ProductionLine,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_products'
    )
    
    # Product specifications
    unit_weight = models.DecimalField(
        max_digits=8, 
        decimal_places=3, 
        null=True, 
        blank=True,
        help_text='Weight in kg per unit'
    )
    shelf_life_days = models.IntegerField(
        null=True, 
        blank=True,
        help_text='Product shelf life in days'
    )
    is_fresh = models.BooleanField(default=True, help_text='Fresh product (short shelf life)')
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category__name', 'code']

    def __str__(self):
        return f"{self.code} - {self.name}"


class LineProductAssignment(models.Model):
    """
    Which products can be produced on which lines
    A product can have a default line + alternative lines
    """
    line = models.ForeignKey(
        ProductionLine, 
        on_delete=models.CASCADE, 
        related_name='product_assignments'
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='line_assignments'
    )
    is_default = models.BooleanField(default=False, help_text='Is this the default line for this product?')
    
    # Line-specific production rate for this product (can differ from line base capacity)
    production_rate_per_hour = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Override production rate for this product on this line'
    )
    
    # Setup/changeover time when switching to this product
    changeover_time_minutes = models.IntegerField(
        default=30,
        help_text='Time to set up line for this product'
    )

    class Meta:
        unique_together = ['line', 'product']
        ordering = ['line__site__name', 'line__name', 'product__code']

    def __str__(self):
        default_marker = " (default)" if self.is_default else ""
        return f"{self.product.code} on {self.line.name}{default_marker}"


class DemandForecast(models.Model):
    """
    Demand forecast data
    Weekly forecasts by client/product combination
    Forecasts available up to 2 years ahead
    """
    client = models.ForeignKey(
        Client, 
        on_delete=models.CASCADE, 
        related_name='forecasts'
    )
    product = models.ForeignKey(
        Product, 
        on_delete=models.CASCADE, 
        related_name='forecasts'
    )
    
    # Week information
    year = models.IntegerField()
    week_number = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(53)])
    week_start_date = models.DateField()
    
    # Forecast quantity (units)
    forecast_quantity = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        validators=[MinValueValidator(0)]
    )
    
    # Optional: Actual quantity (for historical comparison)
    actual_quantity = models.DecimalField(
        max_digits=12, 
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0)]
    )
    
    # Forecast confidence/accuracy
    confidence_level = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(0), MaxValueValidator(1)],
        help_text='Forecast confidence (0-1)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['client', 'product', 'year', 'week_number']
        ordering = ['year', 'week_number', 'client__name', 'product__code']
        indexes = [
            models.Index(fields=['year', 'week_number']),
            models.Index(fields=['week_start_date']),
            models.Index(fields=['client', 'year', 'week_number']),
            models.Index(fields=['product', 'year', 'week_number']),
        ]

    def __str__(self):
        return f"{self.client.code} - {self.product.code} - W{self.week_number}/{self.year}: {self.forecast_quantity}"

