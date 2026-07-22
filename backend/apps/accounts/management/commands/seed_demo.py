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

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

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
from apps.curriculum.models import Course, CourseEnrollment, CourseWeek, WeekDayPlan
from apps.grades import attendance_admin
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
from apps.videos.models import MakeupGrant, Video, VideoGrant

PASSWORD = "test1234"  # 데모 전용 공통 비밀번호(모듈 docstring)

_SURNAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임"]
_GIVEN = [
    "하늘", "서준", "지우", "민준", "서연", "도윤", "예린", "시우", "지안", "주원",
    "하린", "은우", "수아", "지호", "다은", "건우", "소율", "현우", "가은", "우진",
    "나윤", "선우", "채원", "정민", "유나", "태윤", "세아", "준서", "예준", "다인",
]
_SCHOOLS = ["세화고", "반포고", "서문여고", "상문고", "숙명여고"]
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
            self._create_payments(students, parents, staff, now)
            self._create_workbook(sessions, students, staff, today)
            self._create_notifications(students, parents, staff, exams, now)
        self._print_summary(triggers, eligible)

    # --- 초기화 -----------------------------------------------------------

    def _wipe(self):
        """도메인 테이블 전체 초기화 — PROTECT FK 역순(자식 먼저)."""
        for submission in WorkbookSubmission.objects.all():
            try:  # 스토리지 파일 잔재 정리(없어도 무시)
                default_storage.delete(submission.image_path)
            except OSError:
                pass
        ordered = [
            Notification,
            ClinicEvaluationItem, ClinicEvaluation, ClinicRequest,
            ClinicEligibility, ClinicEvalCriteria, ClinicSlot,
            Payment, Order, Product,
            VideoGrant, MakeupGrant, Video,
            AbsenceCounseling, ParentCounselRequest, PostComment, Post,
            WorkbookSubmission, WeaknessCheckPdf, QuestionSimilarMap, QuestionBankItem,
            SheetAnswer, AnswerSheet, Score, Assignment, Attendance,
            Question, ClassSession, Exam,
            CourseEnrollment, WeekDayPlan, CourseWeek, Course,
            StaffFeatureGrant, ParentStudent, Parent, Student, User,
        ]
        for model in ordered:
            model.objects.all().delete()

    # --- 계정 -------------------------------------------------------------

    @staticmethod
    def _make_user(login_id, role, name, phone=""):
        user = User.objects.create_user(
            login_id=login_id,
            password=PASSWORD,
            role=role,
            name=name,
            phone=phone or login_id,
            must_change_password=False,  # 데모 전용(모듈 docstring)
        )
        return user

    def _create_staff(self):
        owner = self._make_user("01000000001", User.Role.OWNER, "한종철")
        admin = self._make_user("01000000002", User.Role.ADMIN, "김관리")
        assistant = self._make_user("01000000003", User.Role.ASSISTANT, "박조교")
        return {"owner": owner, "admin": admin, "assistant": assistant}

    def _create_students_and_parents(self, now):
        """학생 30(등록 28·예비등록 29/30번) + 학부모 10(자녀 1~2명)."""
        students = []
        for i in range(1, 31):
            name = _SURNAMES[(i - 1) % 10] + _GIVEN[i - 1]
            login_id = f"010{10000000 + i:08d}"  # 01010000001 ~ 01010000030
            user = self._make_user(login_id, User.Role.STUDENT, name)
            pre_registered = i >= 29
            students.append(
                Student.objects.create(
                    user=user,
                    unique_id=f"26{i:03d}",
                    grade="고2",
                    school=_SCHOOLS[(i - 1) % 5],
                    current_class="수요반" if i % 2 else "토요반",
                    enrollment_status=(
                        Student.EnrollmentStatus.PRE_REGISTERED
                        if pre_registered
                        else Student.EnrollmentStatus.REGISTERED
                    ),
                    registered_at=None if pre_registered else now,
                )
            )
        parents = []
        for i in range(1, 11):
            login_id = f"010{20000000 + i:08d}"  # 01020000001 ~ 01020000010
            child = students[i - 1]
            user = self._make_user(
                login_id, User.Role.PARENT, f"{child.user.name} 학부모"
            )
            parent = Parent.objects.create(user=user, phone=login_id)
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
        course = Course.objects.create(name="로직엔제", target_grade=2)
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
        for idx, student in enumerate(students):
            CourseEnrollment.objects.create(
                student=student,
                course=course,
                class_name=student.current_class,
                primary_weekday=3 if idx % 2 == 0 else 6,  # 0=일…6=토(수/토)
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
            count = 3 if week.week_no <= 2 else 2
            released = week.start_date <= today
            for seq in range(1, count + 1):
                videos.append(
                    Video.objects.create(
                        course_week=week,
                        title=f"로직엔제 {week.week_no}주차 복습영상 {seq}강",
                        sequence_no=seq,
                        duration_seconds=1500 + seq * 300,
                        status=Video.Status.PUBLISHED if released else Video.Status.PREPARING,
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

        출석 확정 → VideoGrant(출석자동), 결석 확정 → 상담 대기열이 실제
        트리거로 생성된다(직접 INSERT 금지 — 모듈 docstring).
        """
        exam_session_ids = {e.class_sessions.first().session_id for e in exams}
        totals = {}
        roster_ids = [s.student_id for s in students]
        for session in sessions:
            if session.session_date > today:
                continue
            absent = set(rng.sample(roster_ids[:28], 3))
            late = set(rng.sample([sid for sid in roster_ids[:28] if sid not in absent], 2))
            skip_exam = set(rng.sample(
                [sid for sid in roster_ids[:28] if sid not in absent], 2
            ))
            entries = []
            for sid in roster_ids:
                if sid in absent:
                    status = Attendance.Status.ABSENT
                elif sid in late:
                    status = Attendance.Status.LATE
                else:
                    status = Attendance.Status.PRESENT
                entry = {"student_id": sid, "status": status}
                if session.session_id in exam_session_ids:
                    entry["exam_taken"] = (
                        status != Attendance.Status.ABSENT and sid not in skip_exam
                    )
                entries.append(entry)
            _, triggers = attendance_admin.apply_entries(
                session, entries, staff["admin"], roster_ids
            )
            for key, value in triggers.items():
                totals[key] = totals.get(key, 0) + value
        return totals

    # --- 성적 -------------------------------------------------------------

    @staticmethod
    def _create_scores(exams, sessions, students, rng):
        """답안지·문항 채점·성적 — 출결과 정합(결석/미응시는 성적표 없음)."""
        registered = students[:28]
        for exam in exams:
            session = exam.class_sessions.first()
            att_map = {
                a.student_id: a
                for a in Attendance.objects.filter(session=session)
            }
            questions = list(exam.questions.order_by("q_number"))
            for idx, student in enumerate(registered):
                att = att_map.get(student.student_id)
                taken = (
                    att is not None
                    and att.status != Attendance.Status.ABSENT
                    and bool(att.exam_taken)
                )
                if not taken:
                    Score.objects.create(exam=exam, student=student, is_taken=False)
                    continue
                sheet = AnswerSheet.objects.create(
                    exam=exam,
                    student=student,
                    scan_image_path=f"omr/demo/{exam.round_no}/{student.unique_id}.png",
                    recognized_unique_id=student.unique_id,
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
                        marked, result = None, SheetAnswer.Result.BLANK
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
        """동보(관리자체크 지급 1건 + 학생신청 대기 1건) + 상담 기록 1건."""
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
        """슬롯 5(월~금) + 최근 시험 자격 판정 + 신청 혼합(대기·승인배정 등)."""
        slots = [
            ClinicSlot.objects.create(
                weekday=weekday, start_time=datetime.time(19, 0),
                end_time=datetime.time(20, 0), capacity=3,
            )
            for weekday in (1, 2, 3, 4, 5)  # 0=일…6=토 → 월~금
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
        for student in students[:28]:
            att = att_map.get(student.student_id)
            score = scores.get(student.student_id)
            if att is None or att.status == Attendance.Status.ABSENT:
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

        assistant = staff["assistant"]
        request(eligible[0], slots[0], next_date(slots[0]))  # 대기
        request(eligible[1], slots[1], next_date(slots[1]))  # 대기
        request(  # 승인배정(예정) — 미트 링크 포함
            eligible[2], slots[2], next_date(slots[2]),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            meet_url="https://meet.google.com/demo-loz-ic01",
        )
        done = request(  # 지난 클리닉 — 출석 처리 + 평가 기록
            eligible[3], slots[3], next_date(slots[3]) - datetime.timedelta(days=7),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            meet_url="https://meet.google.com/demo-loz-ic02",
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
            eligible[4], slots[4], next_date(slots[4]) - datetime.timedelta(days=7),
            status=ClinicRequest.Status.APPROVED, assigned_staff=assistant,
            meet_url="https://meet.google.com/demo-loz-ic03",
            attendance_status=ClinicRequest.AttendanceStatus.ABSENT,
            attendance_marked_at=now, attendance_marked_by=staff["admin"],
        )
        noshow.student.noshow_count = 1
        noshow.student.save(update_fields=["noshow_count"])
        request(  # 취소 이력
            eligible[5], slots[0], next_date(slots[0]),
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
            title="학원 굿즈 수요조사",
            body="원하는 굿즈를 댓글로 남겨주세요.",
        )
        return notice_week

    # --- 결제 -------------------------------------------------------------

    @staticmethod
    def _create_payments(students, parents, staff, now):
        """교재 1 + 주문 혼합(미결제·결제완료·배부완료) + 결제 트랜잭션."""
        product = Product.objects.create(name="로직엔제 교재 Vol.1", price=45000)
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
                f"workbook/demo/{target_session.session_id}-{student.unique_id}.png",
                ContentFile(_PNG_BYTES),
            )
            WorkbookSubmission.objects.create(
                student=student,
                session=target_session,
                image_path=path,
                performance_grade=grade,
                recognized_unique_id=(
                    student.unique_id if match_status is not None else None
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

    def _print_summary(self, triggers, eligible):
        w = self.stdout.write
        w(self.style.SUCCESS("seed_demo 완료 — 데모 데이터 생성됨(전체 초기화 후 재생성)"))
        w("")
        w("로그인 계정 (비밀번호는 전부 test1234):")
        w("  역할     아이디                          비고")
        w("  대표     01000000001                    한종철")
        w("  관리자   01000000002                    김관리")
        w("  조교     01000000003                    박조교")
        w("  학생     01010000001 ~ 01010000030      30명(29·30번은 예비등록)")
        w("  학부모   01020000001 ~ 01020000010      10명(자녀 1~2명 연동)")
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
