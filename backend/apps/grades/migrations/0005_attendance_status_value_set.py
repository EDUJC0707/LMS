"""출결 값집합 개편 — `지각` 제거 · `결석(동보)`·`결석(현보)` 추가 (2026-07-29 확정).

**데이터 이관 없음 — 의도적이다.** 이 시점의 `지각` 레코드는 전부 dev 시드
(`seed_demo`)가 만든 것이고 운영 데이터는 아직 없다(서비스 미오픈). 시드는 매
실행마다 전량 wipe 후 재생성하므로 같은 커밋에서 시드 코드를 새 값집합으로
바꾸는 것으로 충분하다. 운영 데이터가 있었다면 `지각`을 무엇으로 옮길지는
자동 판정이 불가능하다 — 지각은 OMR 미제출(scores.is_taken=False)로 드러나는
사실이지 결석이 아니므로 `출석`으로 밀어야 하는데, 그건 복습영상 자동지급
트리거를 소급 발동시키는 파괴적 이관이라 사람 확인 없이는 돌리면 안 된다.

`status` 는 choices 만 바뀌므로 DB 레벨은 무변화(폭도 그대로 — `결석(동보)`는
6자, max_length=10 안에 들어간다). CHECK 제약을 두지 않는 프로젝트 원칙 덕에
DDL 없이 Django 메타데이터만 갱신된다.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("grades", "0004_widen_recognized_unique_id"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[
                    ("출석", "출석"),
                    ("결석", "결석"),
                    ("결석(동보)", "결석(동보)"),
                    ("결석(현보)", "결석(현보)"),
                ],
                max_length=10,
                verbose_name="출결 상태",
            ),
        ),
    ]
