"""스캔 PDF 한 묶음 → 판독·매칭·저장 (PRD 3.1.1).

## 지면이 두 가지다

`exams.kind` 가 어느 카드인지 정한다. 지면에서는 못 읽는다 — 두 카드 다
마커 네 점이 같은 자리에 있고, 상단 제목은 마킹이 아니라 인쇄 글자다.

- **미니테스트** — 우리 답안 카드. 문항별 마킹을 읽고 정답 키로 채점한다
- **모의고사** — 모의고사와 함께 오는 `성적 조사 카드`. 문항이 없고 학생이
  학교에서 본 점수를 스스로 적어 낸다. 읽는 것은 점수 두 자리뿐이다.
  **버블을 하나도 안 칠한 장은 손글씨 OCR 로 한 번 더 본다**(`grades.ocr`) —
  실물 94장 중 34장이 그런 장이었고, 그중 20장을 그렇게 건졌다

매칭(이름+전화 뒷4)과 저장 멱등 계약은 둘이 같다.

## 페이지를 다시 그리지 않는다

스캐너가 만든 PDF 는 페이지마다 JPEG 를 통째로 품고 있다. 그 스트림을 그대로
꺼내면 **픽셀이 원본과 바이트 단위로 같다** — 격자 보정을 잰 그 픽셀이다.
래스터라이즈하면 DPI·리샘플링이 개입해 보정을 다시 해야 한다.

실측(65쪽 24MB): 추출 0.01초. 판독까지 합쳐 한 묶음 약 2초다. 요청 안에서도
끝나지만 그동안 웹 워커가 통째로 묶이므로 호출은 Celery 태스크가 한다
(`tasks.ingest_omr_batch`). 이 함수 자체는 동기이고 태스크를 모른다.

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

from . import ocr, omr_match, omr_store
from .models import Exam
from .omr import sheet


def ingest_pdf(exam, pdf, question_count):
    """PDF 파일객체 → 저장 결과 요약.

    문항 수는 **그 시험이 실제로 쓰는 수**다(카드는 20줄이지만 16문항 회차가
    있다). 안 쓴 줄을 넣으면 흐린 장에서 인쇄 글리프가 답으로 승격된다.
    모의고사는 지면이 아예 다른 카드(성적 조사 카드)라 문항 수를 안 쓴다.
    """
    roster = list(Student.objects.select_related("user").all())
    # holds 는 보류 사유별 장수다. 실물에서 "마킹 없음"이 34/94 였다 — 사람에게
    # 알려 줄 값이 "보류 34장"이 아니라 "34명이 버블을 안 칠했다"이기 때문이다.
    summary = {"pages": 0, "read": 0, "held": 0, "matched": 0, "needs_review": 0, "holds": {}}
    survey = exam.kind == Exam.Kind.MOCK
    sheets = []
    for page_no, image_bytes in enumerate(page_images(pdf), start=1):
        summary["pages"] += 1
        path = _store_scan(exam, image_bytes)
        image = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_GRAYSCALE)
        reading = (
            sheet.read_survey(image) if survey else sheet.read_sheet(image, question_count)
        )
        if survey and reading.held == sheet.CARD_UNMARKED:
            reading = _rescue_by_ocr(image, reading)
        if reading.held:
            summary["held"] += 1
            summary["holds"][reading.held] = summary["holds"].get(reading.held, 0) + 1
            row, _ = (
                omr_store.store_survey(exam, path, None)
                if survey
                else omr_store.store_sheet(exam, path, None)
            )
        else:
            summary["read"] += 1
            student, status = omr_match.match_sheet(reading.name, reading.phone, roster=roster)
            if student is not None:
                summary["matched"] += 1
            else:
                summary["needs_review"] += 1
            identity = {
                "student": student,
                "match_status": status,
                "recognized_matching_key": reading.matching_key,
                "recognized_name": reading.name,
            }
            row, _ = (
                omr_store.store_survey(exam, path, reading.score, **identity)
                if survey
                else omr_store.store_sheet(exam, path, reading.answers, **identity)
            )
        sheets.append({"page": page_no, "sheet_id": row.pk, "held": reading.held})
    summary["sheets"] = sheets
    return summary


def _rescue_by_ocr(image, reading):
    """버블이 없는 조사 카드 — 손글씨 점수만 OCR 로 건진다(`grades.ocr` 계약).

    건져도 **신원은 여전히 없다.** 성명·수험번호 격자도 비어 있어 대조에 넣을 값이
    아무것도 없으므로 `비정상`으로 떨어진다(`omr_match.resolve` 첫 분기) — 점수를
    든 채 보정 화면에 서고, 조교는 학생만 고르면 된다.

    `비정상`은 판독을 못 믿는 장과 같은 칸이지만 여기서는 **점수가 채워져 있어**
    화면에서 갈린다. 갈라 두려면 상태값을 새로 만들어야 하는데, 조교가 할 일이
    (지면 보고 학생 고르기)로 같아서 두지 않았다.
    """
    score = ocr.read_score(sheet.score_box_image(image, reading.frame))
    if score is None:
        return reading
    return sheet.SurveyReading(score=score, frame=reading.frame)


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
