from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def assign_existing_trades_to_current_user(apps, schema_editor):
    Trade = apps.get_model('trading', 'Trade')
    User = apps.get_model('auth', 'User')

    user = User.objects.filter(username='noah.stephenson').first()
    if user is None:
        user = User.objects.filter(is_superuser=True).order_by('id').first()
    if user is None:
        user = User.objects.order_by('id').first()

    if user is not None:
        Trade.objects.filter(user__isnull=True).update(user=user)


class Migration(migrations.Migration):

    dependencies = [
        ('trading', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='trade',
            name='user',
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.RunPython(assign_existing_trades_to_current_user),
        migrations.AlterField(
            model_name='trade',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
