"""반별 격자 — 가로 주차 · 세로 학생 (FLOW 3-1 · 5-1).

조교가 반을 열면 보는 판이다. 회차 하나가 **세로 한 줄**(그 주 전원의 출결표 —
3-2)이라면 여기는 반 전체를 한 번에 본다. 학부모 전화가 오면 보는 **가로 한 줄**
(그 학생이 이 반에서 어땠는가)이 곧 격자의 한 행이다.

**`x` 는 여기서 만들지 않는다.** 그때 이 반에 없던 학생의 칸(FLOW 3-1)은 저장도
전송도 하지 않는다 — 그 학생의 **첫 기록보다 앞선 주차**면 화면이 그린다. 서버가
보내는 것은 주차 목록과 칸 값뿐이고, 첫 기록이 몇 주차인지는 그 값에서 그대로
읽힌다(값이 있는 첫 칸). 같은 사실을 서버가 한 번 더 계산해 실어 보내면 두 계산이
갈릴 수 있어 싣지 않는다(사본 금지 — key_considerations §6).

`cells` 는 **`weeks` 와 자리를 맞춘 리스트**다(딕셔너리가 아니다). 주차 번호를 키로
쓰면 JSON 이 정수 키를 문자열로 바꿔 화면이 매번 형변환해야 한다.

명단은 **회차 명단(`attendance_admin.load_roster`)의 반 단위 판**이다 — 이 반 수강생
**또는** 이 반 회차에 출결 기록이 있는 학생. 뒤쪽이 없으면 반을 옮긴 학생의 줄이
옛 반 격자에서 통째로 사라진다(FLOW 3-9). 기록은 옛 반에 남는데 그것을 볼 자리가
없어지는 셈이다. 퇴원생도 남는다 — 다녔던 주차의 기록이 그 학생의 이력이다.

**읽기 전용이다.** 출결을 고치는 문은 주차(3-2)뿐이고 내보내는 것은 `출결 확정`
(3-5) 하나다. 칸을 여기서 바로 고치게 하면 영상과 통지가 확정을 거치지 않고 갈린다.
"""
from django.db import models

from apps.accounts.models import Student
from apps.curriculum.models import Class, CourseEnrollment

from .models import Attendance


def load_class(class_id):
    """반 + 커리 1쿼리. 없으면 None — 뷰가 404 로 바꾼다."""
    return Class.objects.select_related("course").filter(pk=class_id).first()


def build_grid_payload(klass):
    """격자 한 판 — 주차 · 학생 · 학생마다 주차 수만큼의 칸.

    쿼리는 **반 크기와 무관하게 셋**이다(반 로드까지 넷): 회차 · 명단 · 출결.
    학생 × 주차라 한 번만 새도 그대로 N+1 이 된다 — 출결은 조인 없이
    `values_list` 로 통째로 받아 파이썬에서 자리에 꽂는다.
    """
    weeks = list(klass.sessions.order_by("week_no", "session_id"))
    position = {s.session_id: i for i, s in enumerate(weeks)}
    students = list(
        Student.objects.filter(
            models.Q(
                course_enrollments__klass=klass,
                course_enrollments__status=CourseEnrollment.Status.ENROLLED,
            )
            | models.Q(attendances__session__klass=klass)
        )
        .distinct()
        .select_related("user")
        .order_by("student_id")
    )
    cells = {s.student_id: [None] * len(weeks) for s in students}
    rows = Attendance.objects.filter(session__klass=klass).values_list(
        "student_id", "session_id", "status"
    )
    for student_id, session_id, status in rows:
        row, index = cells.get(student_id), position.get(session_id)
        if row is not None and index is not None:
            row[index] = status
    return {
        "klass": {
            "class_id": klass.class_id,
            "name": klass.name,
            "course_name": klass.course.name,
        },
        "weeks": [
            {
                "session_id": s.session_id,
                "week_no": s.week_no,
                "session_date": s.session_date.isoformat(),
            }
            for s in weeks
        ],
        "students": [
            {
                "student_id": s.student_id,
                "name": s.user.name if s.user else None,
                "login_id": s.user.login_id if s.user else None,
                "enrollment_status": s.enrollment_status,
                "cells": cells[s.student_id],
            }
            for s in students
        ],
    }
