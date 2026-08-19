"""대조 6분기 — DB 없이 전부 검사한다(판정이 순수 함수라서).

**반쪽 키의 범위만 DB 를 탄다**(FLOW 3-3 ② — 아래 `ClassRosterTests`). 판정은
여전히 순수하고, 좁히는 것은 후보를 고르는 쪽이다.
"""
import datetime

from django.test import SimpleTestCase, TestCase

from apps.accounts.models import Student, User
from apps.curriculum.models import Class, Course, CourseEnrollment, CourseWeek

from .models import AnswerSheet, ClassSession, Exam
from .omr_match import class_roster, match_sheet, resolve

_MS = AnswerSheet.MatchStatus


class FakeStudent:
    def __init__(self, matching_key):
        self.matching_key = matching_key


def roster(*keys):
    return [FakeStudent(key) for key in keys]


def make_omr_student(login_id, name, matching_key, klass):
    user = User.objects.create_user(
        login_id=login_id, password="pw-Secret-77!", name=name, role=User.Role.STUDENT
    )
    student = Student.objects.create(
        user=user,
        matching_key=matching_key,
        enrollment_status=Student.EnrollmentStatus.REGISTERED,
    )
    CourseEnrollment.objects.create(student=student, course=klass.course, klass=klass)
    return student


class ResolveTests(SimpleTestCase):
    def test_one_student_with_that_key_is_normal(self):
        people = roster("김하늘0001", "박민준0002")

        student, status = resolve(people, "김하늘", "0001")

        self.assertIs(student, people[0])
        self.assertEqual(status, _MS.MATCHED)

    def test_two_students_sharing_a_key_can_never_be_told_apart(self):
        """동명이인 + 같은 뒷4. 지면에 접미사가 없어 원리상 못 가른다."""
        people = roster("김하늘0001", "김하늘0001")

        student, status = resolve(people, "김하늘", "0001")

        self.assertIsNone(student)
        self.assertEqual(status, _MS.DUPLICATE)

    def test_nobody_matches_either_half_is_missing(self):
        student, status = resolve(roster("김하늘0001"), "최유진", "9999")

        self.assertIsNone(student)
        self.assertEqual(status, _MS.MISSING)

    def test_halves_that_disagree_are_a_mismatch(self):
        """이름은 명단에 있는데 붙여 놓으면 아무도 아니다 — 한쪽을 잘못 읽었다."""
        student, status = resolve(roster("김하늘0001"), "김하늘", "9999")

        self.assertIsNone(student)
        self.assertEqual(status, _MS.MISMATCH)

    def test_phone_alone_settles_it_when_only_one_student_ends_that_way(self):
        """전화칸을 안 쓴 장이 실물에 있었다 — 이름만으로도 확정될 수 있다."""
        people = roster("김하늘0001", "박민준0002")

        student, status = resolve(people, "김하늘", None)

        self.assertIs(student, people[0])
        self.assertEqual(status, _MS.PARTIAL)

    def test_half_a_key_with_several_candidates_goes_to_a_person(self):
        people = roster("김하늘0001", "김하늘0002")

        student, status = resolve(people, "김하늘", None)

        self.assertIsNone(student)
        self.assertEqual(status, _MS.PARTIAL)

    def test_nothing_readable_is_invalid(self):
        student, status = resolve(roster("김하늘0001"), None, None)

        self.assertIsNone(student)
        self.assertEqual(status, _MS.INVALID)

    def test_a_name_the_card_cannot_spell_still_matches(self):
        """카드에 쌍자음이 없어 `꽃님` 은 `곷님` 으로 들어온다.

        양쪽을 낮춰 비교하지 않으면 그 학생은 시험마다 불일치로 떨어지고
        조교가 매번 같은 사람을 손으로 고른다.
        """
        people = roster("꽃님0007")

        student, status = resolve(people, "곷님", "0007")

        self.assertIs(student, people[0])
        self.assertEqual(status, _MS.MATCHED)

    def test_half_a_key_only_looks_inside_the_class(self):
        """반쪽 키는 반 안에서 찾는다(FLOW 3-3 ②).

        전교에 같은 이름이 하나 더 있어도 그 학생은 이 반 명단에 없다 — 넓게
        보면 후보가 둘이 돼 보류로 떨어지거나 남의 반 사람에게 확정된다.
        """
        mine, stranger = roster("김하늘0001", "김하늘0002")

        student, status = resolve([mine, stranger], "김하늘", None, klass_roster=[mine])

        self.assertIs(student, mine)
        self.assertEqual(status, _MS.PARTIAL)

    def test_a_full_key_still_reaches_outside_the_class(self):
        """현보로 온 학생이 여기서 붙는다 — 대조키가 온전하면 사람이 갈린다."""
        mine, visitor = roster("김하늘0001", "박지우0009")

        student, status = resolve([mine, visitor], "박지우", "0009", klass_roster=[mine])

        self.assertIs(student, visitor)
        self.assertEqual(status, _MS.MATCHED)


class ClassRosterTests(TestCase):
    """`class_roster` — 시험에 걸린 회차의 반으로 후보를 좁힌다(FLOW 3-3 ②)."""

    @classmethod
    def setUpTestData(cls):
        cls.exam = Exam.objects.create(name="3주차 미니", exam_date=datetime.date(2026, 9, 17))
        course = Course.objects.create(name="2026 여름 N제", total_weeks=3)
        cls.thursday = Class.objects.create(course=course, name="목 6.5 대치러셀")
        tuesday = Class.objects.create(course=course, name="화 6.5 대치러셀")
        week = CourseWeek.objects.create(course=course, week_no=3)
        ClassSession.objects.create(
            session_date=datetime.date(2026, 9, 17),
            course_week=week,
            klass=cls.thursday,
            week_no=3,
            exam=cls.exam,
        )
        cls.mine = make_omr_student("stu-mine", "김하늘", "김하늘0001", cls.thursday)
        cls.namesake = make_omr_student("stu-twin", "김하늘", "김하늘0002", tuesday)

    def all_students(self):
        return list(Student.objects.select_related("user").all())

    def test_a_namesake_in_another_class_is_not_a_candidate(self):
        """이름만 읽힌 장 — 전교를 훑으면 둘이라 보류로 떨어졌다."""
        student, status = match_sheet(
            "김하늘", None, roster=self.all_students(), klass_roster=class_roster(self.exam)
        )

        self.assertEqual(student, self.mine)
        self.assertEqual(status, _MS.PARTIAL)

    def test_without_the_class_scope_the_same_sheet_goes_to_a_person(self):
        """좁히기 전 동작 — 이 테스트가 좁힘의 값을 말한다."""
        student, status = match_sheet("김하늘", None, roster=self.all_students())

        self.assertIsNone(student)
        self.assertEqual(status, _MS.PARTIAL)

    def test_an_exam_with_no_class_keeps_the_whole_school(self):
        """반이 안 걸린 회차는 좁힐 근거가 없다 — 종전대로 전체 명단이다."""
        lonely = Exam.objects.create(name="회차 미매핑", exam_date=datetime.date(2026, 9, 17))

        self.assertIsNone(class_roster(lonely))
