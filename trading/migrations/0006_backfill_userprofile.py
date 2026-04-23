from decimal import Decimal

from django.db import migrations

STARTING_CASH = Decimal('100000.00')


def backfill_profiles(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    UserProfile = apps.get_model('trading', 'UserProfile')
    Trade = apps.get_model('trading', 'Trade')

    for user in User.objects.all():
        if UserProfile.objects.filter(user=user).exists():
            continue  # idempotent — skip users who already have a profile

        cash = STARTING_CASH
        for trade in Trade.objects.filter(user=user).order_by('created_at'):
            amount = Decimal(str(trade.quantity)) * Decimal(str(trade.price))
            if trade.trade_type == 'BUY':
                cash -= amount
            else:
                cash += amount

        UserProfile.objects.create(
            user=user,
            cash_balance=cash,
            starting_balance=STARTING_CASH,
        )


class Migration(migrations.Migration):
    dependencies = [
        ('trading', '0005_userprofile'),
    ]

    operations = [
        migrations.RunPython(backfill_profiles, migrations.RunPython.noop),
    ]
