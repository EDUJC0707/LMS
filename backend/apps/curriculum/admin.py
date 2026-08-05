"""curriculum 관리자 등록 — Course/CourseWeek/WeekDayPlan/CourseEnrollment."""
from django.contrib import admin

from .models import Course, CourseEnrollment, CourseWeek, WeekDayPlan


class CourseWeekInline(admin.TabularInline):
    model = CourseWeek
    extra = 0


class WeekDayPlanInline(admin.TabularInline):
    model = WeekDayPlan
    extra = 0


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
    list_display = ("enrollment_id", "student", "course", "class_name", "status", "enrolled_at")
    list_filter = ("status", "course", "class_name")
    search_fields = ("student__matching_key", "student__user__name", "course__name")
