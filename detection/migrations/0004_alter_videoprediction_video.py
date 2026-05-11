from cloudinary.models import CloudinaryField
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("detection", "0003_videoprediction_video_url_and_suspicious_frame_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="videoprediction",
            name="video",
            field=CloudinaryField(
                "video",
                folder="securevision/videos",
                resource_type="video",
            ),
        ),
    ]
