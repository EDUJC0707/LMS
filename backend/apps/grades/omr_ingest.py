"""스캔 PDF 한 묶음 → 판독·매칭·저장 (PRD 3.1.1).

## 페이지를 다시 그리지 않는다

스캐너가 만든 PDF 는 페이지마다 JPEG 를 통째로 품고 있다. 그 스트림을 그대로
꺼내면 **픽셀이 원본과 바이트 단위로 같다** — 격자 보정을 잰 그 픽셀이다.
래스터라이즈하면 DPI·리샘플링이 개입해 보정을 다시 해야 한다.

실측(65쪽 24MB): 추출 0.01초. 판독까지 합쳐 한 묶음 약 1.5초라 **요청 안에서
끝난다** — 그래서 Celery 를 붙이지 않았다.

# ponytail: 동기 처리. 한 묶음이 수백 쪽이 되거나 렌더링이 끼면 태스크로 옮긴다.

## 장의 정체성은 파일 내용이다

스캔에는 일련번호가 없으므로 경로를 **페이지 바이트의 내용 주소**로 발급한다.
같은 PDF 를 두 번 올리거나 중간에 끊겨 다시 올려도 같은 행으로 수렴한다
(`omr_store` 멱등 계약).
"""
import hashlib

import cv2
import numpy as np
import pypdf
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from apps.accounts.models import Student

from . import omr_match, omr_store
from .omr import sheet


def ingest_pdf(exam, pdf, question_count):
    """PDF 파일객체 → 저장 결과 요약.

    문항 수는 **그 시험이 실제로 쓰는 수**다(카드는 20줄이지만 16문항 회차가
    있다). 안 쓴 줄을 넣으면 흐린 장에서 인쇄 글리프가 답으로 승격된다.
    """
    roster = list(Student.objects.select_related("user").all())
    summary = {"pages": 0, "read": 0, "held": 0, "matched": 0, "needs_review": 0}
    sheets = []
    for page_no, image_bytes in enumerate(page_images(pdf), start=1):
        summary["pages"] += 1
        path = _store_scan(exam, image_bytes)
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        reading = sheet.read_sheet(image, question_count)
        if reading.held:
            summary["held"] += 1
            row, _ = omr_store.store_sheet(exam, path, None)
        else:
            summary["read"] += 1
            student, status = omr_match.match_sheet(reading.name, reading.phone, roster=roster)
            if student is not None:
                summary["matched"] += 1
            else:
                summary["needs_review"] += 1
            row, _ = omr_store.store_sheet(
                exam,
                path,
                reading.answers,
                student=student,
                match_status=status,
                recognized_matching_key=reading.matching_key,
                recognized_name=reading.name,
            )
        sheets.append({"page": page_no, "sheet_id": row.pk, "held": reading.held})
    summary["sheets"] = sheets
    return summary


def page_images(pdf):
    """페이지마다 품고 있는 이미지 스트림을 그대로 내놓는다(재인코딩 없음).

    한 페이지에 이미지가 여럿이면 제일 큰 것을 쓴다 — 스캔본은 전면 이미지가
    하나지만, 로고 따위가 섞인 PDF 를 만나도 넘어지지 않게.
    """
    for page in pypdf.PdfReader(pdf).pages:
        best = None
        resources = page.get("/Resources") or {}
        for name in resources.get("/XObject", {}) or {}:
            obj = resources["/XObject"][name].get_object()
            if obj.get("/Subtype") != "/Image":
                continue
            data = obj.get_data()
            if best is None or len(data) > len(best):
                best = data
        if best is not None:
            # 이 스캐너의 JPEG 는 끝표지 앞에 615~621 바이트를 덧붙여 libjpeg 가
            # 장마다 경고를 뱉는다. 스트림 자체는 FFD9 로 정확히 끝나므로 잘라낼
            # 것이 없고, 디코드도 정상이다 — 경고는 그냥 둔다.
            yield best


def _store_scan(exam, image_bytes):
    """내용 주소로 저장하고 경로를 돌려준다. 같은 바이트면 다시 쓰지 않는다."""
    digest = hashlib.sha256(image_bytes).hexdigest()[:24]
    path = f"omr/{exam.pk}/{digest}.jpg"
    if not default_storage.exists(path):
        default_storage.save(path, ContentFile(image_bytes))
    return path
