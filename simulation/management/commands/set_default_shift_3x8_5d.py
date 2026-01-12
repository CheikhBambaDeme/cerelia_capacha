# Usage: python manage.py shell < set_default_shift_3x8_5d.py
# This script sets all ProductionLine.default_shift_config to the '3x8 5d' ShiftConfiguration.

from simulation.models import ShiftConfiguration, ProductionLine


# Find the '3x8 5d' shift config (case-insensitive, flexible naming)
shift = ShiftConfiguration.objects.filter(name__icontains='3x8 5d').first()
if not shift:
    # Try a fallback: name contains '3x8' and description contains '5d'
    shift = ShiftConfiguration.objects.filter(name__icontains='3x8', description__icontains='5d').first()
if not shift:
    raise Exception("No ShiftConfiguration found with name containing '3x8 5d' or name '3x8' and description '5d'. Please create it first.")

updated = 0
for line in ProductionLine.objects.all():
    if line.default_shift_config != shift:
        line.default_shift_config = shift
        line.save()
        updated += 1
print(f"Updated {updated} production lines to default shift config: {shift.name}")
