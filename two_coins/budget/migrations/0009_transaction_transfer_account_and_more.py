# Generated by Django 4.2.2 on 2023-07-27 08:34

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0008_alter_category_icon_alter_transaction_txn_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='transaction',
            name='transfer_account',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='transfer_transactions', to='budget.account', verbose_name='Transfer account'),
        ),
        migrations.AlterField(
            model_name='transaction',
            name='description',
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name='Description'),
        ),
    ]
