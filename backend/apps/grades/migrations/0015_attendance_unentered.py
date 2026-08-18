"""출결 값집합에 `미입력` 추가 (2026-08-18 대표 지시).

*"결석이 기본값으로 하지 말고 그냥 미입력을 만들고 ui에 클릭된게 없거나
해제할때 이 상태로 유지하자"* — 지금까지는 `결석` 이 사실상 기본값이라
**"안 왔다"와 "아직 아무도 안 봤다"가 구별되지 않았다.** 앞의 것은 학부모에게
문자가 나가는 상태다(FLOW 3-4).

**백필 없음 — 필요가 없다.** `status` 에 `default=` 가 없고 회차 생성 시 명단만큼
행을 까는 코드도 없어서 미입력 학생은 애초에 **행이 없다**. 행 없음과 `미입력`
행은 같은 뜻이라 그대로 공존한다(집계는 둘을 합쳐 센다 — attendance_admin).

`status` 는 choices 만 바뀌므로 DB 레벨은 무변화(`미입력` 은 3자, max_length=10
안). CHECK 제약을 두지 않는 프로젝트 원칙 덕에 DDL 없이 메타데이터만 갱신된다.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("grades", "0014_make_class_a_real_entity"),
    ]

    operations = [
        migrations.AlterField(
            model_name="attendance",
            name="status",
            field=models.CharField(
                choices=[
                    ("미입력", "미입력"),
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
