"""VideoGrant 지급 단위를 주차 → 영상으로 (2026-08-04 사용자 확정).

구 설계는 권한을 `course_week` 에 걸고 재생 판정이 영상의 course_week 와
맞춰봤다. 그러면 영상과 권한이 같은 칸을 공유해서, 관리자가 영상의 주차를
고치는 순간 그 주차 권한을 든 학생 전원이 못 보게 된다(실측: 영상 1건의
주차를 옮기면 활성 권한 51건이 끊김).

**데이터 이관**: 주차 권한 1행 → 그 주차의 `공개` 영상 1개당 1행으로 편다.
첫 영상은 기존 행을 재사용하고 나머지는 복제한다(이력 필드 전부 보존).
`공개` 영상이 하나도 없는 주차의 권한은 **삭제**한다 — 구 재생 판정도
`status=공개` 를 요구했으므로 그 권한으로는 애초에 아무것도 볼 수 없었다.

UQ 를 먼저 떼는 이유: 구 제약이 `attendance` 단독이라, 한 출석이 영상 수만큼
행을 낳는 순간 확장 INSERT 가 걸린다.

**스키마 조이기(0003)를 왜 갈랐나**: 같은 트랜잭션에서 행을 만든 뒤 ALTER TABLE 을
치면 postgres 가 "pending trigger events" 로 거부한다(지연 FK 검사가 남아 있다).
데이터 이관과 스키마 확정을 다른 마이그레이션 = 다른 트랜잭션으로 나눈다.
"""
from django.db import migrations, models
import django.db.models.deletion


def expand_to_videos(apps, schema_editor):
    """주차 권한을 그 주차의 공개 영상별 행으로 편다."""
    VideoGrant = apps.get_model("videos", "VideoGrant")
    Video = apps.get_model("videos", "Video")

    # 주차 → 공개 영상 id 목록 (한 번만 훑는다)
    published = {}
    for video in Video.objects.filter(status="공개", course_week__isnull=False).order_by(
        "sequence_no", "video_id"
    ):
        published.setdefault(video.course_week_id, []).append(video.video_id)

    copies = []
    for grant in VideoGrant.objects.all().iterator():
        video_ids = published.get(grant.course_week_id, [])
        if not video_ids:
            continue  # 아래 delete 단계에서 정리된다(video 가 NULL 로 남음)
        grant.video_id = video_ids[0]
        grant.save(update_fields=["video"])
        for extra_id in video_ids[1:]:
            copies.append(
                VideoGrant(
                    student_id=grant.student_id,
                    video_id=extra_id,
                    # course_week 는 이 마이그레이션 뒤에서 제거되지만 아직
                    # NOT NULL 이라 복제 행에도 채워야 INSERT 가 통과한다.
                    course_week_id=grant.course_week_id,
                    source=grant.source,
                    attendance_id=grant.attendance_id,
                    makeup_id=grant.makeup_id,
                    granted_by_id=grant.granted_by_id,
                    granted_at=grant.granted_at,
                    expires_at=grant.expires_at,
                    revoked_at=grant.revoked_at,
                    sync_status=grant.sync_status,
                    synced_at=grant.synced_at,
                )
            )
    if copies:
        VideoGrant.objects.bulk_create(copies, batch_size=500)


def drop_orphans(apps, schema_editor):
    """공개 영상이 없어 붙일 곳이 없던 권한을 지운다(구 설계에서도 무용지물)."""
    apps.get_model("videos", "VideoGrant").objects.filter(video__isnull=True).delete()


def noop_reverse(apps, schema_editor):
    """되돌리기 불가 — 편 행을 다시 뭉치면 어느 행이 원본인지 알 수 없다."""
    raise migrations.exceptions.IrreversibleError(
        "지급 단위 변경은 되돌릴 수 없다(편 행의 원본을 특정할 수 없음)."
    )


class Migration(migrations.Migration):
    # Django 는 새 FK 의 CREATE INDEX 를 마이그레이션 **끝**으로 미룬다
    # (schema editor 의 deferred_sql). 그래서 한 트랜잭션 안에서는 RunPython 이
    # 만든 행의 지연 FK 검사가 남은 채로 인덱스를 만들게 돼 postgres 가 거부한다
    # ("pending trigger events"). 연산마다 커밋되게 해 검사를 흘려보낸다.
    atomic = False

    dependencies = [("videos", "0001_initial")]

    operations = [
        # ① 구 UQ 해제 — attendance 단독이라 확장 INSERT 가 걸린다
        migrations.RemoveConstraint(
            model_name="videogrant", name="uq_video_grants_attendance"
        ),
        migrations.RemoveConstraint(
            model_name="videogrant", name="uq_video_grants_makeup"
        ),
        # ② video 를 NULL 허용으로 붙이고 데이터를 편다
        migrations.AddField(
            model_name="videogrant",
            name="video",
            field=models.ForeignKey(
                null=True,
                db_column="video_id",
                on_delete=django.db.models.deletion.PROTECT,
                related_name="video_grants",
                to="videos.video",
                verbose_name="지급 영상",
            ),
        ),
        migrations.RunPython(expand_to_videos, noop_reverse),
        migrations.RunPython(drop_orphans, noop_reverse),
    ]
