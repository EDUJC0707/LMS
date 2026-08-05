"""화상 축을 업체 중립으로 — `meet_url` → provider 값 + 중립 참조 + 참가 URL.

key_considerations §4(추상화 경계) 계약. 컬럼 이름이 업체(구글 미트)를 가리키고
있어서 화상 업체를 바꾸면 스키마가 따라 움직여야 했다. videos.Video·payments.Payment
와 같은 3분할(provider 값 / 중립 참조 / 사용 값)로 정렬한다.

**RenameField 를 쓰는 이유**: Remove+Add 로 갈리면 이미 배정된 링크가 통째로
사라진다(시드·개발 DB 에 실제로 값이 있다).
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clinic", "0002_clinic_slot_capacity_fixed_one"),
    ]

    operations = [
        migrations.RenameField(
            model_name="clinicrequest",
            old_name="meet_url",
            new_name="conference_url",
        ),
        migrations.AlterField(
            model_name="clinicrequest",
            name="conference_url",
            field=models.CharField(
                blank=True, max_length=500, null=True, verbose_name="화상 참가 링크"
            ),
        ),
        migrations.AddField(
            model_name="clinicrequest",
            name="conference_provider",
            field=models.CharField(
                blank=True,
                choices=[("google_meet", "Google Meet")],
                max_length=20,
                null=True,
                verbose_name="화상 제공자",
            ),
        ),
        migrations.AddField(
            model_name="clinicrequest",
            name="conference_ref",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="화상 참조 ID"
            ),
        ),
    ]
