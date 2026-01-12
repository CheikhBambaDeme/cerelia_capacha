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
        parser.add_argument(
            '--forecast-file',
            type=str,
            default='generated_data/forecast_cheikh.xlsx',
            help='Path to the forecast Excel file to import',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.stdout.write('Clearing existing data...')
            self._clear_data()
        
        self.stdout.write('Importing company data...')
        
        try:
            # Load the Excel file
            file_path = options['file']
            forecast_file_path = options['forecast_file']
            self.stdout.write(f'Loading data from: {file_path}')
            self.stdout.write(f'Loading forecast data from: {forecast_file_path}')
            
            data = pd.read_excel(file_path, sheet_name=0)
            data_df = pd.DataFrame(data)
            
            # Load forecast data
            forecast_data = pd.read_excel(forecast_file_path, sheet_name=0)
            forecast_df = pd.DataFrame(forecast_data)
            # Drop first two columns and set first row as header
            forecast_df = forecast_df.drop(forecast_df.columns[[0, 1]], axis=1)
            forecast_df.columns = forecast_df.iloc[0]
            forecast_df = forecast_df.drop(forecast_df.index[0]).reset_index(drop=True)
            # Remove rows where all week columns are empty
            week_columns = [col for col in forecast_df.columns if str(col).startswith('W')]
            forecast_df = forecast_df.dropna(subset=week_columns, how='all')
            forecast_df = forecast_df[~forecast_df[week_columns].apply(
                lambda row: all(str(x).strip() == '' or pd.isna(x) for x in row), axis=1
            )]
            forecast_df = forecast_df.fillna(0)
            
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
                
                # 7. Create Clients from real forecast data
                clients = self._create_clients(forecast_df)
                
                # 8. Create Demand Forecasts from real forecast data
                self._create_forecasts(forecast_df, clients, products)
                
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
        
        # Define site codes (from clean_main_dfs.ipynb - based on order in Excel)
        site_codes = {
            "Dole": "PA02",
            "Hoerdt": "PA04",
            "Rivoli": "PA05",
            "SLB": "PA06",
            "Vittel": "PA03",
        }
        
        sites = {}
        for _, row in sites_df.iterrows():
            site_name = row['Site']
            code = site_codes.get(site_name)
            
            if not code:
                self.stdout.write(self.style.WARNING(f'  Unknown site: {site_name} - please add to site_codes mapping'))
                continue
            
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
        """Create production lines from the data with real efficiency and cadency values"""
        lines_df = data_df[["Ligne", "Site"]].drop_duplicates().reset_index(drop=True)
        lines_df = lines_df[lines_df["Ligne"] != "(vide)"]
        
        # Default shift config
        default_shift = list(shift_configs.values())[0] if shift_configs else None
        
        # Real efficiency and cadency data from lines.ipynb
        line_data = {
            'PA02F05': {'efficiency': 82.0, 'cadency': 5400.0},
            'PA04F02': {'efficiency': 84.8, 'cadency': 4800.0},
            'PA02F01': {'efficiency': 83.5, 'cadency': 5400.0},
            'PA02F02': {'efficiency': 78.0, 'cadency': 5280.0},
            'PA02F06': {'efficiency': 84.5, 'cadency': 5160.0},
            'PA05F02': {'efficiency': 79.5, 'cadency': 5100.0},
            'PA02F04': {'efficiency': 82.0, 'cadency': 5400.0},
            'PA05F01': {'efficiency': 84.3, 'cadency': 5100.0},
            'PA02F03': {'efficiency': 84.5, 'cadency': 5280.0},
            'PA04F01': {'efficiency': 84.8, 'cadency': 4800.0},
            'PA06F12': {'efficiency': 50.0, 'cadency': 7740.0},
            'PA06F13': {'efficiency': 50.0, 'cadency': 10380.0},
            'PA02F08': {'efficiency': 86.0, 'cadency': 5100.0},
            'PA06F03': {'efficiency': 63.0, 'cadency': 4200.0},
            'PA06F04': {'efficiency': 64.0, 'cadency': 4800.0},
            'PA04F03': {'efficiency': 85.0, 'cadency': 9600.0},
            'PA05F04': {'efficiency': 80.5, 'cadency': 4440.0},
            'PA06F01': {'efficiency': 60.0, 'cadency': 5200.0},
            'PA03F06': {'efficiency': 82.4, 'cadency': 2035.0},
            'PA03F01': {'efficiency': 74.0, 'cadency': 5055.0},
            'PA03F03': {'efficiency': 80.0, 'cadency': 4650.0},
            'PA06F02': {'efficiency': 0.0, 'cadency': 0.0},
            'PA03F07': {'efficiency': 84.0, 'cadency': 4980.0},
            'PA06F10': {'efficiency': 60.0, 'cadency': 10500.0},
            'PA06F05': {'efficiency': 72.2, 'cadency': 5400.0},
            'PA04F05': {'efficiency': 85.0, 'cadency': 4800.0},
            'PA06C01': {'efficiency': 0.0, 'cadency': 0.0},
            'PA06F11': {'efficiency': 50.0, 'cadency': 4710.0},
            'PA06F06': {'efficiency': 75.0, 'cadency': 4500.0},
            'PA06F07': {'efficiency': 75.0, 'cadency': 4500.0},
            'PA02F07': {'efficiency': 78.5, 'cadency': 5280.0},
            'PA02C03': {'efficiency': 0.0, 'cadency': 0.0},
        }
        
        lines = {}
        for _, row in lines_df.iterrows():
            line_code = row['Ligne']
            site_name = row['Site']
            
            if site_name not in sites:
                continue
            
            site = sites[site_name]
            
            # Use real data if available, otherwise generate random values
            if line_code in line_data:
                # Efficiency is stored as percentage (e.g., 82.0), convert to decimal (0.82)
                efficiency = line_data[line_code]['efficiency'] / 100.0
                base_capacity = line_data[line_code]['cadency']
            else:
                # Fallback to random values for unknown lines
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
                self.stdout.write(f'  Created line: {line.name} at {site.name} (cadency: {base_capacity}, efficiency: {efficiency:.2%})')
        
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

    def _create_clients(self, forecast_df):
        """Create clients from real forecast data"""
        # Extract unique clients from forecast data
        clients_df = forecast_df[["Code Réceptionnaire", "Nom Réceptionnaire"]].drop_duplicates().reset_index(drop=True)
        
        clients = {}
        for _, row in clients_df.iterrows():
            code = str(row['Code Réceptionnaire'])
            raw_name = str(row['Nom Réceptionnaire'])[:180]  # Truncate to leave room for code suffix
            
            # Make name unique by appending code if there's a duplicate
            name = raw_name
            existing_with_name = Client.objects.filter(name=name).exclude(code=code).exists()
            if existing_with_name:
                name = f"{raw_name} ({code})"[:200]
            
            client, created = Client.objects.get_or_create(
                code=code,
                defaults={'name': name, 'is_active': True}
            )
            clients[code] = client
            if created:
                pass  # Don't spam the console
        
        self.stdout.write(f'  Created {len(clients)} clients')
        return clients

    def _create_forecasts(self, forecast_df, clients, products):
        """Create demand forecasts from real forecast data"""
        self.stdout.write('  Generating demand forecasts from real data...')
        
        # Get week columns
        week_columns = [col for col in forecast_df.columns if str(col).startswith('W')]
        
        if not week_columns:
            self.stdout.write('  No week columns found in forecast data')
            return
        
        forecasts_to_create = []
        missing_products = set()
        
        for _, row in forecast_df.iterrows():
            client_code = str(row['Code Réceptionnaire'])
            product_code = str(int(row['Code Article'])) if pd.notna(row['Code Article']) else None
            
            if not product_code:
                continue
            
            client = clients.get(client_code)
            product = products.get(product_code)
            
            if not client:
                continue
            
            if not product:
                missing_products.add(product_code)
                continue
            
            # Process each week column
            for week_col in week_columns:
                try:
                    # Parse week column name (e.g., "W03 2026")
                    week_str = str(week_col)
                    parts = week_str.split()
                    if len(parts) != 2:
                        continue
                    
                    week_num = int(parts[0][1:])  # Extract number after 'W'
                    year = int(parts[1])
                    
                    # Get forecast quantity
                    quantity = row[week_col]
                    if pd.isna(quantity) or quantity == 0:
                        continue
                    
                    # Calculate week start date (Monday of that week)
                    week_start = datetime.strptime(f'{year}-W{week_num:02d}-1', '%G-W%V-%u')
                    
                    forecasts_to_create.append(DemandForecast(
                        client=client,
                        product=product,
                        year=year,
                        week_number=week_num,
                        week_start_date=week_start,
                        forecast_quantity=Decimal(str(round(float(quantity), 2)))
                    ))
                except (ValueError, TypeError) as e:
                    continue
        
        if missing_products:
            self.stdout.write(f'  Warning: {len(missing_products)} products in forecast not found in product database')
        
        # Bulk create forecasts
        if forecasts_to_create:
            DemandForecast.objects.bulk_create(forecasts_to_create, batch_size=5000)
            self.stdout.write(f'  Created {len(forecasts_to_create)} demand forecasts')
