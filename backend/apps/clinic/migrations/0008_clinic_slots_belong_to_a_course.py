"""슬롯이 커리에 붙고, 정원이 조교 수를 따라 움직인다 (FLOW 1-1·3-7).

2026-08-19 대표 구술로 두 가지가 뒤집혔다.

① **시간대는 커리가 갖는다.** 슬롯은 커리의 클리닉 창에서 한 시간 단위로 선다.
② **정원은 클리닉 조교 수다.** 0002 가 걸어 둔 `capacity=1` 고정
   (`editable=False` · `CheckConstraint`)을 여기서 푼다 — 조교가 둘이면 두 명을
   받아야 하는데 그때 값이 하나뿐인 컬럼은 거짓말이 된다.

옛 슬롯은 커리가 없다. 지우지 못한다 — 신청 이력이 PROTECT 로 참조하고 있고
지난 클리닉의 "그때는 이 시간이 있었다" 도 남아야 한다. 그래서 폐지만 한다.
"""

import django.db.models.deletion
from django.db import migrations, models


def retire_courseless_slots(apps, schema_editor):
    """커리 없이 서 있던 슬롯을 폐지한다 — 새 신청은 커리의 창에서만 받는다."""
    apps.get_model("clinic", "ClinicSlot").objects.filter(course__isnull=True).update(
        is_active=False
    )


class Migration(migrations.Migration):

    dependencies = [
        ("clinic", "0007_clinicrequest_reject_reason"),
        ("curriculum", "0008_course_holds_the_clinic_hours"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="clinicslot",
            name="uq_clinic_slots_weekday_start",
        ),
        migrations.RemoveConstraint(
            model_name="clinicslot",
            name="ck_clinic_slots_capacity_one",
        ),
        migrations.AddField(
            model_name="clinicslot",
            name="course",
            field=models.ForeignKey(
                blank=True,
                db_column="course_id",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="clinic_slots",
                to="curriculum.course",
                verbose_name="커리",
            ),
        ),
        migrations.AlterField(
            model_name="clinicslot",
            name="capacity",
            field=models.SmallIntegerField(default=1, verbose_name="정원"),
        ),
        migrations.AddConstraint(
            model_name="clinicslot",
            constraint=models.UniqueConstraint(
                fields=("course", "weekday", "start_time"),
                name="uq_clinic_slots_course_weekday_start",
            ),
        ),
        migrations.RunPython(retire_courseless_slots, migrations.RunPython.noop),
    ]
