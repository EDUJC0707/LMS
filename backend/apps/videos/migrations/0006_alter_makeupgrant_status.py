"""동보에서 `승인` 값을 뺀다 (FLOW 3-4).

승인 단계가 없어졌다 — 지급 조건은 신청 + 결석 확인 둘뿐이다. 값집합(choices)만
바뀌므로 **DB 에는 제약이 없고 기존 행도 건드리지 않는다**. 과거에 `승인` 으로
찍힌 행은 그대로 남는다(감사 이력 — 지우지 않는다).

클리닉의 `승인배정`(clinic.ClinicRequest)은 별개 값집합이라 영향 없다.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("videos", "0005_watermark_tamper"),
    ]

    operations = [
        migrations.AlterField(
            model_name="makeupgrant",
            name="status",
            field=models.CharField(
                choices=[("신청", "신청"), ("지급완료", "지급완료"), ("거절", "거절")],
                default="신청",
                max_length=15,
                verbose_name="상태",
            ),
        ),
    ]
