"""워크북 사진 업로드·열람 API 7차 슬라이스 테스트 (PRD 3.1.7·3.1.1·§4, 8-9 결정).

검증 축:
- 기능 키 게이트(FeatureRequired 워크북업로드): 조교 **프리셋 포함**·회수 delta 차단
- 업로드: 실제 파일 IO(임시 MEDIA_ROOT) — 스토리지 저장·DB엔 경로만(§6),
  OCR 3컬럼(recognized_*·match_status)은 업로드 시 전부 NULL(=매핑 대기),
  파일 검증(이미지 확장자·크기 상한·빈 파일·전량 검증 원자성)
- 매칭 수용 API: student_id 직접 지정(수동확정) / recognized_unique_id 기입 시
  원번+이름 대조(원번은 단독 UQ 아님 — 이름과 함께 매칭키): 성공=자동매칭,
  실패(이름 불일치·미존재·동일 원번+이름 중복)=불일치
- 관리자 목록: session_id·매핑 상태 필터(대기=NULL 포함), 미매핑 건 카운트
- 소비자 노출 규칙(§4): 확정(자동매칭·수동확정)만 노출 — 대기·불일치·인식실패
  미노출, 타학생 미노출, 학부모 자녀 소유 검증(404 존재 비노출),
  학생·학부모 동일 페이로드, 사진 URL 은 storage url() 경유
- 삭제: 업로더 본인 + 상위 직원(관리자·대표)만, 파일도 함께 제거(실검증)

업로드 시점의 student 는 **잠정 매핑**이다 — 설계 문서(도메인 2)가 student_id
NN 을 명시하므로 업로드 본문에 student_id 를 받되, 확정(자동매칭·수동확정)
전에는 소비자에게 노출되지 않는다(닫힘 기본값 — key_considerations §5).
"""
import datetime
import json
import shutil
import tempfile
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from apps.accounts.features import FeatureKey
from apps.accounts.models import Parent, ParentStudent, StaffFeatureGrant, User
from apps.accounts.unique_id import build_unique_id

from .models import Assignment, ClassSession, WorkbookSubmission
from .test_grade_report_api import make_student, make_user

ADMIN_WORKBOOK = "/api/admin/workbook"
UPLOAD_URL = "/api/admin/workbook/upload"
STUDENT_WORKBOOK = "/api/student/workbook"
PARENT_WORKBOOK = "/api/parent/workbook"

TEMP_MEDIA = tempfile.mkdtemp(prefix="lms-workbook-test-media-")

MS = WorkbookSubmission.MatchStatus


def tearDownModule():  # noqa: N802 — unittest 모듈 훅
    shutil.rmtree(TEMP_MEDIA, ignore_errors=True)


def make_image(name="workbook.jpg", content=b"\xff\xd8\xff\xe0fakejpegbytes"):
    return SimpleUploadedFile(name, content, content_type="image/jpeg")


class WorkbookFixtureMixin:
    """공용 픽스처 — 원번+이름 매칭키 검증용 학생 구성(동일 원번·동명 케이스 포함)."""

    @classmethod
    def setUpTestData(cls):
        # 학생: unique_id 는 단독 UQ 아님(accounts 설계) — 이름과 함께 매칭키
        cls.student_a = make_student("stu-wb-a", "김서연")
        cls.student_a.unique_id = "10001"
        cls.student_a.save(update_fields=["unique_id"])
        cls.student_b = make_student("stu-wb-b", "이민준")
        cls.student_b.unique_id = "10002"
        cls.student_b.save(update_fields=["unique_id"])
        # 동일 원번 20001 + 다른 이름 — 이름 대조로 판별되는 케이스
        cls.student_shared1 = make_student("stu-wb-s1", "박하나")
        cls.student_shared1.unique_id = "20001"
        cls.student_shared1.save(update_fields=["unique_id"])
        cls.student_shared2 = make_student("stu-wb-s2", "박두리")
        cls.student_shared2.unique_id = "20001"
        cls.student_shared2.save(update_fields=["unique_id"])
        # 동일 원번 30001 + 동명 — 대조로도 판별 불가(불일치) 케이스
        cls.student_dup1 = make_student("stu-wb-d1", "최중복")
        cls.student_dup1.unique_id = "30001"
        cls.student_dup1.save(update_fields=["unique_id"])
        cls.student_dup2 = make_student("stu-wb-d2", "최중복")
        cls.student_dup2.unique_id = "30001"
        cls.student_dup2.save(update_fields=["unique_id"])

        # 학부모: A 자녀 보유 / other 는 B 자녀 보유(소유 밖 404 검증 축)
        cls.parent_user = make_user("par-wb", User.Role.PARENT, name="김학부모")
        parent = Parent.objects.create(user=cls.parent_user, name="김학부모")
        ParentStudent.objects.create(parent=parent, student=cls.student_a)
        cls.other_parent_user = make_user("par-wb2", User.Role.PARENT)
        other = Parent.objects.create(user=cls.other_parent_user)
        ParentStudent.objects.create(parent=other, student=cls.student_b)

        # 직원: 조교(프리셋)·회수 조교·타 조교·관리자·대표
        cls.assistant = make_user("ast-wb", User.Role.ASSISTANT, name="업로드조교")
        cls.other_assistant = make_user("ast-wb2", User.Role.ASSISTANT, name="타조교")
        cls.revoked_assistant = make_user("ast-wb3", User.Role.ASSISTANT, name="회수조교")
        StaffFeatureGrant.objects.create(
            user=cls.revoked_assistant,
            feature_key=FeatureKey.WORKBOOK_UPLOAD,
            is_granted=False,
        )
        cls.admin = make_user("adm-wb", User.Role.ADMIN, name="관리자")
        cls.owner = make_user("own-wb", User.Role.OWNER, name="대표")

        cls.session1 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 15), session_no=3
        )
        cls.session2 = ClassSession.objects.create(
            session_date=datetime.date(2026, 7, 22), session_no=4
        )
        # 과제 수행 여부 연동(PRD 3.1.1) — session1 의 A 는 수행
        Assignment.objects.create(session=cls.session1, student=cls.student_a, done=True)

    def upload(self, files, student=None, session=None, extra=None):
        data = {"images": files}
        if student is not None:
            data["student_id"] = student.pk
        if session is not None:
            data["session_id"] = session.pk
        if extra:
            data.update(extra)
        return self.client.post(UPLOAD_URL, data)

    def make_submission(self, student, session=None, match_status=None, uploaded_by=None, **extra):
        """스토리지에 실제 파일을 만들고 제출 행 생성 — 목록·소비자·삭제 테스트용."""
        path = default_storage.save(
            "workbook/test-fixture.jpg", make_image(content=b"fixture-bytes")
        )
        return WorkbookSubmission.objects.create(
            student=student,
            session=session,
            image_path=path,
            match_status=match_status,
            uploaded_by=uploaded_by,
            **extra,
        )


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkbookUploadAccessTests(WorkbookFixtureMixin, TestCase):
    """기능 키 게이트 — 워크북업로드 (조교 프리셋 포함, PRD 2장 역할 정의)."""

    def test_anonymous_denied(self):
        self.assertEqual(self.upload([make_image()], self.student_a).status_code, 403)
        self.assertEqual(self.client.get(ADMIN_WORKBOOK).status_code, 403)

    def test_consumer_roles_denied(self):
        for user in (self.student_a.user, self.parent_user):
            self.client.force_login(user)
            self.assertEqual(self.upload([make_image()], self.student_a).status_code, 403)
            self.assertEqual(self.client.get(ADMIN_WORKBOOK).status_code, 403)

    def test_assistant_preset_allowed(self):
        """조교는 프리셋에 워크북업로드 포함 — delta 없이 허용."""
        self.client.force_login(self.assistant)
        self.assertEqual(self.upload([make_image()], self.student_a).status_code, 201)

    def test_assistant_revoked_delta_denied(self):
        self.client.force_login(self.revoked_assistant)
        self.assertEqual(self.upload([make_image()], self.student_a).status_code, 403)

    def test_admin_and_owner_allowed(self):
        for user in (self.admin, self.owner):
            self.client.force_login(user)
            self.assertEqual(self.upload([make_image()], self.student_a).status_code, 201)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkbookUploadTests(WorkbookFixtureMixin, TestCase):
    """POST /api/admin/workbook/upload — 실제 파일 IO·경로만 DB 저장(§6)."""

    def setUp(self):
        self.client.force_login(self.assistant)

    def test_upload_saves_file_and_creates_pending_submission(self):
        res = self.upload([make_image()], self.student_a, self.session1)
        self.assertEqual(res.status_code, 201)
        rows = res.json()["submissions"]
        self.assertEqual(len(rows), 1)
        submission = WorkbookSubmission.objects.get(pk=rows[0]["submission_id"])
        # 잠정 매핑 + OCR 3컬럼 NULL(=매핑 대기)
        self.assertEqual(submission.student_id, self.student_a.pk)
        self.assertEqual(submission.session_id, self.session1.pk)
        self.assertIsNone(submission.recognized_unique_id)
        self.assertIsNone(submission.recognized_name)
        self.assertIsNone(submission.match_status)
        self.assertEqual(submission.uploaded_by_id, self.assistant.pk)
        # DB엔 경로만(절대경로 금지) + 스토리지에 실제 파일 존재
        self.assertFalse(submission.image_path.startswith("/"))
        self.assertTrue(submission.image_path.startswith("workbook/"))
        self.assertTrue(default_storage.exists(submission.image_path))
        self.assertTrue((Path(TEMP_MEDIA) / submission.image_path).is_file())
        # 응답은 storage url() 경유 — 직접 경로 노출 대신
        self.assertEqual(rows[0]["image_url"], default_storage.url(submission.image_path))
        self.assertIsNone(rows[0]["match_status"])

    def test_upload_multiple_files(self):
        res = self.upload(
            [make_image("a.jpg"), make_image("b.png"), make_image("c.webp")],
            self.student_b,
        )
        self.assertEqual(res.status_code, 201)
        rows = res.json()["submissions"]
        self.assertEqual(len(rows), 3)
        for row in rows:
            submission = WorkbookSubmission.objects.get(pk=row["submission_id"])
            self.assertTrue(default_storage.exists(submission.image_path))
            self.assertIsNone(submission.session_id)  # session 은 선택 입력

    def test_upload_requires_student(self):
        self.assertEqual(self.upload([make_image()]).status_code, 400)
        self.assertEqual(
            self.upload([make_image()], extra={"student_id": "abc"}).status_code, 400
        )

    def test_upload_unknown_student_or_session_not_found(self):
        res = self.client.post(UPLOAD_URL, {"images": [make_image()], "student_id": 999999})
        self.assertEqual(res.status_code, 404)
        res = self.upload([make_image()], self.student_a, extra={"session_id": 999999})
        self.assertEqual(res.status_code, 404)

    def test_upload_requires_image_files(self):
        res = self.client.post(UPLOAD_URL, {"student_id": self.student_a.pk})
        self.assertEqual(res.status_code, 400)

    def test_upload_rejects_non_image_extension(self):
        before = WorkbookSubmission.objects.count()
        res = self.upload([make_image("report.pdf")], self.student_a)
        self.assertEqual(res.status_code, 400)
        # 전량 검증 원자성 — 유효 파일이 섞여 있어도 전체 거부·저장 없음
        res = self.upload([make_image("ok.jpg"), make_image("bad.exe")], self.student_a)
        self.assertEqual(res.status_code, 400)
        self.assertEqual(WorkbookSubmission.objects.count(), before)

    def test_upload_rejects_oversize_and_empty(self):
        empty = make_image("empty.jpg", content=b"")
        self.assertEqual(self.upload([empty], self.student_a).status_code, 400)
        oversize = make_image("big.jpg", content=b"x" * (10 * 1024 * 1024 + 1))
        self.assertEqual(self.upload([oversize], self.student_a).status_code, 400)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkbookAdminListTests(WorkbookFixtureMixin, TestCase):
    """GET /api/admin/workbook?session_id=&status= — 보정 화면 근거."""

    def setUp(self):
        self.client.force_login(self.admin)
        self.pending = self.make_submission(
            self.student_a, self.session1, uploaded_by=self.assistant
        )
        self.auto = self.make_submission(
            self.student_a,
            self.session1,
            match_status=MS.AUTO_MATCHED,
            recognized_unique_id="10001",
            recognized_name="김서연",
        )
        self.manual = self.make_submission(
            self.student_b, self.session2, match_status=MS.MANUAL_CONFIRMED
        )
        self.mismatch = self.make_submission(
            self.student_b, self.session2, match_status=MS.MISMATCH
        )
        self.ocr_failed = self.make_submission(self.student_b, None, match_status=MS.OCR_FAILED)

    def test_list_rows_and_unmatched_count(self):
        res = self.client.get(ADMIN_WORKBOOK)
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertEqual(body["total_count"], 5)
        # 미매핑 = 확정(자동매칭·수동확정) 아닌 건 — 대기·불일치·인식실패
        self.assertEqual(body["unmatched_count"], 3)
        rows = {r["submission_id"]: r for r in body["submissions"]}
        self.assertEqual(len(rows), 5)
        row = rows[self.auto.pk]
        self.assertEqual(
            row["student"],
            {
                "student_id": self.student_a.pk,
                "name": "김서연",
                "unique_id": "10001",
            },
        )
        self.assertEqual(
            row["session"],
            {
                "session_id": self.session1.pk,
                "session_date": "2026-07-15",
                "session_no": 3,
            },
        )
        self.assertEqual(row["image_url"], default_storage.url(self.auto.image_path))
        self.assertEqual(row["recognized_unique_id"], "10001")
        self.assertEqual(row["recognized_name"], "김서연")
        self.assertEqual(row["match_status"], "자동매칭")
        pending_row = rows[self.pending.pk]
        self.assertIsNone(pending_row["match_status"])
        self.assertEqual(
            pending_row["uploaded_by"],
            {"user_id": self.assistant.pk, "name": "업로드조교"},
        )
        self.assertIsNone(rows[self.ocr_failed.pk]["session"])

    def test_list_filter_by_status(self):
        res = self.client.get(ADMIN_WORKBOOK, {"status": "대기"})
        self.assertEqual(
            [r["submission_id"] for r in res.json()["submissions"]], [self.pending.pk]
        )
        res = self.client.get(ADMIN_WORKBOOK, {"status": "불일치"})
        self.assertEqual(
            [r["submission_id"] for r in res.json()["submissions"]], [self.mismatch.pk]
        )
        self.assertEqual(self.client.get(ADMIN_WORKBOOK, {"status": "이상한값"}).status_code, 400)

    def test_list_filter_by_session(self):
        res = self.client.get(ADMIN_WORKBOOK, {"session_id": self.session2.pk})
        body = res.json()
        self.assertEqual(
            {r["submission_id"] for r in body["submissions"]},
            {self.manual.pk, self.mismatch.pk},
        )
        # 미매핑 카운트는 session 필터 반영(해당 회차 보정 잔량) — status 필터와 무관
        self.assertEqual(body["unmatched_count"], 1)
        self.assertEqual(self.client.get(ADMIN_WORKBOOK, {"session_id": "abc"}).status_code, 400)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkbookMatchTests(WorkbookFixtureMixin, TestCase):
    """PATCH /api/admin/workbook/{id}/match — 인식 결과 수용·수동확정 (8-9 결정)."""

    def setUp(self):
        self.client.force_login(self.admin)
        self.submission = self.make_submission(self.student_a, self.session1)

    def patch_match(self, submission_id, body):
        return self.client.patch(
            f"{ADMIN_WORKBOOK}/{submission_id}/match",
            data=json.dumps(body),
            content_type="application/json",
        )

    def test_manual_confirm_sets_student(self):
        res = self.patch_match(self.submission.pk, {"student_id": self.student_b.pk})
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.student_id, self.student_b.pk)
        self.assertEqual(self.submission.match_status, MS.MANUAL_CONFIRMED)
        self.assertEqual(res.json()["submission"]["match_status"], "수동확정")

    def test_auto_match_by_unique_id_and_name(self):
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": "10002", "recognized_name": "이민준"},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.student_id, self.student_b.pk)
        self.assertEqual(self.submission.match_status, MS.AUTO_MATCHED)
        self.assertEqual(self.submission.recognized_unique_id, "10002")
        self.assertEqual(self.submission.recognized_name, "이민준")

    def test_auto_match_accepts_full_length_unique_id(self):
        """인식 컬럼은 **원번이 가질 수 있는 길이**를 다 담아야 한다(2026-07-29 개정).

        원번이 `{이름}{뒷4}` 가 되면서 이름 길이만큼 길어졌다. 지면에 들어오는
        것이 곧 원번이고 화면도 원번 전체를 보내므로(`apply_recognition` 이
        전체를 비교한다), 긴 이름 학생 한 명이 이 화면을 500 으로 떨어뜨리면 안 된다.
        """
        long_name = "무하마드알리"  # 6자 → 원번 10자
        student = make_student("stu-wb-long", long_name)
        student.unique_id = build_unique_id(long_name, "01012344821")
        student.save(update_fields=["unique_id"])
        self.assertGreater(len(student.unique_id), 5)

        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": student.unique_id, "recognized_name": long_name},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.student_id, student.pk)
        self.assertEqual(self.submission.match_status, MS.AUTO_MATCHED)
        self.assertEqual(self.submission.recognized_unique_id, student.unique_id)

    def test_auto_match_strips_whitespace(self):
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": " 10002 ", "recognized_name": " 이민준 "},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.AUTO_MATCHED)
        self.assertEqual(self.submission.recognized_unique_id, "10002")

    def test_auto_match_shared_unique_id_resolved_by_name(self):
        """원번은 단독 UQ 아님 — 동일 원번 2명도 이름 대조로 판별(설계 원칙)."""
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": "20001", "recognized_name": "박두리"},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.student_id, self.student_shared2.pk)
        self.assertEqual(self.submission.match_status, MS.AUTO_MATCHED)

    def test_auto_match_name_mismatch(self):
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": "10002", "recognized_name": "김서연"},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.MISMATCH)
        self.assertEqual(self.submission.student_id, self.student_a.pk)  # 잠정 매핑 유지
        self.assertEqual(self.submission.recognized_unique_id, "10002")  # 인식값은 보존(보정 근거)
        self.assertEqual(self.submission.recognized_name, "김서연")

    def test_auto_match_unknown_unique_id(self):
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": "99999", "recognized_name": "김서연"},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.MISMATCH)

    def test_auto_match_duplicate_pair_mismatch(self):
        """동일 원번+동명 2명 — 대조로 판별 불가 → 불일치(수동확정으로만 보정)."""
        res = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": "30001", "recognized_name": "최중복"},
        )
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.MISMATCH)

    def test_duplicate_unique_id_falls_to_the_admin(self):
        """원번이 겹치면 **관리자가 고른다** — 2026-07-29 확정의 실제 경로.

        동명이인 + 같은 뒷4자리는 원번이 같다(접미사로 해소하지 않는다). 지면에
        적힌 값만으로는 둘을 못 가르므로 자동매칭이 서지 않고, 관리자가 학생을
        지목해 수동확정한다.
        """
        shared = build_unique_id("최중복", "01011110001")
        for student in (self.student_dup1, self.student_dup2):
            student.unique_id = shared
            student.save(update_fields=["unique_id"])

        recognized = self.patch_match(
            self.submission.pk,
            {"recognized_unique_id": shared, "recognized_name": "최중복"},
        )
        self.assertEqual(recognized.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.MISMATCH)

        chosen = self.patch_match(
            self.submission.pk, {"student_id": self.student_dup2.pk}
        )
        self.assertEqual(chosen.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.student_id, self.student_dup2.pk)
        self.assertEqual(self.submission.match_status, MS.MANUAL_CONFIRMED)

    def test_auto_match_without_name_mismatch(self):
        """이름 없이 원번 단독으론 확정하지 않는다 — 이름과 함께 매칭키."""
        res = self.patch_match(self.submission.pk, {"recognized_unique_id": "10002"})
        self.assertEqual(res.status_code, 200)
        self.submission.refresh_from_db()
        self.assertEqual(self.submission.match_status, MS.MISMATCH)
        self.assertEqual(self.submission.recognized_unique_id, "10002")

    def test_requires_exactly_one_mode(self):
        both = {"student_id": self.student_b.pk, "recognized_unique_id": "10002"}
        self.assertEqual(self.patch_match(self.submission.pk, both).status_code, 400)
        self.assertEqual(self.patch_match(self.submission.pk, {}).status_code, 400)
        self.assertEqual(
            self.patch_match(self.submission.pk, {"recognized_unique_id": "  "}).status_code,
            400,
        )
        self.assertEqual(
            self.patch_match(self.submission.pk, {"student_id": "abc"}).status_code, 400
        )

    def test_unknown_student_not_found(self):
        res = self.patch_match(self.submission.pk, {"student_id": 999999})
        self.assertEqual(res.status_code, 404)

    def test_unknown_submission_not_found(self):
        res = self.patch_match(999999, {"student_id": self.student_b.pk})
        self.assertEqual(res.status_code, 404)

    def test_consumer_roles_denied(self):
        for user in (self.student_a.user, self.parent_user):
            self.client.force_login(user)
            res = self.patch_match(self.submission.pk, {"student_id": self.student_b.pk})
            self.assertEqual(res.status_code, 403)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class WorkbookDeleteTests(WorkbookFixtureMixin, TestCase):
    """DELETE /api/admin/workbook/{id} — 업로더 본인 + 상위 직원, 파일도 함께 제거."""

    def setUp(self):
        self.submission = self.make_submission(
            self.student_a, self.session1, uploaded_by=self.assistant
        )

    def delete(self, submission_id):
        return self.client.delete(f"{ADMIN_WORKBOOK}/{submission_id}")

    def test_uploader_deletes_row_and_file(self):
        path = self.submission.image_path
        self.assertTrue(default_storage.exists(path))
        self.client.force_login(self.assistant)
        self.assertEqual(self.delete(self.submission.pk).status_code, 204)
        self.assertFalse(WorkbookSubmission.objects.filter(pk=self.submission.pk).exists())
        self.assertFalse(default_storage.exists(path))
        self.assertFalse((Path(TEMP_MEDIA) / path).exists())

    def test_other_assistant_denied(self):
        """업로더 아닌 조교는 남의 업로드를 지울 수 없다 — 본인 또는 상위 직원만."""
        self.client.force_login(self.other_assistant)
        self.assertEqual(self.delete(self.submission.pk).status_code, 403)
        self.assertTrue(WorkbookSubmission.objects.filter(pk=self.submission.pk).exists())
        self.assertTrue(default_storage.exists(self.submission.image_path))

    def test_admin_and_owner_can_delete(self):
        for user in (self.admin, self.owner):
            submission = self.make_submission(self.student_a, uploaded_by=self.assistant)
            self.client.force_login(user)
            self.assertEqual(self.delete(submission.pk).status_code, 204)
            self.assertFalse(WorkbookSubmission.objects.filter(pk=submission.pk).exists())

    def test_unknown_submission_not_found(self):
        self.client.force_login(self.admin)
        self.assertEqual(self.delete(999999).status_code, 404)

    def test_consumer_roles_denied(self):
        for user in (self.student_a.user, self.parent_user):
            self.client.force_login(user)
            self.assertEqual(self.delete(self.submission.pk).status_code, 403)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class StudentWorkbookViewTests(WorkbookFixtureMixin, TestCase):
    """GET /api/student/workbook — 내 것·확정만(§4 노출 규칙)."""

    def setUp(self):
        self.auto = self.make_submission(
            self.student_a, self.session1, match_status=MS.AUTO_MATCHED, performance_grade="A"
        )
        self.manual = self.make_submission(
            self.student_a, self.session2, match_status=MS.MANUAL_CONFIRMED
        )
        # 미노출 4종: 대기·불일치·인식실패·타학생 확정
        self.make_submission(self.student_a, self.session1)
        self.make_submission(self.student_a, self.session1, match_status=MS.MISMATCH)
        self.make_submission(self.student_a, None, match_status=MS.OCR_FAILED)
        self.make_submission(self.student_b, self.session1, match_status=MS.AUTO_MATCHED)
        self.client.force_login(self.student_a.user)

    def test_only_my_confirmed_submissions_exposed(self):
        res = self.client.get(STUDENT_WORKBOOK)
        self.assertEqual(res.status_code, 200)
        # 최근 회차 우선(7/22 수동확정 → 7/15 자동매칭) — 대기·불일치·인식실패·타학생 미노출
        self.assertEqual(
            [r["submission_id"] for r in res.json()["workbooks"]],
            [self.manual.pk, self.auto.pk],
        )

    def test_payload_fields_and_assignment_link(self):
        rows = {
            r["submission_id"]: r for r in self.client.get(STUDENT_WORKBOOK).json()["workbooks"]
        }
        row = rows[self.auto.pk]
        self.assertEqual(
            row["session"],
            {
                "session_id": self.session1.pk,
                "session_date": "2026-07-15",
                "session_no": 3,
            },
        )
        # 사진 URL 은 storage url() 경유 — 직접 경로 노출 대신
        self.assertEqual(row["image_url"], default_storage.url(self.auto.image_path))
        self.assertEqual(row["performance_grade"], "A")
        self.assertIs(row["assignment_done"], True)  # session1 과제 수행 기록(PRD 3.1.1)
        self.assertIsNone(rows[self.manual.pk]["assignment_done"])  # 기록 없음 = null
        self.assertIn("uploaded_at", row)
        # 학생 페이로드에는 인식·매핑 내부 정보를 내리지 않는다
        self.assertNotIn("recognized_unique_id", row)
        self.assertNotIn("match_status", row)

    def test_role_gate(self):
        self.client.logout()
        self.assertEqual(self.client.get(STUDENT_WORKBOOK).status_code, 403)
        self.client.force_login(self.assistant)
        self.assertEqual(self.client.get(STUDENT_WORKBOOK).status_code, 403)


@override_settings(MEDIA_ROOT=TEMP_MEDIA)
class ParentWorkbookViewTests(WorkbookFixtureMixin, TestCase):
    """GET /api/parent/workbook?student_id= — 자녀 소유 검증·학생과 동일 페이로드."""

    def setUp(self):
        self.auto = self.make_submission(
            self.student_a, self.session1, match_status=MS.AUTO_MATCHED
        )
        self.make_submission(self.student_a, self.session1)  # 대기 — 미노출

    def test_same_payload_as_student(self):
        """PRD 3.1.1 리포트 '워크북 사진 링크' 데이터 원천 — 학생 응답과 동일."""
        self.client.force_login(self.student_a.user)
        student_body = self.client.get(STUDENT_WORKBOOK).json()
        self.client.force_login(self.parent_user)
        res = self.client.get(PARENT_WORKBOOK, {"student_id": self.student_a.pk})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json(), student_body)
        self.assertEqual(
            [r["submission_id"] for r in res.json()["workbooks"]], [self.auto.pk]
        )

    def test_default_child_without_param(self):
        self.client.force_login(self.parent_user)
        res = self.client.get(PARENT_WORKBOOK)
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r["submission_id"] for r in res.json()["workbooks"]], [self.auto.pk])

    def test_other_child_denied(self):
        """소유 밖 자녀는 존재 여부와 무관하게 404(§4 존재 비노출 — 2차 선례)."""
        self.client.force_login(self.parent_user)
        res = self.client.get(PARENT_WORKBOOK, {"student_id": self.student_b.pk})
        self.assertEqual(res.status_code, 404)

    def test_invalid_student_id(self):
        self.client.force_login(self.parent_user)
        self.assertEqual(self.client.get(PARENT_WORKBOOK, {"student_id": "abc"}).status_code, 400)

    def test_role_gate(self):
        self.client.force_login(self.student_a.user)
        self.assertEqual(self.client.get(PARENT_WORKBOOK).status_code, 403)
