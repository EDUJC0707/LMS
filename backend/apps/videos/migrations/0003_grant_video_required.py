"""0002 의 데이터 이관을 받아 스키마를 확정한다.

0002 와 갈라 둔 이유는 그쪽 docstring 참조 — 같은 트랜잭션에서 INSERT 뒤
ALTER TABLE 이 "pending trigger events" 로 막힌다.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    # 0002 가 만든 행의 지연 FK 검사가 남아 있어 한 트랜잭션 안에서는
    # ALTER/CREATE INDEX 가 "pending trigger events" 로 거부된다.
    # 연산마다 자기 트랜잭션을 쓰게 해 검사를 흘려보낸다.
    atomic = False

    dependencies = [("videos", "0002_grant_per_video")]

    operations = [
        migrations.AlterField(
            model_name="videogrant",
            name="video",
            field=models.ForeignKey(
                db_column="video_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="video_grants",
                to="videos.video",
                verbose_name="지급 영상",
            ),
        ),
        migrations.RemoveField(model_name="videogrant", name="course_week"),
        migrations.AddConstraint(
            model_name="videogrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("attendance__isnull", False)),
                fields=("attendance", "video"),
                name="uq_video_grants_attendance_video",
            ),
        ),
        migrations.AddConstraint(
            model_name="videogrant",
            constraint=models.UniqueConstraint(
                condition=models.Q(("makeup__isnull", False)),
                fields=("makeup", "video"),
                name="uq_video_grants_makeup_video",
            ),
        ),
    ]
