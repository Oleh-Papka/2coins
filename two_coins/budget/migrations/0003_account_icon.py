# Generated by Django 4.2.2 on 2023-07-01 15:12

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('budget', '0002_category_icon'),
    ]

    operations = [
        migrations.AddField(
            model_name='account',
            name='icon',
            field=models.CharField(blank=True, help_text='Icon name from FontAwesome', max_length=30, null=True, verbose_name='Icon'),
        ),
    ]