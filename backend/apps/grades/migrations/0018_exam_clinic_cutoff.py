"""클리닉 컷을 시험에 담는다 (FLOW 3-3·3-7).

대상 판정은 지금까지 언제나 그 시험 평균이었다 — 컷을 담을 자리가 없어서다.
비워 두면 종전대로 평균으로 갈린다(`scoring._threshold`).
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("grades", "0017_exam_on_course_week"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="clinic_cutoff",
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=6,
                null=True,
                verbose_name="클리닉 컷",
            ),
        ),
    ]
