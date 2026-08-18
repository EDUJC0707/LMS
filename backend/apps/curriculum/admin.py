"""curriculum 관리자 등록 — Subject/Course/Class/CourseWeek/WeekDayPlan/CourseEnrollment."""
from django.contrib import admin

from .models import Class, Course, CourseEnrollment, CourseWeek, Subject, WeekDayPlan


class CourseWeekInline(admin.TabularInline):
    model = CourseWeek
    extra = 0


class WeekDayPlanInline(admin.TabularInline):
    model = WeekDayPlan
    extra = 0


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ("subject_id", "track", "name")
    list_filter = ("track",)
    search_fields = ("name",)


@admin.register(Class)
class ClassAdmin(admin.ModelAdmin):
    """반. `uses_payssam` 이 여기 있는 유일한 이유는 러셀이다(FLOW 2-7) —
    켜지 않으면 그 반에서는 청구가 나가지 않는다."""

    list_display = ("class_id", "course", "name", "start_date", "uses_payssam", "is_active")
    list_filter = ("uses_payssam", "is_active", "course")
    search_fields = ("name", "course__name")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("course_id", "name", "target_grade", "is_active", "created_at")
    list_filter = ("is_active", "target_grade")
    search_fields = ("name",)
    inlines = [CourseWeekInline]


@admin.register(CourseWeek)
class CourseWeekAdmin(admin.ModelAdmin):
    list_display = (
        "week_id", "course", "week_no", "title", "start_date", "end_date", "release_at",
    )
    list_filter = ("course",)
    search_fields = ("title", "offline_notice", "course__name")
    inlines = [WeekDayPlanInline]


@admin.register(WeekDayPlan)
class WeekDayPlanAdmin(admin.ModelAdmin):
    list_display = ("plan_id", "week", "day_no", "title", "display_order")
    list_filter = ("week__course",)
    search_fields = ("title", "content")


@admin.register(CourseEnrollment)
class CourseEnrollmentAdmin(admin.ModelAdmin):
    list_display = ("enrollment_id", "student", "course", "klass", "status", "enrolled_at")
    list_filter = ("status", "course", "klass")
    search_fields = ("student__matching_key", "student__user__name", "course__name")
