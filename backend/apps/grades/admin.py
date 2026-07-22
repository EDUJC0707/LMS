"""grades 관리자 등록 — 성적·출결·OMR·과제·문제은행·약점체크·워크북."""
from django.contrib import admin

from .models import (
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


class QuestionInline(admin.TabularInline):
    model = Question
    extra = 0


class AttendanceInline(admin.TabularInline):
    model = Attendance
    extra = 0


@admin.register(ClassSession)
class ClassSessionAdmin(admin.ModelAdmin):
    list_display = (
        "session_id", "session_date", "session_no", "target_grade", "exam", "course_week",
    )
    list_filter = ("session_date", "target_grade")
    search_fields = ("memo",)
    inlines = [AttendanceInline]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = (
        "id", "session", "student", "status", "exam_taken", "marked_by",
        "created_at", "updated_at",
    )
    list_filter = ("status", "exam_taken", "session__session_date")
    search_fields = ("student__unique_id", "student__user__name")


@admin.register(Exam)
class ExamAdmin(admin.ModelAdmin):
    list_display = (
        "exam_id", "name", "exam_date", "round_no", "target_grade", "avg_score",
    )
    list_filter = ("exam_date", "target_grade")
    search_fields = ("name",)
    inlines = [QuestionInline]


@admin.register(Question)
class QuestionAdmin(admin.ModelAdmin):
    list_display = (
        "question_id", "exam", "q_number", "answer", "points",
        "unit_major", "theme_tag", "question_format", "wrong_rate",
    )
    list_filter = ("question_format", "exam")
    search_fields = ("unit_major", "unit_minor", "theme_tag")


@admin.register(AnswerSheet)
class AnswerSheetAdmin(admin.ModelAdmin):
    list_display = (
        "sheet_id", "exam", "student", "recognized_unique_id", "recognized_name",
        "match_status", "is_corrected", "created_at",
    )
    list_filter = ("match_status", "is_corrected", "exam")
    search_fields = ("recognized_unique_id", "recognized_name", "student__unique_id")


@admin.register(SheetAnswer)
class SheetAnswerAdmin(admin.ModelAdmin):
    list_display = (
        "id", "sheet", "question", "marked", "result",
        "extra_practice_marked", "is_corrected",
    )
    list_filter = ("result", "extra_practice_marked", "is_corrected")


@admin.register(Score)
class ScoreAdmin(admin.ModelAdmin):
    list_display = (
        "score_id", "exam", "student", "total_score", "max_score",
        "percentile", "rank_top_pct", "is_taken",
    )
    list_filter = ("is_taken", "exam")
    search_fields = ("student__unique_id", "student__user__name")


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = ("id", "session", "student", "done", "memo")
    list_filter = ("done", "session__session_date")
    search_fields = ("student__unique_id", "student__user__name")


@admin.register(QuestionBankItem)
class QuestionBankItemAdmin(admin.ModelAdmin):
    list_display = (
        "bank_item_id", "bank_type", "unit_major", "unit_minor",
        "theme_tag", "difficulty", "is_active",
    )
    list_filter = ("bank_type", "is_active")
    search_fields = ("unit_major", "unit_minor", "theme_tag", "source")


@admin.register(QuestionSimilarMap)
class QuestionSimilarMapAdmin(admin.ModelAdmin):
    list_display = ("map_id", "question", "similar_bank_item", "ordinal")
    list_filter = ("ordinal",)


@admin.register(WeaknessCheckPdf)
class WeaknessCheckPdfAdmin(admin.ModelAdmin):
    list_display = (
        "pdf_id", "exam", "student", "status", "page_count", "generated_at",
    )
    list_filter = ("status", "exam")
    search_fields = ("student__unique_id", "student__user__name")


@admin.register(WorkbookSubmission)
class WorkbookSubmissionAdmin(admin.ModelAdmin):
    list_display = (
        "submission_id", "student", "session", "performance_grade",
        "uploaded_by", "created_at",
    )
    list_filter = ("performance_grade", "session__session_date")
    search_fields = ("student__unique_id", "student__user__name")
