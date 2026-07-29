"""원번 컬럼 확장 20 → 30 (2026-07-29 원번 규칙 개정).

원번이 `{학년}{이름}{뒷4자리}` 파생값이 되면서 최대치가 학년 1 + 정규화 이름
20(login_id 상한) + 뒷4자리 4 = 25자가 됐다. **확장뿐이라 기존 값은 그대로
살아 있다**(자르지 않는다) — 구 형식 원번은 학년 승급·재발급 시점에 새 규칙
값으로 갈린다.
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
