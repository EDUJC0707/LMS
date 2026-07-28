"""클리닉 슬롯 정원 1 고정 (2026-07-21 회의 — "시간별로 학생 한 명씩").

정원은 관리자가 정하는 설정값이 아니라 운영의 고정 사실이므로
① 기존 행의 capacity 를 1 로 정규화하고 ② CheckConstraint 로 못 박는다.
③ editable=False 로 폼·관리자 화면에서 입력칸이 뜨지 않게 한다.

정규화(RunPython)를 먼저 두는 이유: capacity>1 인 기존 행(시드 포함)이 있으면
제약 추가가 실패한다. 역방향은 값 복원이 불가능(원래 값을 모른다)하므로 no-op.
"""
from django.db import migrations, models


def normalize_capacity(apps, schema_editor):
    apps.get_model("clinic", "ClinicSlot").objects.exclude(capacity=1).update(capacity=1)


class Migration(migrations.Migration):

    dependencies = [
        ("clinic", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(normalize_capacity, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="clinicslot",
            name="capacity",
            field=models.SmallIntegerField(default=1, editable=False, verbose_name="정원"),
        ),
        migrations.AddConstraint(
            model_name="clinicslot",
            constraint=models.CheckConstraint(
                condition=models.Q(("capacity", 1)), name="ck_clinic_slots_capacity_one"
            ),
        ),
    ]
