"""원번을 login_id 로 통합하고, 지면 대조용 컬럼은 대조키로 개명 (2026-08-05 확정).

`students.unique_id` 는 이름이 계약을 배반하고 있었다 — 컬럼명은 unique 인데
계약은 "중복될 수 있다"였다. 그 값이 실제로 하는 일은 **지면 대조**뿐이므로
`matching_key` 로 옮긴다.

원번은 이제 `users.login_id` 하나다(접미사 포함, 유일). 지면에는 접미사가
나타날 수 없으므로 대조는 계속 접미사 없는 대조키로 한다.

**값은 바뀌지 않는다** — 컬럼 이름만 옮기는 무손실 개명이다.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("accounts", "0004_loginattempt")]

    operations = [
        migrations.RenameField(
            model_name="student",
            old_name="unique_id",
            new_name="matching_key",
        ),
        migrations.AlterField(
            model_name="student",
            name="matching_key",
            field=models.CharField(db_index=True, max_length=30, verbose_name="대조키"),
        ),
    ]
