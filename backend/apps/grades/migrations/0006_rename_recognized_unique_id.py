"""지면 인식값도 대조키로 개명 (2026-08-05, accounts 0004 와 한 벌).

답안지·워크북이 지면에서 읽어 오는 값은 원번이 아니라 **대조키**다 — 접미사가
지면에 나타날 수 없으므로 원번 전체는 애초에 들어올 수 없다. 이름을 사실에
맞춘다. 값은 그대로다.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("grades", "0005_attendance_status_value_set"),
        ("accounts", "0004_rename_unique_id_matching_key"),
    ]

    operations = [
        migrations.RenameField(
            model_name="answersheet",
            old_name="recognized_unique_id",
            new_name="recognized_matching_key",
        ),
        migrations.RenameField(
            model_name="workbooksubmission",
            old_name="recognized_unique_id",
            new_name="recognized_matching_key",
        ),
        migrations.AlterField(
            model_name="answersheet",
            name="recognized_matching_key",
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name="인식된 대조키"
            ),
        ),
        migrations.AlterField(
            model_name="workbooksubmission",
            name="recognized_matching_key",
            field=models.CharField(
                blank=True, max_length=30, null=True, verbose_name="인식된 대조키"
            ),
        ),
    ]
