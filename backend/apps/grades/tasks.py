"""OMR 스캔 묶음 판독 Celery 태스크.

## 왜 태스크인가 — 시간이 아니라 요청 점유다

한 묶음(65쪽)은 추출 0.01초 + 판독 2.1초라 **요청 안에서도 끝난다.** 그래도
태스크로 미는 이유는 그 2초 동안 gunicorn 워커 하나가 통째로 묶이고, 업로드가
27MB 라 그 앞뒤로 전송 시간이 더 붙기 때문이다. 판독은 CPU 를 꽉 쓰는 일이라
웹 프로세스와 나눠 두는 편이 낫다.

`clinic`·`notifications` 가 이미 태스크를 갖고 있어 워커는 어차피 뜬다 —
여기 얹는 비용은 사실상 없다.

## 재시도하지 않는다

발송과 다르다. 판독은 외부에 의존하지 않아 **다시 걸어도 같은 결과**다.
실패한다면 PDF 가 깨졌거나 코드가 틀린 것이고, 둘 다 재시도로 낫지 않는다.
저장은 멱등이라(`omr_store`) 사람이 다시 올리는 것이 안전한 복구 경로다.
"""
import logging

from celery import shared_task
from django.core.files.storage import default_storage

from . import omr_ingest
from .models import Exam

logger = logging.getLogger(__name__)


@shared_task(name="grades.ingest_omr_batch")
def ingest_omr_batch(exam_id, pdf_path, question_count):
    """업로드된 스캔 PDF 한 묶음을 판독·매칭·저장하고 요약을 돌려준다.

    PDF 는 뷰가 스토리지에 올려 두고 경로만 넘긴다 — 27MB 를 브로커에 실으면
    Redis 가 메시지 큐가 아니라 파일 서버가 된다.
    """
    exam = Exam.objects.get(pk=exam_id)
    with default_storage.open(pdf_path, "rb") as pdf:
        summary = omr_ingest.ingest_pdf(exam, pdf, question_count)
    logger.info(
        "omr batch read: exam=%s pages=%s held=%s matched=%s",
        exam_id, summary["pages"], summary["held"], summary["matched"],
    )
    # 원본 PDF 는 장별 이미지로 이미 다 들어갔다 — 27MB 를 두 벌 두지 않는다.
    default_storage.delete(pdf_path)
    return summary
