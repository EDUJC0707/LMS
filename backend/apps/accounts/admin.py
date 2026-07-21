"""accounts 관리자 등록 — User/Student/Parent/ParentStudent."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import Parent, ParentStudent, Student, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """커스텀 User(AbstractBaseUser) 전용 admin.

    is_staff는 DB 컬럼이 아니라 role 기반 property라 list_filter에는 못 쓰고
    role 필터로 대신한다.
    """

    ordering = ("login_id",)
    list_display = ("login_id", "name", "role", "is_active", "must_change_password", "is_staff")
    list_filter = ("role", "is_active", "must_change_password")
    search_fields = ("login_id", "name", "phone")
    readonly_fields = ("last_login", "password_changed_at", "created_at")
    filter_horizontal = ("groups", "user_permissions")
    fieldsets = (
        (None, {"fields": ("login_id", "password")}),
        ("개인 정보", {"fields": ("name", "phone", "role")}),
        (
            "권한",
            {
                "fields": (
                    "is_active",
                    "must_change_password",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("주요 일자", {"fields": ("last_login", "password_changed_at", "created_at")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("login_id", "name", "role", "password1", "password2"),
            },
        ),
    )


class ParentStudentInline(admin.TabularInline):
    model = ParentStudent
    extra = 0


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("student_id", "unique_id", "grade", "school", "enrollment_status", "user")
    list_filter = ("enrollment_status", "grade", "clinic_banned")
    search_fields = ("unique_id", "school", "user__name", "user__login_id")
    inlines = [ParentStudentInline]


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ("parent_id", "name", "phone", "user")
    search_fields = ("name", "phone", "user__login_id")
    inlines = [ParentStudentInline]


@admin.register(ParentStudent)
class ParentStudentAdmin(admin.ModelAdmin):
    list_display = ("parent", "student", "relation", "is_primary_contact")
    list_filter = ("is_primary_contact",)
