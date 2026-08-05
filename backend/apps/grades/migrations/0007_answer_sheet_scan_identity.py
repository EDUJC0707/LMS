from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("grades", "0006_rename_recognized_unique_id"),
    ]

    operations = [
        migrations.AddConstraint(
            model_name="answersheet",
            constraint=models.UniqueConstraint(
                fields=("exam", "scan_image_path"), name="uq_answer_sheets_exam_scan"
            ),
        ),
    ]
