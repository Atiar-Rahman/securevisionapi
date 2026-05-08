from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("alert", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="alert",
            name="frame_url",
            field=models.URLField(blank=True, null=True),
        ),
    ]
