"""감독 자료는 녹음이 아니라 전사다 — `recording_path` → 전사 문서 참조·링크.

PRD 8-5 확정(전사+요약으로 감독, 녹화 없음)에 컬럼을 맞춘다. 미트에 오디오
전용 녹음이 없고 녹화도 꺼 두므로 **녹음 파일은 영원히 생기지 않는다** — 이름이
없는 것을 가리키고 있으면 다음 사람이 그 파일을 찾아 헤맨다.

RenameField 를 쓰는 이유: 값이 들어 있진 않지만(연동 전) Remove+Add 로 갈리면
같은 자리라는 사실이 히스토리에서 끊긴다.
"""
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("clinic", "0003_clinic_conference_provider_neutral"),
    ]

    operations = [
        migrations.RenameField(
            model_name="clinicevaluation",
            old_name="recording_path",
            new_name="transcript_ref",
        ),
        migrations.AlterField(
            model_name="clinicevaluation",
            name="transcript_ref",
            field=models.CharField(
                blank=True, max_length=200, null=True, verbose_name="전사 문서 참조 ID"
            ),
        ),
        migrations.AddField(
            model_name="clinicevaluation",
            name="transcript_url",
            field=models.CharField(
                blank=True, max_length=500, null=True, verbose_name="전사 문서 링크"
            ),
        ),
        migrations.AlterField(
            model_name="clinicevaluation",
            name="ai_summary",
            field=models.TextField(blank=True, null=True, verbose_name="AI 요약"),
        ),
    ]
