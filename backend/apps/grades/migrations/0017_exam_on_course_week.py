"""시험을 반의 회차에서 커리 주차로 올린다 (FLOW 3-3).

지금까지는 `class_sessions.exam` 하나로 회차마다 시험을 따로 잡았다. 그래서
목반과 화반이 같은 시험지를 봐도 문항·정답·배점을 두 벌 넣어야 했다.

백필은 두 걸음이다.
1. 회차가 가리키던 시험을 **그 회차의 커리 주차**로 올린다. 한 주차 = 시험
   하나이므로 이미 다른 시험이 올라간 주차는 건너뛴다(옛 회차 링크는 그대로
   남으니 잃는 것은 없다).
2. 같은 주차를 듣는 **다른 반의 회차**가 그 시험을 가리키게 한다. 비어 있는
   자리만 채운다 — 이미 다른 시험이 걸린 회차는 안 건드린다.
"""

import django.db.models.deletion
from django.db import migrations, models


def lift_exams_to_weeks(apps, schema_editor):
    Exam = apps.get_model("grades", "Exam")
    ClassSession = apps.get_model("grades", "ClassSession")
    taken = set()
    for exam_id, week_id in (
        ClassSession.objects.filter(exam__isnull=False, course_week__isnull=False)
        .order_by("session_id")
        .values_list("exam_id", "course_week_id")
    ):
        if week_id in taken:
            continue
        if Exam.objects.filter(pk=exam_id).exclude(course_week=None).exists():
            continue
        Exam.objects.filter(pk=exam_id).update(course_week_id=week_id)
        taken.add(week_id)
    for exam_id, week_id in Exam.objects.exclude(course_week=None).values_list(
        "exam_id", "course_week_id"
    ):
        ClassSession.objects.filter(course_week_id=week_id, exam__isnull=True).update(
            exam_id=exam_id
        )


class Migration(migrations.Migration):

    dependencies = [
        ("curriculum", "0007_class_uses_payssam"),
        ("grades", "0016_confirm_attendance"),
    ]

    operations = [
        migrations.AddField(
            model_name="exam",
            name="course_week",
            field=models.OneToOneField(
                blank=True,
                db_column="course_week_id",
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="exam",
                to="curriculum.courseweek",
                verbose_name="커리 주차",
            ),
        ),
        migrations.RunPython(lift_exams_to_weeks, migrations.RunPython.noop),
    ]
