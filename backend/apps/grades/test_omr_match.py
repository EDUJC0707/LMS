"""대조 6분기 — DB 없이 전부 검사한다(판정이 순수 함수라서)."""
from django.test import SimpleTestCase

from .models import AnswerSheet
from .omr_match import resolve

_MS = AnswerSheet.MatchStatus


class FakeStudent:
    def __init__(self, matching_key):
        self.matching_key = matching_key


def roster(*keys):
    return [FakeStudent(key) for key in keys]


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
