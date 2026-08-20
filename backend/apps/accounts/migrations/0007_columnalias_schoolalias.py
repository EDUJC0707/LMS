"""별칭표 두 개 + 컬럼 별칭 초기값 (FLOW 2-2).

초기값은 지금까지 프런트(`paste.ts`)에 하드코딩돼 있던 목록 그대로다. 표를
비워 두고 시작하면 **오늘 자동으로 맞던 머리줄이 내일 안 맞는다** — 표로
옮기는 것이 기능 후퇴가 되면 안 된다. 이미 squash 된 형태(공백·구두점 없는
소문자)라 `aliases.alias_key` 를 다시 태우지 않는다.

학교 별칭표는 **비운 채로 둔다.** 넣을 근거 목록이 없고, 모르는 학교는 온
그대로 저장되므로(FLOW 2-3) 빈 표가 곧 지금 동작이다.
"""
from django.db import migrations, models

# 별칭 → 열. paste.ts 의 ALIASES 를 뒤집은 것이다.
COLUMN_ALIASES = [
    ("이름", "name"),
    ("성명", "name"),
    ("학생이름", "name"),
    ("학생성명", "name"),
    ("학생명", "name"),
    ("name", "name"),
    ("학생휴대폰", "phone"),
    ("학생휴대전화", "phone"),
    ("학생핸드폰", "phone"),
    ("학생폰", "phone"),
    ("학생전화", "phone"),
    ("학생전화번호", "phone"),
    ("학생연락처", "phone"),
    ("학생번호", "phone"),
    ("학생hp", "phone"),
    ("휴대폰", "phone"),
    ("휴대전화", "phone"),
    ("핸드폰", "phone"),
    ("전화", "phone"),
    ("전화번호", "phone"),
    ("연락처", "phone"),
    ("학부모휴대폰", "parent_phone"),
    ("학부모휴대전화", "parent_phone"),
    ("학부모핸드폰", "parent_phone"),
    ("학부모폰", "parent_phone"),
    ("학부모전화", "parent_phone"),
    ("학부모전화번호", "parent_phone"),
    ("학부모연락처", "parent_phone"),
    ("학부모번호", "parent_phone"),
    ("학부모hp", "parent_phone"),
    ("학부모", "parent_phone"),
    ("보호자휴대폰", "parent_phone"),
    ("보호자핸드폰", "parent_phone"),
    ("보호자폰", "parent_phone"),
    ("보호자전화", "parent_phone"),
    ("보호자연락처", "parent_phone"),
    ("보호자", "parent_phone"),
    ("부모님연락처", "parent_phone"),
    ("모연락처", "parent_phone"),
    ("부연락처", "parent_phone"),
    ("학년", "grade"),
    ("재학학년", "grade"),
    ("학교", "school"),
    ("학교명", "school"),
    ("출신학교", "school"),
    ("재학학교", "school"),
    ("고교", "school"),
]


def seed_column_aliases(apps, schema_editor):
    ColumnAlias = apps.get_model("accounts", "ColumnAlias")
    ColumnAlias.objects.bulk_create(
        [ColumnAlias(alias=alias, field=field) for alias, field in COLUMN_ALIASES],
        ignore_conflicts=True,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0006_remove_student_current_class"),
    ]

    operations = [
        migrations.CreateModel(
            name="ColumnAlias",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "alias",
                    models.CharField(max_length=50, unique=True, verbose_name="별칭"),
                ),
                ("field", models.CharField(max_length=20, verbose_name="열")),
            ],
            options={
                "verbose_name": "컬럼 별칭",
                "verbose_name_plural": "컬럼 별칭",
                "db_table": "column_aliases",
            },
        ),
        migrations.CreateModel(
            name="SchoolAlias",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "alias",
                    models.CharField(max_length=100, unique=True, verbose_name="별칭"),
                ),
                (
                    "canonical",
                    models.CharField(
                        db_index=True, max_length=100, verbose_name="정식 이름"
                    ),
                ),
            ],
            options={
                "verbose_name": "학교 별칭",
                "verbose_name_plural": "학교 별칭",
                "db_table": "school_aliases",
            },
        ),
        # 되돌리기는 아무것도 하지 않는다 — 되돌리는 시점에 표가 통째로
        # 사라지므로 행을 골라 지울 이유가 없다.
        migrations.RunPython(seed_column_aliases, migrations.RunPython.noop),
    ]
