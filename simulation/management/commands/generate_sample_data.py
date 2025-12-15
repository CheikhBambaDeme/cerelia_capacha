"""
Management command to generate sample data for Cerelia Simulation
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal
from django.core.management.base import BaseCommand
from simulation.models import (
    Site, ProductCategory, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast
)


class Command(BaseCommand):
    help = 'Generate sample data for Cerelia Simulation'

    def handle(self, *args, **options):
        self.stdout.write('Creating sample data...')
        
        # Create Sites
        sites_data = [
            {'name': 'Cerelia Site 1 - Main Factory', 'code': 'S1'},
            {'name': 'Cerelia Site 2 - North Plant', 'code': 'S2'},
            {'name': 'Cerelia Site 3 - South Plant', 'code': 'S3'},
        ]
        sites = []
        for data in sites_data:
            site, created = Site.objects.get_or_create(code=data['code'], defaults=data)
            sites.append(site)
            if created:
                self.stdout.write(f'  Created site: {site.name}')

        # Create Shift Configurations
        shift_configs_data = [
            {'name': '2x8', 'shifts_per_day': 2, 'hours_per_shift': 8, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': '2 shifts of 8 hours, Monday-Friday'},
            {'name': '3x8', 'shifts_per_day': 3, 'hours_per_shift': 8, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': '3 shifts of 8 hours, Monday-Friday'},
            {'name': '2x8 SS', 'shifts_per_day': 2, 'hours_per_shift': 8, 'days_per_week': 7,
             'includes_saturday': True, 'includes_sunday': True,
             'description': '2 shifts of 8 hours, including weekends'},
            {'name': '3x8 SS', 'shifts_per_day': 3, 'hours_per_shift': 8, 'days_per_week': 7,
             'includes_saturday': True, 'includes_sunday': True,
             'description': '3 shifts of 8 hours, including weekends'},
            {'name': '2x7', 'shifts_per_day': 2, 'hours_per_shift': 7, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': '2 shifts of 7 hours, Monday-Friday'},
        ]
        shift_configs = []
        for data in shift_configs_data:
            config, created = ShiftConfiguration.objects.get_or_create(
                name=data['name'], defaults=data
            )
            shift_configs.append(config)
            if created:
                self.stdout.write(f'  Created shift config: {config.name}')

        # Create Product Categories
        categories_data = [
            {'name': 'Pizza Dough', 'color_code': '#ea6d09', 'description': 'Ready-to-bake pizza bases'},
            {'name': 'Pastry', 'color_code': '#f5dd1f', 'description': 'Puff pastry and croissant dough'},
            {'name': 'Pancakes', 'color_code': '#5e3e2f', 'description': 'Pancake and crepe batter'},
            {'name': 'Bread Dough', 'color_code': '#8B4513', 'description': 'Bread and roll dough'},
            {'name': 'Cookie Dough', 'color_code': '#D2691E', 'description': 'Cookie and biscuit dough'},
        ]
        categories = []
        for data in categories_data:
            category, created = ProductCategory.objects.get_or_create(
                name=data['name'], defaults=data
            )
            categories.append(category)
            if created:
                self.stdout.write(f'  Created category: {category.name}')

        # Create Clients
        clients_data = [
            {'name': 'Lidl', 'code': 'LIDL', 'priority': 1},
            {'name': 'Carrefour', 'code': 'CARF', 'priority': 1},
            {'name': 'Auchan', 'code': 'AUCH', 'priority': 2},
            {'name': 'Leclerc', 'code': 'LECL', 'priority': 2},
            {'name': 'Intermarché', 'code': 'INTM', 'priority': 3},
            {'name': 'Casino', 'code': 'CASI', 'priority': 3},
            {'name': 'Monoprix', 'code': 'MONO', 'priority': 4},
            {'name': 'Franprix', 'code': 'FRAN', 'priority': 5},
        ]
        clients = []
        for data in clients_data:
            client, created = Client.objects.get_or_create(code=data['code'], defaults=data)
            clients.append(client)
            if created:
                self.stdout.write(f'  Created client: {client.name}')

        # Create Production Lines
        lines = []
        line_counter = 1
        for site in sites:
            num_lines = random.randint(8, 12)
            for i in range(num_lines):
                line_data = {
                    'site': site,
                    'name': f'Line {i+1}',
                    'code': f'L{line_counter:02d}',
                    'default_shift_config': random.choice(shift_configs),
                    'base_capacity_per_hour': Decimal(str(random.randint(800, 2000))),
                    'efficiency_factor': Decimal(str(round(random.uniform(0.75, 0.92), 2))),
                }
                line, created = ProductionLine.objects.get_or_create(
                    site=site, code=line_data['code'],
                    defaults=line_data
                )
                lines.append(line)
                line_counter += 1
                if created:
                    self.stdout.write(f'  Created line: {site.code} - {line.name}')

        # Create Products (~100 sample products)
        products = []
        product_counter = 1
        for category in categories:
            num_products = random.randint(15, 25)
            for i in range(num_products):
                product_data = {
                    'code': f'{category.name[:3].upper()}{product_counter:04d}',
                    'name': f'{category.name} Product {i+1}',
                    'category': category,
                    'default_line': random.choice(lines),
                    'unit_weight': Decimal(str(round(random.uniform(0.2, 2.0), 3))),
                    'shelf_life_days': random.randint(5, 30),
                    'is_fresh': random.choice([True, True, True, False]),
                }
                product, created = Product.objects.get_or_create(
                    code=product_data['code'], defaults=product_data
                )
                products.append(product)
                product_counter += 1
                if created:
                    self.stdout.write(f'  Created product: {product.code}')

        # Create Line-Product Assignments
        for product in products:
            # Assign to default line
            LineProductAssignment.objects.get_or_create(
                line=product.default_line,
                product=product,
                defaults={'is_default': True}
            )
            # Assign to 1-3 alternative lines
            alt_lines = random.sample([l for l in lines if l != product.default_line], 
                                      min(random.randint(1, 3), len(lines)-1))
            for line in alt_lines:
                LineProductAssignment.objects.get_or_create(
                    line=line,
                    product=product,
                    defaults={'is_default': False}
                )

        # Generate Demand Forecasts (2 years of weekly data)
        self.stdout.write('  Generating demand forecasts (this may take a moment)...')
        
        # Start from current week
        today = datetime.now().date()
        start_date = today - timedelta(days=today.weekday())  # Monday of current week
        
        # Generate 104 weeks (2 years) of forecasts
        forecasts_created = 0
        for week_offset in range(104):
            week_start = start_date + timedelta(weeks=week_offset)
            year, week_num, _ = week_start.isocalendar()
            
            # Seasonal factor (higher demand in winter)
            month = (week_start + timedelta(days=3)).month
            if month in [11, 12, 1, 2]:
                seasonal_factor = 1.3
            elif month in [6, 7, 8]:
                seasonal_factor = 0.8
            else:
                seasonal_factor = 1.0
            
            # Create forecasts for a subset of client-product combinations
            for client in clients:
                # Each client orders from some products
                client_products = random.sample(products, min(random.randint(10, 30), len(products)))
                
                for product in client_products:
                    # Base demand with some randomness
                    base_demand = random.randint(500, 5000)
                    demand = int(base_demand * seasonal_factor * random.uniform(0.8, 1.2))
                    
                    forecast, created = DemandForecast.objects.get_or_create(
                        client=client,
                        product=product,
                        year=year,
                        week_number=week_num,
                        defaults={
                            'week_start_date': week_start,
                            'forecast_quantity': Decimal(str(demand)),
                            'confidence_level': Decimal(str(round(random.uniform(0.7, 0.95), 2)))
                        }
                    )
                    if created:
                        forecasts_created += 1

        self.stdout.write(f'  Created {forecasts_created} demand forecasts')
        
        self.stdout.write(self.style.SUCCESS('Sample data generation complete!'))
        self.stdout.write(f'''
Summary:
  - Sites: {Site.objects.count()}
  - Shift Configurations: {ShiftConfiguration.objects.count()}
  - Product Categories: {ProductCategory.objects.count()}
  - Production Lines: {ProductionLine.objects.count()}
  - Clients: {Client.objects.count()}
  - Products: {Product.objects.count()}
  - Line Assignments: {LineProductAssignment.objects.count()}
  - Demand Forecasts: {DemandForecast.objects.count()}
''')
