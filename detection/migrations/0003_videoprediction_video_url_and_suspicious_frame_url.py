from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("detection", "0002_videoprediction_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="videoprediction",
            name="suspicious_frame_url",
            field=models.URLField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="videoprediction",
            name="video_url",
            field=models.URLField(blank=True, null=True),
        ),
    ]
