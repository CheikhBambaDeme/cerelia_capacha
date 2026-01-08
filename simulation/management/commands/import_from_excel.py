"""
Management command to import company data from Excel files
Populates the database with real data from the company files
"""

import random
from datetime import datetime, timedelta
from decimal import Decimal
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from simulation.models import (
    Site, ShiftConfiguration, ProductionLine,
    Client, Product, LineProductAssignment, DemandForecast,
    SimulationCategory, CustomShiftConfiguration
)


class Command(BaseCommand):
    help = 'Import company data from Excel files and generate missing data'

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear all existing data before import',
        )
        parser.add_argument(
            '--file',
            type=str,
            default='generated_data/fy26_sales_cheikh.xlsx',
            help='Path to the Excel file to import',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            self._clear_data()
        
        self.stdout.write('Importing company data...')
        
        try:
            # Load the Excel file
            file_path = options['file']
            self.stdout.write(f'Loading data from: {file_path}')
            
            data = pd.read_excel(file_path, sheet_name=0)
            data_df = pd.DataFrame(data)
            
            # Select relevant columns
            data_df = data_df[["FY", "Période", "Article", "Libellé", "Ligne", "UVC", "UVP", 
                             "Type Produit", "Type de recette", "Type de matière", "Type d'emballage", "Site"]]
            
            with transaction.atomic():
                # 1. Create Sites
                sites = self._create_sites(data_df)
                
                # 2. Create Shift Configurations
                shift_configs = self._create_shift_configurations()
                
                # 3. Create Production Lines
                lines = self._create_lines(data_df, sites, shift_configs)
                
                # 4. Create Products
                products = self._create_products(data_df, lines)
                
                # 6. Create Line-Product Assignments
                self._create_line_product_assignments(data_df, lines, products)
                
                # 7. Create Clients
                clients = self._create_clients()
                
                # 8. Create Demand Forecasts
                self._create_forecasts(clients, products)
                
            self.stdout.write(self.style.SUCCESS('Data import completed successfully!'))
            
        except FileNotFoundError:
            self.stdout.write(self.style.ERROR(f'File not found: {file_path}'))
            self.stdout.write('Please ensure the Excel file exists in the generated_data folder.')
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Error during import: {str(e)}'))
            import traceback
            traceback.print_exc()

    def _clear_data(self):
        """Clear all existing data"""
        DemandForecast.objects.all().delete()
        LineProductAssignment.objects.all().delete()
        Product.objects.all().delete()
        ProductionLine.objects.all().delete()
        Client.objects.all().delete()
        ShiftConfiguration.objects.all().delete()
        Site.objects.all().delete()
        SimulationCategory.objects.all().delete()
        CustomShiftConfiguration.objects.all().delete()
        self.stdout.write('  Cleared all existing data')

    def _create_sites(self, data_df):
        """Create sites from the data"""
        sites_df = data_df[["Site"]].drop_duplicates().reset_index(drop=True)
        
        # Define site codes
        site_codes = {
            "Dole": "PA02",
            "Nanteuil": "PA04",
            "Nanterre": "PA05",
            "Roquefort": "PA06",
            "Agen": "PA03",
        }
        
        # Create default codes for any unknown sites
        unknown_counter = 1
        
        sites = {}
        for _, row in sites_df.iterrows():
            site_name = row['Site']
            code = site_codes.get(site_name, f"SITE{unknown_counter:02d}")
            if site_name not in site_codes:
                unknown_counter += 1
            
            site, created = Site.objects.get_or_create(
                name=site_name,
                defaults={'code': code, 'is_active': True}
            )
            sites[site_name] = site
            if created:
                self.stdout.write(f'  Created site: {site.name} ({site.code})')
        
        return sites

    def _create_shift_configurations(self):
        """Create shift configurations with new naming convention"""
        configs_data = [
            {'name': '3x8 SS 7d', 'shifts_per_day': 3, 'hours_per_shift': 8, 'days_per_week': 7,
             'includes_saturday': True, 'includes_sunday': True,
             'description': '3 shifts of 8 hours, all week'},
            {'name': '2x8 5d', 'shifts_per_day': 2, 'hours_per_shift': 8, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': 'Two 8-hour shifts, weekdays only'},
            {'name': '2x8 SS 7d', 'shifts_per_day': 2, 'hours_per_shift': 8, 'days_per_week': 7,
             'includes_saturday': True, 'includes_sunday': True,
             'description': '2 shifts of 8 hours, including weekends'},
            {'name': '3x8 5d', 'shifts_per_day': 3, 'hours_per_shift': 8, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': '3 shifts of 8 hours, Monday-Friday'},
            {'name': '1x12 6d', 'shifts_per_day': 1, 'hours_per_shift': 12, 'days_per_week': 6,
             'includes_saturday': True, 'includes_sunday': False,
             'description': 'One 12-hour shift, Mon-Sat'},
            {'name': '2x12 WE 2d', 'shifts_per_day': 2, 'hours_per_shift': 12, 'days_per_week': 2,
             'includes_saturday': True, 'includes_sunday': True,
             'description': 'Two 12-hour shifts, weekends only'},
            {'name': '2x7 5d', 'shifts_per_day': 2, 'hours_per_shift': 7, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': '2 shifts of 7 hours, Monday-Friday'},
            {'name': '1x8 5d', 'shifts_per_day': 1, 'hours_per_shift': 8, 'days_per_week': 5,
             'includes_saturday': False, 'includes_sunday': False,
             'description': 'Single 8-hour shift, Monday-Friday'},
        ]
        
        configs = {}
        for data in configs_data:
            config, created = ShiftConfiguration.objects.get_or_create(
                name=data['name'], defaults=data
            )
            configs[data['name']] = config
            if created:
                self.stdout.write(f'  Created shift config: {config.name} ({config.weekly_hours}h/week)')
        
        return configs

    def _create_lines(self, data_df, sites, shift_configs):
        """Create production lines from the data"""
        lines_df = data_df[["Ligne", "Site"]].drop_duplicates().reset_index(drop=True)
        lines_df = lines_df[lines_df["Ligne"] != "(vide)"]
        
        # Default shift config
        default_shift = list(shift_configs.values())[0] if shift_configs else None
        
        lines = {}
        for _, row in lines_df.iterrows():
            line_code = row['Ligne']
            site_name = row['Site']
            
            if site_name not in sites:
                continue
            
            site = sites[site_name]
            
            # Generate realistic capacity values
            base_capacity = random.uniform(800, 2500)
            efficiency = random.uniform(0.75, 0.92)
            
            line, created = ProductionLine.objects.get_or_create(
                site=site,
                code=line_code,
                defaults={
                    'name': f'Line {line_code}',
                    'default_shift_config': default_shift,
                    'base_capacity_per_hour': Decimal(str(round(base_capacity, 2))),
                    'efficiency_factor': Decimal(str(round(efficiency, 2))),
                    'is_active': True
                }
            )
            lines[line_code] = line
            if created:
                self.stdout.write(f'  Created line: {line.name} at {site.name}')
        
        return lines

    def _create_products(self, data_df, lines):
        """Create products from the data"""
        products_df = data_df[["Article", "Libellé", "Type Produit", "Type de recette", 
                              "Type de matière", "Type d'emballage"]].drop_duplicates().reset_index(drop=True)
        
        # Determine default line for each product
        article_line_uvc = data_df.groupby(["Article", "Ligne"], as_index=False)["UVC"].sum()
        article_line_uvc.rename(columns={"UVC": "Total_UVC"}, inplace=True)
        default_line_df = article_line_uvc.loc[
            article_line_uvc.groupby('Article')['Total_UVC'].idxmax(), 
            ['Article', 'Ligne']
        ]
        default_line_dict = dict(zip(default_line_df['Article'], default_line_df['Ligne']))
        
        products = {}
        for _, row in products_df.iterrows():
            code = str(row['Article'])
            name = row['Libellé'] if pd.notna(row['Libellé']) else code
            
            # Get product attributes
            product_type = row['Type Produit'] if pd.notna(row['Type Produit']) else ''
            recipe_type = row['Type de recette'] if pd.notna(row['Type de recette']) else ''
            material_type = row['Type de matière'] if pd.notna(row['Type de matière']) else ''
            packaging_type = row["Type d'emballage"] if pd.notna(row["Type d'emballage"]) else ''
            
            # Get default line
            default_line_code = default_line_dict.get(row['Article'])
            default_line = lines.get(default_line_code) if default_line_code else None
            
            product, created = Product.objects.get_or_create(
                code=code,
                defaults={
                    'name': name[:200],
                    'default_line': default_line,
                    'product_type': str(product_type)[:100] if product_type else '',
                    'recipe_type': str(recipe_type)[:100] if recipe_type else '',
                    'material_type': str(material_type)[:100] if material_type else '',
                    'packaging_type': str(packaging_type)[:100] if packaging_type else '',
                    'is_active': True
                }
            )
            products[code] = product
            if created:
                pass  # Don't spam the console
        
        self.stdout.write(f'  Created {len(products)} products')
        return products

    def _create_line_product_assignments(self, data_df, lines, products):
        """Create line-product assignments"""
        # Get all line-product combinations
        article_line_uvc = data_df.groupby(["Article", "Ligne"], as_index=False)["UVC"].sum()
        article_line_uvc.rename(columns={"UVC": "Total_UVC"}, inplace=True)
        
        # Determine default lines
        default_line_df = article_line_uvc.loc[
            article_line_uvc.groupby('Article')['Total_UVC'].idxmax(), 
            ['Article', 'Ligne']
        ]
        default_line_set = set(zip(default_line_df['Article'], default_line_df['Ligne']))
        
        assignments_created = 0
        for _, row in article_line_uvc.iterrows():
            product_code = str(row['Article'])
            line_code = row['Ligne']
            
            if line_code == "(vide)":
                continue
            
            product = products.get(product_code)
            line = lines.get(line_code)
            
            if product and line:
                is_default = (row['Article'], line_code) in default_line_set
                
                assignment, created = LineProductAssignment.objects.get_or_create(
                    line=line,
                    product=product,
                    defaults={'is_default': is_default}
                )
                if created:
                    assignments_created += 1
        
        self.stdout.write(f'  Created {assignments_created} line-product assignments')

    def _create_clients(self):
        """Create clients"""
        clients_data = [
            {'name': 'Lidl', 'code': 'LIDL'},
            {'name': 'Carrefour', 'code': 'CARF'},
            {'name': 'Auchan', 'code': 'AUCH'},
            {'name': 'Leclerc', 'code': 'LECL'},
            {'name': 'Intermarché', 'code': 'INTM'},
            {'name': 'Casino', 'code': 'CASI'},
            {'name': 'Monoprix', 'code': 'MONO'},
            {'name': 'Système U', 'code': 'SYSU'},
        ]
        
        clients = {}
        for data in clients_data:
            client, created = Client.objects.get_or_create(
                code=data['code'],
                defaults={'name': data['name'], 'is_active': True}
            )
            clients[data['code']] = client
            if created:
                self.stdout.write(f'  Created client: {client.name}')
        
        return clients

    def _create_forecasts(self, clients, products):
        """Create demand forecasts for the clients"""
        self.stdout.write('  Generating demand forecasts...')
        
        # Get list of products
        product_list = list(products.values())
        client_list = list(clients.values())
        
        if not product_list or not client_list:
            self.stdout.write('  No products or clients available for forecasts')
            return
        
        # Assign products to clients (each client gets a random subset)
        client_products = {}
        for client in client_list:
            # Each client gets 10-30% of products
            num_products = max(10, len(product_list) // random.randint(4, 10))
            client_products[client.id] = random.sample(product_list, min(num_products, len(product_list)))
        
        # Generate weekly forecasts for 2 years
        start_date = datetime(2026, 1, 5)  # First Monday of 2026 (week starts on Monday)
        weeks_ahead = 104  # 2 years
        
        forecasts_to_create = []
        
        for week_offset in range(weeks_ahead):
            week_start = start_date + timedelta(weeks=week_offset)
            year = week_start.isocalendar()[1]
            week_num = week_start.isocalendar()[1]
            year = week_start.isocalendar()[0]
            
            # Seasonal factor (higher in winter, lower in summer)
            month = week_start.month
            if month in [11, 12, 1, 2]:
                seasonal_factor = random.uniform(1.1, 1.4)
            elif month in [6, 7, 8]:
                seasonal_factor = random.uniform(0.7, 0.9)
            else:
                seasonal_factor = random.uniform(0.9, 1.1)
            
            for client in client_list:
                # Each client creates forecasts for their assigned products
                for product in client_products[client.id]:
                    # Random base demand with client-specific variation
                    base_demand = random.uniform(500, 15000)
                    
                    # Apply seasonal factor and some noise
                    demand = base_demand * seasonal_factor * random.uniform(0.8, 1.2)
                    
                    forecasts_to_create.append(DemandForecast(
                        client=client,
                        product=product,
                        year=year,
                        week_number=week_num,
                        week_start_date=week_start,
                        forecast_quantity=Decimal(str(round(demand, 2)))
                    ))
        
        # Bulk create forecasts
        if forecasts_to_create:
            DemandForecast.objects.bulk_create(forecasts_to_create, batch_size=5000)
            self.stdout.write(f'  Created {len(forecasts_to_create)} demand forecasts')
