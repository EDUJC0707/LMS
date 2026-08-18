"""seed_demo — **데모·개발 전용** 시드 데이터 생성 커맨드.

목적: 개발자가 브라우저(bare 프런트)에서 백엔드 API 전 기능을 눌러보며
공부·테스트할 수 있는 데이터 상태를 한 번에 만든다.

**운영 사용 금지.** 데모 편의를 위해 보안 기본값을 의도적으로 낮춘다:
- 모든 계정 비밀번호가 test1234 로 동일하고 응답·출력에 평문 노출된다.
- must_change_password=False — 최초 로그인 비밀번호 변경 강제(PRD 3.1.5)를
  꺼서 로그인 즉시 모든 화면을 테스트할 수 있게 한다.

**멱등 — 초기화 후 재생성.** 재실행하면 LMS 도메인 테이블(계정 포함)을
전부 비우고 같은 시드(고정 RNG)로 다시 만든다. 스킵 방식이 아니라 리셋
방식을 택한 이유: 이 커맨드의 용도가 "데이터를 이리저리 조작해 본 뒤
깨끗한 기준 상태로 되돌리는 것"이라서다. 날짜는 실행일 기준 상대 배치
(이번 주 = 4주차)라 언제 실행해도 게이팅·마감 시연이 성립한다.

파생 데이터(영상 권한·상담 대기열)는 직접 INSERT 하지 않고 실서비스
(`grades.attendance_admin.apply_entries`)를 경유해 만든다 — 출결 SSOT
트리거가 실제로 작동한 결과를 화면에서 그대로 확인할 수 있다.
"""
import base64
import datetime
import random
import textwrap
import unicodedata

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.accounts.login_id import (
    issue_parent_login_id,
    issue_staff_login_id,
    issue_student_login_id,
)
from apps.accounts.matching_key import build_matching_key
from apps.accounts.models import Parent, ParentStudent, StaffFeatureGrant, Student, User
from apps.boards.models import AbsenceCounseling, ParentCounselRequest, Post, PostComment
from apps.clinic.models import (
    ClinicEligibility,
    ClinicEvalCriteria,
    ClinicEvaluation,
    ClinicEvaluationItem,
    ClinicRequest,
    ClinicSlot,
)
from apps.curriculum.models import (
    Class,
    Course,
    CourseEnrollment,
    CourseWeek,
    Subject,
    WeekDayPlan,
)
from apps.grades import attendance_admin
from apps.grades import media as grades_media
from apps.grades.models import (
    AnswerSheet,
    Assignment,
    Attendance,
    ClassSession,
    Exam,
    Question,
    QuestionBankItem,
    QuestionSimilarMap,
    Score,
    SheetAnswer,
    WeaknessCheckPdf,
    WorkbookSubmission,
)
from apps.notifications.models import Notification
from apps.payments.models import Order, Payment, Product
from apps.videos.models import MakeupGrant, Video, VideoGrant, WatermarkTamper

PASSWORD = "test1234"  # 데모 전용 공통 비밀번호(모듈 docstring)

_STAFF_ROLES = (User.Role.OWNER, User.Role.ADMIN, User.Role.ASSISTANT)


def _pad(text, width):
    """한글 폭(2칸)을 반영한 열 정렬 — str.ljust 는 글자 수만 세어 어긋난다."""
    used = sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)
    return text + " " * max(width - used, 1)

_SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
_GIVEN = [
    "하늘", "서준", "지우", "민준", "서연", "도윤", "예린", "시우", "지안", "주원",
    "하린", "은우", "수아", "지호", "다은", "건우", "소율", "현우", "가은", "우진",
    "나윤", "선우", "채원", "정민", "유나", "태윤", "세아", "준서", "예준", "다인",
]
_SCHOOLS = ["세화고", "반포고", "서문여고", "상문고", "숙명여고"]
# 학년을 섞는 이유: 학년은 원번에서 빠졌지만(2026-07-29 재개정) 명단·필터에
# 그대로 노출되는 학생 정보다. 승급 커맨드 시연도 고3(다음이 N수)과 나머지가
# 섞여 있어야 성립한다.
_GRADES = ["고1", "고2", "고3"]
_UNITS = [
    ("역학", "등가속도 운동", "등가속도"),
    ("역학", "운동량과 충격량", "운동량 보존"),
    ("열역학", "기체 법칙", "기체 법칙"),
    ("파동", "굴절과 간섭", "파동의 굴절"),
    ("전자기", "직류 회로", "회로 해석"),
]
# 1×1 PNG(데모 워크북 사진) — 실파일이 있어야 이미지 URL 이 깨지지 않는다.
_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJ"
    "AAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class Command(BaseCommand):
    help = "데모 전용 시드 데이터 생성(멱등 — 도메인 테이블 초기화 후 재생성)"

    def handle(self, *args, **options):
        rng = random.Random(20260722)
        now = timezone.now()
        today = timezone.localdate(now)
        with transaction.atomic():
            self._wipe()
            staff = self._create_staff()
            students, parents = self._create_students_and_parents(now)
            course, weeks = self._create_course(students, today)
            sessions = self._create_sessions(course, weeks)
            exams = self._create_exams(sessions, weeks)
            videos = self._create_videos(weeks, today)
            self._attach_guide_videos(exams, videos)
            triggers = self._enter_attendance(sessions, students, exams, staff, today, rng)
            self._create_scores(exams, sessions, students, rng)
            self._create_makeup_and_counseling(staff, students, now)
            eligible = self._create_clinic(exams[-1], students, staff, now, today)
            self._create_boards(staff, students, weeks, now)
            self._create_payments(students, parents, staff, course, now)
            self._create_workbook(sessions, students, staff, today)
            self._create_notifications(students, parents, staff, exams, now)
        self._print_summary(triggers, eligible)

    # --- 초기화 -----------------------------------------------------------

    def _wipe(self):
        """도메인 테이블 전체 초기화 — PROTECT FK 역순(자식 먼저)."""
        self._wipe_demo_files()
        ordered = [
            Notification,
            ClinicEvaluationItem, ClinicEvaluation, ClinicRequest,
            ClinicEligibility, ClinicEvalCriteria, ClinicSlot,
            Payment, Order, Product,
            WatermarkTamper, VideoGrant, MakeupGrant, Video,
            AbsenceCounseling, ParentCounselRequest, PostComment, Post,
            WorkbookSubmission, WeaknessCheckPdf, QuestionSimilarMap, QuestionBankItem,
            SheetAnswer, AnswerSheet, Score, Assignment, Attendance,
            Question, ClassSession, Exam,
            CourseEnrollment, Class, WeekDayPlan, CourseWeek, Course,
            StaffFeatureGrant, ParentStudent, Parent, Student, User,
        ]
        for model in ordered:
            model.objects.all().delete()

    @staticmethod
    def _wipe_demo_files():
        """시드가 만든 스토리지 파일을 **경로 기준**으로 지운다.

        DB 행(WorkbookSubmission.image_path)을 훑어 지우면 고아 파일이 남는다 —
        컨테이너 재생성·스키마 리셋처럼 DB만 비워지는 일이 있으면 파일은 호스트에
        그대로 남고, 그다음 시드가 같은 이름으로 저장할 때 Django 가 충돌을 피해
        랜덤 접미사를 붙이므로(`26-26006_qnmd7XT.png`) 재실행마다 누적된다.
        (2026-07-28 실측: 6회 실행 → 파일 58개.)

        디렉터리째 비우면 DB 상태와 무관하게 항상 같은 결과가 된다.
        `demo/` 하나만 지운다. 시드가 최상위 `demo/` 아래에만 쓰므로 실제
        업로드본과 절대 안 겹친다(apps/grades/media.py).
        """
        for prefix in (grades_media.DEMO,):
            try:
                _dirs, files = default_storage.listdir(prefix)
            except (FileNotFoundError, NotImplementedError, OSError):
                continue  # 아직 없거나 listdir 미지원 백엔드(S3 등)면 건너뛴다
            for name in files:
                try:
                    default_storage.delete(f"{prefix}/{name}")
                except OSError:
                    pass

    # --- 계정 -------------------------------------------------------------

    @staticmethod
    def _make_user(login_id, role, name, phone):
        """아이디는 호출자가 login_id 모듈로 만들어 넘긴다 — 규칙 우회 금지."""
        user = User.objects.create_user(
            login_id=login_id,
            password=PASSWORD,
            role=role,
            name=name,
            phone=phone,
            must_change_password=False,  # 데모 전용(모듈 docstring)
        )
        return user

    def _create_person(self, role, name, phone):
        """이름+휴대폰 → 8-4 규칙 아이디로 계정 생성(학생·직원 공통 축)."""
        return self._make_user(issue_staff_login_id(name, phone), role, name, phone)

    def _create_staff(self):
        owner = self._create_person(User.Role.OWNER, "한종철", "01000000001")
        admin = self._create_person(User.Role.ADMIN, "김관리", "01000000002")
        assistant = self._create_person(User.Role.ASSISTANT, "박조교", "01000000003")
        return {"owner": owner, "admin": admin, "assistant": assistant}

    def _create_students_and_parents(self, now):
        """학생 30(등록 1~26 · 퇴원 27/28 · 예비등록 29/30) + 학부모 10(자녀 1~2명).

        퇴원생 2명은 2026-07-29 추가 — 출결 명단이 퇴원생을 **빼지 않고 표시
        전용 행으로 남기는** 동작(attendance_admin)을 화면에서 확인하려면
        시드에 퇴원생이 있어야 한다.

        아이디는 login_id 모듈 산출값 그대로 — 학생 `{이름}{뒷4자리}`,
        학부모 `{최초 연결 자녀 아이디}p`(8-4 개정). 원번도 손으로 만들지 않고
        matching_key 모듈 산출값 그대로다 — `{이름}{뒷4자리}`(2026-07-29 재개정).
        시드는 이름·번호가 전부 달라 아이디 충돌이 없으므로 원번 == 아이디다.
        """
        students = []
        for i in range(1, 31):
            name = _SURNAMES[(i - 1) % 10] + _GIVEN[i - 1]
            phone = f"010{10000000 + i:08d}"  # 01010000001 ~ 01010000030
            grade = _GRADES[(i - 1) % 3]
            user = self._make_user(
                issue_student_login_id(name, phone), User.Role.STUDENT, name, phone
            )
            if i >= 29:
                enrollment = Student.EnrollmentStatus.PRE_REGISTERED
            elif i >= 27:
                enrollment = Student.EnrollmentStatus.WITHDRAWN
            else:
                enrollment = Student.EnrollmentStatus.REGISTERED
            withdrawn = enrollment == Student.EnrollmentStatus.WITHDRAWN
            students.append(
                Student.objects.create(
                    user=user,
                    matching_key=build_matching_key(name, phone),
                    grade=grade,
                    school=_SCHOOLS[(i - 1) % 5],
                    enrollment_status=enrollment,
                    registered_at=(
                        None
                        if enrollment == Student.EnrollmentStatus.PRE_REGISTERED
                        else now
                    ),
                    withdrawn_at=now if withdrawn else None,
                    withdrawn_reason="타 학원 이동" if withdrawn else None,
                )
            )
        parents = []
        for i in range(1, 11):
            phone = f"010{20000000 + i:08d}"  # 01020000001 ~ 01020000010
            child = students[i - 1]  # 최초 연결 자녀 — 학부모 아이디의 기준
            user = self._make_user(
                issue_parent_login_id(child.user.login_id),
                User.Role.PARENT,
                f"{child.user.name} 학부모",
                phone,
            )
            parent = Parent.objects.create(user=user, phone=phone)
            ParentStudent.objects.create(
                parent=parent, student=child, relation="모", is_primary_contact=True
            )
            if i <= 4:  # 학부모 1~4번은 자녀 2명(다자녀 드롭다운 시연)
                ParentStudent.objects.create(
                    parent=parent, student=students[9 + i], relation="모"
                )
            parents.append(parent)
        return students, parents

    # --- 커리큘럼 ----------------------------------------------------------

    def _create_course(self, students, today):
        """강좌 1 + 주차 10 + Day 계획. 이번 주 = 4주차(5주차부터 미공개)."""
        # 과목은 마이그레이션이 넣는 기준값이라 _wipe 대상이 아니다(FLOW 1-2).
        subject, _ = Subject.objects.get_or_create(
            track=Subject.Track.SUNEUNG, name="통합과학"
        )
        course = Course.objects.create(
            name="로직엔제", total_weeks=10, target_grade=2, subject=subject
        )
        week1_monday = today - datetime.timedelta(days=today.weekday(), weeks=3)
        weeks = []
        for no in range(1, 11):
            start = week1_monday + datetime.timedelta(weeks=no - 1)
            week = CourseWeek.objects.create(
                course=course,
                week_no=no,
                title=f"{no}주차 — {_UNITS[(no - 1) % 5][0]} 심화",
                offline_notice=(
                    "오메가블랙 1회 응시(지필)" if no in (2, 4) else None
                ),
                start_date=start,
                end_date=start + datetime.timedelta(days=6),
                release_at=None,  # 시작일 자정 공개 — 5주차부터 자연 미공개
            )
            for day_no in (1, 2):
                WeekDayPlan.objects.create(
                    week=week,
                    day_no=day_no,
                    title=f"Day{day_no} {_UNITS[(no - 1) % 5][1]}",
                    content=(
                        f"{no}주차 Day{day_no}: 교재 {no * 10 + day_no * 4}p "
                        "문항 풀이 후 오답 정리"
                    ),
                    display_order=day_no,
                )
            weeks.append(week)
        # 결제선생을 쓰는 반과 안 쓰는 반을 하나씩 둔다(FLOW 2-7 — 러셀은
        # 교재값을 학원이 따로 받는다). 토요반에서는 청구가 막힌다.
        classes = {
            name: Class.objects.create(
                course=course, name=name, start_date=week1_monday,
                uses_payssam=(name == "수요반"),
            )
            for name in ("수요반", "토요반")
        }
        for idx, student in enumerate(students):
            wednesday = idx % 2 == 0
            CourseEnrollment.objects.create(
                student=student,
                course=course,
                klass=classes["수요반" if wednesday else "토요반"],
                primary_weekday=3 if wednesday else 6,  # 0=일…6=토(수/토)
            )
        return course, weeks

    @staticmethod
    def _create_sessions(course, weeks):
        """매주 수·토 회차(주차당 2회, 총 20회)."""
        sessions = []
        session_no = 0
        for week in weeks:
            for offset in (2, 5):  # 월요일 시작 기준 수(+2)·토(+5)
                session_no += 1
                sessions.append(
                    ClassSession.objects.create(
                        session_date=week.start_date + datetime.timedelta(days=offset),
                        session_no=session_no,
                        target_grade=2,
                        course_week=week,
                    )
                )
        return sessions

    # --- 시험 -------------------------------------------------------------

    @staticmethod
    def _create_exams(sessions, weeks):
        """시험 3회 — 1~3주차 토요일 회차에 연결, 문항 20개(테마·가이드 포함)."""
        exams = []
        for round_no in (1, 2, 3):
            session = sessions[round_no * 2 - 1]  # 각 주차 토요일 회차
            exam = Exam.objects.create(
                name=f"로직엔제 주간모의고사 {round_no}회",
                exam_date=session.session_date,
                round_no=round_no,
                target_grade=2,
                notice=f"{round_no}회차 성적표입니다. 오답 문항은 학습가이드를 따라 복습하세요.",
            )
            session.exam = exam
            session.save(update_fields=["exam"])
            for q_no in range(1, 21):
                unit_major, unit_minor, theme = _UNITS[(q_no - 1) % 5]
                Question.objects.create(
                    exam=exam,
                    q_number=q_no,
                    answer=str((q_no * 7 + round_no) % 5 + 1),
                    points="5.0",
                    unit_major=unit_major,
                    unit_minor=unit_minor,
                    theme_tag=theme,
                    study_guide=(
                        f"{unit_major}·{unit_minor} 개념 복습 후 교재 "
                        f"{q_no * 3 + 40}p 유형 문제를 다시 풀어보세요."
                    ),
                    question_format=(
                        Question.Format.SCHOOL if q_no % 2 else Question.Format.CSAT
                    ),
                )
            exams.append(exam)
        return exams

    # --- 영상 -------------------------------------------------------------

    @staticmethod
    def _create_videos(weeks, today):
        """주차별 복습영상 2~3개 — 공개된 주차는 `공개`, 미래 주차는 `준비중`."""
        videos = []
        for week in weeks:
            # 주차당 1편이면 충분하다. 재생·권한·만료는 영상 한 편으로 다
            # 검증되고, 여러 편은 목록을 길게 만들 뿐이다 — 게다가 시드 영상은
            # 전부 같은 자산으로 대체돼 재생되므로(resolve_ref) 늘려도 보이는
            # 것이 달라지지 않는다. 2주차만 2편으로 둔다: "한 주차에 여러 편"
            # 이라는 축(차시 정렬·다음 차시 계산)을 잃지 않기 위해서다.
            count = 2 if week.week_no == 2 else 1
            released = week.start_date <= today
            for seq in range(1, count + 1):
                # `seed-` 접두는 실제 Mux 참조가 아니라는 표시다. 서버가 이 접두를
                # 보고 `MUX_DEMO_PLAYBACK_ID` 자산으로 바꿔 재생한다
                # (videos.playback.resolve_ref — 대체와 서명이 같은 자리여야 한다).
                # 공개 영상에 참조를 채우는 이유: 비워 두면 "공개인데 볼 수 없는"
                # 상태가 되어 시드 직후 화면이 통째로 죽는다.
                videos.append(
                    Video.objects.create(
                        course_week=week,
                        title=f"로직엔제 {week.week_no}주차 복습영상 {seq}강",
                        sequence_no=seq,
                        duration_seconds=1500 + seq * 300,
                        status=Video.Status.PUBLISHED if released else Video.Status.PREPARING,
                        provider=Video.Provider.MUX if released else None,
                        external_ref=(
                            f"seed-{week.week_no}-{seq}" if released else None
                        ),
                    )
                )
        return videos

    @staticmethod
    def _attach_guide_videos(exams, videos):
        """오답 학습가이드 영상 연결 — 각 시험 앞 5문항에 해당 주차 영상."""
        by_week_no = {}
        for video in videos:
            by_week_no.setdefault(video.course_week.week_no, []).append(video)
        for exam in exams:
            week_videos = by_week_no.get(exam.round_no, [])
            if not week_videos:
                continue
            for question in exam.questions.filter(q_number__lte=5):
                question.guide_video = week_videos[(question.q_number - 1) % len(week_videos)]
                question.save(update_fields=["guide_video"])

    # --- 출결(실서비스 경유 — 트리거 실작동) --------------------------------

    def _enter_attendance(self, sessions, students, exams, staff, today, rng):
        """지난 회차 출결 upsert — attendance_admin.apply_entries 경유.

        값 **4종을 모두 섞는다**(2026-07-29 개편) — 화면에서 넷이 구분되는지
        눈으로 봐야 하기 때문이다. 각 값이 서로 다른 트리거를 태우므로 파생
        데이터도 넷 다 생긴다(직접 INSERT 금지 — 모듈 docstring):
          출석/결석(현보) → VideoGrant(출석자동) · 결석 → 상담 대기열
          결석(동보) → MakeupGrant(지급완료) + VideoGrant(동보)

        퇴원생은 entries 에서 뺀다 — 명단에는 남지만 출결 레코드를 만들지
        않는 것이 계약이다(attendance_admin.is_entry_target).

        `exam_taken` 은 **출석생만** True 후보다. 결석 계열은 그 회차 교실에
        없었으므로 현장 시험을 볼 수 없다. 출석인데 False 인 학생(skip_exam)이
        곧 사용자가 말한 "지각해서 OMR 카드가 안 들어온" 경우이며, 리포트에는
        `시험 미제출`로 나간다 — 지각을 출결 값에서 없앤 자리가 여기다.
        """
        exam_session_ids = {e.class_sessions.first().session_id for e in exams}
        totals = {}
        target_ids = [
            s.student_id
            for s in students
            if s.enrollment_status != Student.EnrollmentStatus.WITHDRAWN
        ]
        registered_ids = [
            s.student_id
            for s in students
            if s.enrollment_status == Student.EnrollmentStatus.REGISTERED
        ]
        for session in sessions:
            if session.session_date > today:
                continue
            drawn = rng.sample(registered_ids, 5)
            absent = set(drawn[:2])  # 보강 미정
            absent_makeup = set(drawn[2:4])  # 동영상 보강
            absent_onsite = {drawn[4]}  # 현장 보강(다른 회차에서 수강)
            present_ids = [sid for sid in registered_ids if sid not in drawn]
            skip_exam = set(rng.sample(present_ids, 2))
            entries = []
            for sid in target_ids:
                if sid in absent:
                    status = Attendance.Status.ABSENT
                elif sid in absent_makeup:
                    status = Attendance.Status.ABSENT_MAKEUP
                elif sid in absent_onsite:
                    status = Attendance.Status.ABSENT_ONSITE
                else:
                    status = Attendance.Status.PRESENT
                entry = {"student_id": sid, "status": status}
                if session.session_id in exam_session_ids:
                    entry["exam_taken"] = (
                        status == Attendance.Status.PRESENT and sid not in skip_exam
                    )
                entries.append(entry)
            _, triggers = attendance_admin.apply_entries(
                session, entries, staff["admin"], target_ids
            )
            for key, value in triggers.items():
                totals[key] = totals.get(key, 0) + value
        return totals

    # --- 성적 -------------------------------------------------------------

    @staticmethod
    def _create_scores(exams, sessions, students, rng):
        """답안지·문항 채점·성적 — 출결과 정합(결석·시험 미제출은 성적표 없음)."""
        registered = [
            s for s in students
            if s.enrollment_status == Student.EnrollmentStatus.REGISTERED
        ]
        for exam in exams:
            session = exam.class_sessions.first()
            att_map = {
                a.student_id: a
                for a in Attendance.objects.filter(session=session)
            }
            questions = list(exam.questions.order_by("q_number"))
            for idx, student in enumerate(registered):
                att = att_map.get(student.student_id)
                # 결석 계열은 그 교실에 없었으므로 현장 시험을 볼 수 없다.
                # 출석인데 exam_taken=False 인 학생 = OMR 미제출(리포트 '시험 미제출').
                taken = (
                    att is not None
                    and att.status == Attendance.Status.PRESENT
                    and bool(att.exam_taken)
                )
                if not taken:
                    Score.objects.create(exam=exam, student=student, is_taken=False)
                    continue
                sheet = AnswerSheet.objects.create(
                    exam=exam,
                    student=student,
                    scan_image_path=grades_media.demo(
                        "omr", exam.round_no, f"{student.matching_key}.png"
                    ),
                    recognized_matching_key=student.matching_key,
                    recognized_name=student.user.name,
                    match_status=AnswerSheet.MatchStatus.MATCHED,
                )
                ability = 0.45 + (idx % 12) * 0.04
                total = 0
                for question in questions:
                    roll = rng.random()
                    if roll < ability:
                        marked, result = question.answer, SheetAnswer.Result.CORRECT
                        total += 5
                    elif roll < ability + 0.05:
                        marked, result = None, None
                    else:
                        wrong = str(int(question.answer) % 5 + 1)
                        marked, result = wrong, SheetAnswer.Result.WRONG
                    SheetAnswer.objects.create(
                        sheet=sheet,
                        question=question,
                        marked=marked,
                        result=result,
                        extra_practice_marked=(
                            result != SheetAnswer.Result.CORRECT and rng.random() < 0.3
                        ),
                    )
                Score.objects.create(
                    exam=exam,
                    student=student,
                    total_score=total,
                    max_score=100,
                    is_taken=True,
                )

    # --- 동보·상담 ---------------------------------------------------------

    @staticmethod
    def _create_makeup_and_counseling(staff, students, now):
        """동보(관리자체크 지급 1건 + 학생신청 대기 1건) + 상담 기록 1건.

        대상은 **보강 미정 결석**(`결석`)뿐이다 — `결석(동보)` 는 담임의 출결
        입력만으로 이미 지급 체인이 완료됐고(트리거 ③), 관리자 체크는 그 결석의
        출결 값을 `결석(동보)` 로 올리며 같은 결과에 도달한다. 즉 이 함수는
        "출결 화면 밖에서 들어오는 두 입구"를 시연한다.
        """
        absences = list(
            Attendance.objects.filter(status=Attendance.Status.ABSENT)
            .select_related("session__course_week")
            .order_by("id")
        )
        granted = absences[0]
        attendance_admin.grant_makeup(granted, staff["admin"])
        pending = next(a for a in absences[1:] if a.student_id != granted.student_id)
        MakeupGrant.objects.create(
            student_id=pending.student_id,
            attendance=pending,
            source=MakeupGrant.Source.STUDENT_REQUEST,
            requested_by=next(
                s.user for s in students if s.student_id == pending.student_id
            ),
        )
        # 상담 대기열 중 1건은 통화 완료 처리(감사 이력 시연)
        card = (
            AbsenceCounseling.objects.filter(status=AbsenceCounseling.Status.PENDING)
            .order_by("counsel_id")
            .first()
        )
        # 대기열은 출결 트리거가 만든다 — 비어 있다면 그 트리거가 안 돈 것이고,
        # 여기서 AttributeError 로 죽으면 원인이 안 보인다.
        if card is None:
            raise RuntimeError(
                "결석 상담 대기열이 비어 있다 — 출결 트리거가 돌지 않았다."
            )
        card.called_at = now
        card.status = AbsenceCounseling.Status.COMPLETED
        card.absence_reason = "감기몸살"
        card.call_memo = "학부모 통화 완료 — 다음 회차 정상 출석 예정, 동보 희망"
        card.makeup_requested = True
        card.counselor = staff["admin"]
        card.save()

    # --- 클리닉 ------------------------------------------------------------

    @staticmethod
    def _create_clinic(exam, students, staff, now, today):
        """슬롯 20(월~금 × 4교시) + 최근 시험 자격 판정 + 신청 혼합(대기·승인배정 등).

        시간대를 요일당 하나가 아니라 넷으로 두는 이유: 정원이 1 고정이라
        (2026-07-21 회의 "시간별로 학생 한 명씩") 한 요일에 시간이 하나뿐이면
        전교생이 하루 한 자리를 두고 다투는 셈이라 운영이 성립하지 않는다.
        회의 문구 자체가 "**시간별로** 한 명"이므로 시간대가 여럿인 것이 전제다.
        """
        slots = [
            ClinicSlot.objects.create(
                weekday=weekday,
                start_time=datetime.time(hour, 0),
                end_time=datetime.time(hour + 1, 0),
            )
            for weekday in (1, 2, 3, 4, 5)  # 0=일…6=토 → 월~금
            for hour in (17, 18, 19, 20)
        ]
        for order, item in enumerate(
            ["개념 이해도 점검", "오답 원인 설명", "유사문항 풀이 지도", "학습 태도 피드백"],
            start=1,
        ):
            ClinicEvalCriteria.objects.create(
                item=item, description=f"{item} 여부를 확인한다.", display_order=order
            )
        # 자격 판정 — 최근 시험(3회) 평균 미달자(원천은 scores·attendances)
        session = exam.class_sessions.first()
        att_map = {
            a.student_id: a for a in Attendance.objects.filter(session=session)
        }
        scores = {s.student_id: s for s in Score.objects.filter(exam=exam)}
        taken_totals = [
            float(s.total_score) for s in scores.values()
            if s.is_taken and s.total_score is not None
        ]
        average = sum(taken_totals) / len(taken_totals)
        eligible = []
        registered = [
            s for s in students
            if s.enrollment_status == Student.EnrollmentStatus.REGISTERED
        ]
        for student in registered:
            att = att_map.get(student.student_id)
            score = scores.get(student.student_id)
            # 결석 계열은 전부 미대상(사유 `결석`) — 클리닉 전제가 '출석 + 응시'다
            if att is None or att.status in Attendance.ABSENT_STATUSES:
                is_target, reason = False, ClinicEligibility.Reason.ABSENT
            elif score is None or not score.is_taken:
                is_target, reason = False, ClinicEligibility.Reason.NOT_TAKEN
            elif float(score.total_score) >= average:
                is_target, reason = False, ClinicEligibility.Reason.ABOVE_AVG
            else:
                is_target, reason = True, None
            ClinicEligibility.objects.create(
                exam=exam,
                student=student,
                is_target=is_target,
                reason=reason,
                determined_by=staff["admin"],
                determined_at=now,
            )
            if is_target:
                eligible.append(student)

        def next_date(slot):
            py_target = slot.weekday - 1  # 모델 0=일…6=토 → 파이썬 월=0
            delta = (py_target - today.weekday()) % 7 or 7
            return today + datetime.timedelta(days=delta)

        def request(student, slot, date, **extra):
            return ClinicRequest.objects.create(
                student=student, exam=exam, slot=slot,
                requested_date=date, requested_time=slot.start_time, **extra,
            )

        def at(weekday, hour):
            """(요일, 시) 로 슬롯을 집는다 — 인덱스 산수로 고르면 시간대를
            늘릴 때마다 조용히 다른 칸을 가리킨다."""
            return next(
                s for s in slots if s.weekday == weekday and s.start_time.hour == hour
            )

        assistant = staff["assistant"]
        # 마감 칸이 요일·시간에 흩어져야 달력에서 "찬 자리/빈 자리"가 눈에 들어온다.
        request(eligible[0], at(1, 18), next_date(at(1, 18)))  # 대기
        request(eligible[1], at(2, 20), next_date(at(2, 20)))  # 대기
        request(  # 승인배정(예정) — 미트 링크 포함
            eligible[2], at(4, 17), next_date(at(4, 17)),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            conference_url="https://meet.google.com/demo-loz-ic01",
        )
        done = request(  # 지난 클리닉 — 출석 처리 + 평가 기록
            eligible[3], at(3, 19), next_date(at(3, 19)) - datetime.timedelta(days=7),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            conference_url="https://meet.google.com/demo-loz-ic02",
            attendance_status=ClinicRequest.AttendanceStatus.PRESENT,
            attendance_marked_at=now, attendance_marked_by=staff["admin"],
        )
        evaluation = ClinicEvaluation.objects.create(
            clinic=done,
            overall_result=ClinicEvaluation.OverallResult.QUALIFIED,
            ai_summary="오답 원인 설명·유사문항 지도 충실. 개념 점검 일부 미흡.",
            evaluated_at=now,
        )
        for idx, criteria in enumerate(ClinicEvalCriteria.objects.order_by("display_order")):
            ClinicEvaluationItem.objects.create(
                evaluation=evaluation,
                criteria=criteria,
                result=(
                    ClinicEvaluationItem.Result.UNMET
                    if idx == 0
                    else ClinicEvaluationItem.Result.MET
                ),
                ai_reason=f"{criteria.item} 판단(데모)",
            )
        noshow = request(  # 지난 클리닉 — 노쇼(결석 처리, unban 시연용)
            eligible[4], at(5, 18), next_date(at(5, 18)) - datetime.timedelta(days=7),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            conference_url="https://meet.google.com/demo-loz-ic03",
            attendance_status=ClinicRequest.AttendanceStatus.ABSENT,
            attendance_marked_at=now, attendance_marked_by=staff["admin"],
        )
        noshow.student.noshow_count = 1
        noshow.student.save(update_fields=["noshow_count"])
        request(  # 취소 이력
            eligible[5], at(1, 17), next_date(at(1, 17)),
            status=ClinicRequest.Status.CANCELLED, cancelled_at=now,
        )
        return eligible

    # --- 게시판 ------------------------------------------------------------

    @staticmethod
    def _create_boards(staff, students, weeks, now):
        owner, admin = staff["owner"], staff["admin"]
        s1, s2, s3 = students[0].user, students[1].user, students[2].user
        notice_week = Post.objects.create(
            category=Post.Category.NOTICE, author=admin, course_week=weeks[3],
            title="4주차 주차공지 — 오메가블랙 1회 응시",
            body="이번 주 토요일 수업 전 오메가블랙 지필 평가를 진행합니다. 준비물: OMR 펜.",
        )
        Post.objects.create(
            category=Post.Category.NOTICE, author=admin,
            title="7월 정규 수업 안내",
            body="7월 수업은 매주 수·토 진행됩니다. 결석 시 상담 전화가 발신됩니다.",
        )
        Post.objects.create(
            category=Post.Category.ERRATA, author=admin,
            title="교재 63p 정답 정정",
            body="63p 7번 정답이 ③이 아니라 ④입니다.",
        )
        Post.objects.create(
            category=Post.Category.ERRATA, author=admin,
            title="주간모의고사 2회 12번 배점 정정",
            body="12번 배점은 4점이 아니라 5점입니다. 성적에 반영 완료.",
        )
        qna = Post.objects.create(
            category=Post.Category.QNA, author=s1,
            title="등가속도 문제 질문 있습니다",
            body="교재 45p 3번에서 가속도 방향을 어떻게 잡아야 하나요?",
        )
        PostComment.objects.create(
            post=qna, author=admin, body="속도 변화 방향 기준으로 잡으면 됩니다. 클리닉에서 다뤄요."
        )
        secret = Post.objects.create(
            category=Post.Category.QNA, author=s2, is_secret=True,
            title="결제 관련 개인 문의",
            body="교재비 결제가 이중으로 청구된 것 같습니다. 확인 부탁드립니다.",
        )
        PostComment.objects.create(
            post=secret, author=admin, body="확인 후 취소 처리했습니다. 영업일 3일 내 환불됩니다."
        )
        Post.objects.create(
            category=Post.Category.QNA, author=s3,
            title="복습영상 시청 기간 연장 가능한가요?",
            body="이번 주 영상 만료가 얼마 안 남았는데 연장 가능할까요?",
        )
        Post.objects.create(
            category=Post.Category.FREE, author=owner,
            title="이번 주 수업 후기",
            body="다들 파동 단원 집중력이 좋았습니다. 이번 주말 모의고사 기대하겠습니다.",
        )
        Post.objects.create(
            category=Post.Category.FREE, author=owner,
            title="여름 특강 준비 중",
            body="8월 특강 커리큘럼을 준비하고 있습니다. 기대해 주세요.",
        )
        goods = Post.objects.create(
            category=Post.Category.EVENT_GOODS, author=admin,
            title="7월 출석왕 이벤트",
            body="7월 전 회차 출석 학생에게 굿즈를 드립니다.",
        )
        PostComment.objects.create(post=goods, author=s1, body="텀블러 옵션도 있나요?")
        Post.objects.create(
            category=Post.Category.EVENT_GOODS, author=admin,
            title="굿즈 수요조사",
            body="원하는 굿즈를 댓글로 남겨주세요.",
        )
        return notice_week

    # --- 결제 -------------------------------------------------------------

    @staticmethod
    def _create_payments(students, parents, staff, course, now):
        """교재 1 + 주문 혼합(미결제·결제완료·배부완료) + 결제 트랜잭션."""
        product = Product.objects.create(
            course=course, name="로직엔제 교재 Vol.1", price=45000
        )
        parent_by_student = {
            link.student_id: link.parent
            for link in ParentStudent.objects.select_related("parent").all()
        }

        def order(student, status, billed, **extra):
            parent = parent_by_student.get(student.student_id)
            return Order.objects.create(
                student=student, product=product, amount=product.price, status=status,
                is_billed=billed, billed_at=now if billed else None,
                billed_to_parent=parent,
                billed_to_phone=parent.phone if parent else None,
                initiated_by_user=student.user,
                charge_trigger=Order.ChargeTrigger.FIRST_SESSION,
                **extra,
            )

        for student in students[:2]:
            paid = order(student, Order.Status.PAID, True, paid_at=now)
            Payment.objects.create(
                order=paid, provider=Payment.Provider.PAYSSAM,
                external_ref=f"payssam-demo-{paid.order_id}",
                status=Payment.Status.COMPLETED, amount=paid.amount,
                paid_at=now, synced_at=now,
            )
        delivered = order(
            students[2], Order.Status.DELIVERED, True, paid_at=now, delivered_at=now
        )
        Payment.objects.create(
            order=delivered, provider=Payment.Provider.PAYSSAM,
            external_ref=f"payssam-demo-{delivered.order_id}",
            status=Payment.Status.COMPLETED, amount=delivered.amount,
            paid_at=now, synced_at=now,
        )
        order(students[3], Order.Status.UNPAID, True)   # 청구 발송·미결제
        order(students[4], Order.Status.UNPAID, False)  # 미청구·미결제
        order(students[28], Order.Status.UNPAID, True)  # 예비등록생(bare 홈 시연)

    # --- 워크북 ------------------------------------------------------------

    @staticmethod
    def _create_workbook(sessions, students, staff, today):
        """워크북 사진 — 확정(자동/수동)·대기·불일치 혼합 + 과제 수행 기록."""
        past = [s for s in sessions if s.session_date <= today]
        target_session = past[-2] if len(past) >= 2 else past[-1]
        assistant = staff["assistant"]
        specs = [
            (0, WorkbookSubmission.MatchStatus.AUTO_MATCHED, "A"),
            (1, WorkbookSubmission.MatchStatus.AUTO_MATCHED, "B"),
            (2, WorkbookSubmission.MatchStatus.AUTO_MATCHED, "C"),
            (3, WorkbookSubmission.MatchStatus.MANUAL_CONFIRMED, "B"),
            (4, WorkbookSubmission.MatchStatus.MANUAL_CONFIRMED, "A"),
            (5, None, None),  # 대기(매핑 전)
            (6, WorkbookSubmission.MatchStatus.MISMATCH, None),  # 보정 대상
        ]
        for idx, match_status, grade in specs:
            student = students[idx]
            path = default_storage.save(
                grades_media.demo(
                    "workbook", f"{target_session.session_id}-{student.matching_key}.png"
                ),
                ContentFile(_PNG_BYTES),
            )
            WorkbookSubmission.objects.create(
                student=student,
                session=target_session,
                image_path=path,
                performance_grade=grade,
                recognized_matching_key=(
                    student.matching_key if match_status is not None else None
                ),
                recognized_name=(
                    student.user.name
                    if match_status == WorkbookSubmission.MatchStatus.AUTO_MATCHED
                    else None
                ),
                match_status=match_status,
                uploaded_by=assistant,
            )
            if match_status in (
                WorkbookSubmission.MatchStatus.AUTO_MATCHED,
                WorkbookSubmission.MatchStatus.MANUAL_CONFIRMED,
            ):
                Assignment.objects.create(
                    session=target_session, student=student, done=idx % 3 != 2,
                    memo=None if idx % 3 != 2 else "분량 절반만 수행",
                )

    # --- 알림 -------------------------------------------------------------

    @staticmethod
    def _create_notifications(students, parents, staff, exams, now):
        """대상 3분기(학생/학부모/직원) 알림 행 — 성공·대기 혼합."""
        exam = exams[-1]
        rows = [
            dict(student=students[0], type=Notification.Type.GRADE,
                 title="주간모의고사 3회 성적표", body="성적표가 도착했습니다.",
                 ref_type="exam", ref_id=exam.exam_id,
                 status=Notification.Status.SUCCESS, sent_at=now),
            dict(student=students[0], type=Notification.Type.VIDEO_EXPIRY,
                 title="복습영상 만료 D-2", body="이번 주 복습영상이 곧 만료됩니다.",
                 status=Notification.Status.PENDING),
            dict(student=students[1], type=Notification.Type.CLINIC_TARGET,
                 title="클리닉 신청 안내", body="이번 시험 클리닉 대상입니다. 신청해 주세요.",
                 ref_type="exam", ref_id=exam.exam_id,
                 status=Notification.Status.SUCCESS, sent_at=now),
            dict(parent=parents[0], type=Notification.Type.REPORT,
                 title="수업 리포트", body="이번 수업 리포트가 도착했습니다.",
                 status=Notification.Status.SUCCESS, sent_at=now),
            dict(parent=parents[1], type=Notification.Type.ABSENCE_COUNSEL,
                 title="결석 안내", body="자녀가 결석하여 상담 전화를 드릴 예정입니다.",
                 status=Notification.Status.PENDING),
            dict(user=staff["admin"], type=Notification.Type.ACCOUNT_ISSUED,
                 title="계정 일괄 발급 완료", body="학생 30명 계정이 발급되었습니다.",
                 status=Notification.Status.SUCCESS, sent_at=now),
        ]
        for row in rows:
            Notification.objects.create(channel=Notification.Channel.KAKAO, **row)

    # --- 출력 -------------------------------------------------------------

    def _print_accounts(self):
        """실제 발급된 아이디를 그대로 나열한다(8-4 개정 후 범위 표기가 불가능).

        구 규칙에서는 `01010000001 ~ 01010000030` 같은 범위 한 줄로 충분했지만
        아이디가 이름 기반이 되어 연속 범위가 성립하지 않는다 — 시드로 만든
        계정으로 로그인하려면 전체 목록이 필요하다.
        """
        w = self.stdout.write
        w("로그인 계정 (비밀번호는 전부 test1234):")
        for user in User.objects.filter(role__in=_STAFF_ROLES).order_by("user_id"):
            w(f"  {_pad(user.role, 8)}{user.login_id}")
        registered, pre_registered = [], []
        for student in Student.objects.select_related("user").order_by("student_id"):
            bucket = (
                pre_registered
                if student.enrollment_status == Student.EnrollmentStatus.PRE_REGISTERED
                else registered
            )
            bucket.append(student.user.login_id)
        self._print_ids(f"학생 등록({len(registered)})", registered)
        self._print_ids(f"학생 예비등록({len(pre_registered)})", pre_registered)
        parents = [
            p.user.login_id
            for p in Parent.objects.select_related("user").order_by("parent_id")
        ]
        self._print_ids(f"학부모({len(parents)})", parents)

    def _print_ids(self, label, login_ids):
        self.stdout.write(f"  {label}")
        for line in textwrap.wrap(
            "  ".join(login_ids), width=92, initial_indent="    ", subsequent_indent="    "
        ):
            self.stdout.write(line)

    def _print_summary(self, triggers, eligible):
        w = self.stdout.write
        w(self.style.SUCCESS("seed_demo 완료 — 데모 데이터 생성됨(전체 초기화 후 재생성)"))
        w("")
        self._print_accounts()
        w("")
        w("생성 카운트:")
        counts = {
            "학생": Student.objects.count(),
            "학부모": Parent.objects.count(),
            "주차": CourseWeek.objects.count(),
            "공개 주차": CourseWeek.objects.released().count(),
            "수업 회차": ClassSession.objects.count(),
            "출결": Attendance.objects.count(),
            "영상 권한(트리거)": VideoGrant.objects.count(),
            "상담 대기열(트리거)": AbsenceCounseling.objects.count(),
            "시험": Exam.objects.count(),
            "성적": Score.objects.count(),
            "클리닉 대상자": len(eligible),
            "클리닉 신청": ClinicRequest.objects.count(),
            "게시글": Post.objects.count(),
            "주문": Order.objects.count(),
            "워크북": WorkbookSubmission.objects.count(),
            "알림": Notification.objects.count(),
        }
        for name, value in counts.items():
            w(f"  {name}: {value}")
        w(f"  출결 트리거 상세: {triggers}")
