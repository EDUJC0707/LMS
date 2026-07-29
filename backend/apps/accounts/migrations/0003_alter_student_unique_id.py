"""원번 컬럼 확장 20 → 30 (2026-07-29 원번 규칙 개정).

원번에 이름이 들어오면서 최대치가 정규화 이름 20(login_id 상한) + 뒷4자리 4 로
커졌다. **확장뿐이라 기존 값은 그대로 살아 있다**(자르지 않는다).

**정정(같은 날 재개정)**: 이 마이그레이션을 쓸 때의 규칙은 `{학년}{이름}{뒷4}`
(최대 25자)였는데, 그 뒤 학년이 빠져 `{이름}{뒷4}`(최대 24자)가 됐다. 폭 30 은
**그대로 둔다** — 줄여도 얻는 것이 없고, 축소 AlterField 는 이미 저장된 구 형식
25자 값을 자르거나 마이그레이션을 실패시킨다(`models.Student.unique_id` 계약).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_remove_student_youtube_email_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="student",
            name="unique_id",
            field=models.CharField(db_index=True, max_length=30, verbose_name="원번"),
        ),
    ]
