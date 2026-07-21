"""accounts 도메인 — 계정·학생·학부모·RBAC (DB 설계 도메인 1).

정렬 테이블(docs/db/lms-db-design-2026-07-15.md §2 도메인 1):
  - users            로그인 계정. role: 대표/관리자/조교/학생/학부모
  - students         학생·원번(허브). enrollment_status: 예비등록/등록/퇴원
  - parents          학부모 로그인 계정(연락처 → 계정 승격)
  - parent_students  학부모↔자녀 M:N 연동(다자녀 드롭다운)

그린필드이므로 설계 문서의 expand-contract 중간 단계(is_registered 백필,
parents.student_id/relation/is_primary 병행)는 건너뛰고 최종 상태로 구현한다.
"""
from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.utils import timezone


class UserManager(BaseUserManager):
    """login_id 기반 계정 생성. 일괄생성(PRD 3.1.5)도 이 매니저를 쓴다."""

    use_in_migrations = True

    def create_user(self, login_id, password=None, **extra_fields):
        if not login_id:
            raise ValueError("login_id는 필수다.")
        # role 미지정 시 ''로 저장되면 5개 role 어디에도 속하지 않는 유령 계정이
        # 된다(DB CHECK를 두지 않는 설계라 DB도 못 막음). 여기서 차단한다.
        # 값집합 검증까지는 하지 않는다 — 값 추가 시 무마이그레이션 원칙 유지.
        if not extra_fields.get("role"):
            raise ValueError("role은 필수다.")
        user = self.model(login_id=login_id, **extra_fields)
        user.set_password(password)  # None이면 unusable password
        user.save(using=self._db)
        return user

    def create_superuser(self, login_id, password=None, **extra_fields):
        extra_fields.setdefault("role", User.Role.OWNER)
        extra_fields.setdefault("must_change_password", False)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("superuser는 is_superuser=True여야 한다.")
        return self.create_user(login_id, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    """`users` — 로그인 계정 (설계 문서 도메인 1 `users`, PRD §5 인증·권한).

    - 인증은 세션 기반(JWT 미사용), USERNAME_FIELD=login_id.
    - role은 설계 문서 값집합(한국어) 그대로. DB CHECK는 두지 않는다
      (설계 원칙: 값 추가 시 무마이그레이션).
    - is_staff는 DB 컬럼으로 만들지 않고 role 기반 property로 산출한다
      (대표·관리자·조교 → admin 접근 허용).
    - AbstractBaseUser/PermissionsMixin 채택으로 설계 문서 외 Django 표준
      컬럼(last_login, is_superuser)과 M2M 테이블(users_groups,
      users_user_permissions)이 생긴다 — 설계 문서 users 절 각주에 기재됨.
    """

    class Role(models.TextChoices):
        OWNER = "대표", "대표"
        ADMIN = "관리자", "관리자"
        ASSISTANT = "조교", "조교"
        STUDENT = "학생", "학생"
        PARENT = "학부모", "학부모"

    user_id = models.BigAutoField(primary_key=True)
    login_id = models.CharField("로그인 아이디", max_length=50, unique=True)
    # Django 관례 필드명(password)을 쓰되 컬럼명은 설계(password_hash)와 정렬.
    password = models.CharField("password", max_length=128, db_column="password_hash")
    role = models.CharField("역할", max_length=10, choices=Role.choices)
    name = models.CharField("이름", max_length=50)
    phone = models.CharField("연락처", max_length=20, blank=True, default="")
    is_active = models.BooleanField("활성", default=True)
    # 일괄생성 계정은 최초 로그인 시 비밀번호 변경 강제(PRD 3.1.5).
    must_change_password = models.BooleanField("비밀번호 변경 필요", default=True)
    password_changed_at = models.DateTimeField("비밀번호 변경 시각", null=True, blank=True)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    USERNAME_FIELD = "login_id"
    REQUIRED_FIELDS = ["name"]  # createsuperuser 성립 최소 조건(name NN·무기본값)

    objects = UserManager()

    class Meta:
        db_table = "users"
        verbose_name = "계정"
        verbose_name_plural = "계정"

    def __str__(self):
        return f"{self.login_id}({self.get_role_display()})"

    @property
    def is_staff(self):
        """admin 접근: 대표·관리자·조교. DB 컬럼 아닌 role 기반 산출값."""
        return self.role in {self.Role.OWNER, self.Role.ADMIN, self.Role.ASSISTANT}

    def set_password(self, raw_password):
        """비밀번호 설정 시 password_changed_at 갱신(설계 users.password_changed_at)."""
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()


class Student(models.Model):
    """`students` — 학생·원번 허브 (설계 문서 도메인 1 `students`).

    - user는 null 허용: PRD 3.1.5상 명단·연락처가 먼저 입력되고 계정은
      출석일 1일 전 자동 발급되므로 사람 행이 계정보다 먼저 생긴다.
      단, students에는 name/phone 컬럼이 없으므로(설계 문서 구조) 명단 입력
      시점에 users 행(role=학생, unusable password)을 함께 만들어 이름·연락처를
      담고, D-1 배치는 랜덤 비밀번호 발급·SMS 발송·credentials_sent_at 스탬프만
      담당한다. (학부모는 parents.name/phone이 있어 사람 행 선행이 그대로 성립.)
    - unique_id(원번)는 이름과 함께 쓰는 매칭키라 단독 UNIQUE가 아니다(인덱스만).
    - 등록 생애주기는 enrollment_status 단일 상태(soft-delete). is_registered 없음.
    """

    class EnrollmentStatus(models.TextChoices):
        PRE_REGISTERED = "예비등록", "예비등록"
        REGISTERED = "등록", "등록"
        WITHDRAWN = "퇴원", "퇴원"

    student_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="user_id",
        related_name="student",
        verbose_name="로그인 계정",
    )
    unique_id = models.CharField("원번", max_length=20, db_index=True)
    grade = models.CharField("학년", max_length=20, blank=True, default="")
    school = models.CharField("학교", max_length=100, blank=True, default="")
    registered_at = models.DateTimeField("등록 처리 시각", null=True, blank=True)
    noshow_count = models.PositiveIntegerField("노쇼 누적", default=0)
    clinic_banned = models.BooleanField("클리닉 이용 정지", default=False)
    credentials_sent_at = models.DateTimeField("계정정보 발송 시각", null=True, blank=True)
    # 아래 문자열 컬럼들은 설계 문서가 NULL로 명시 — ''와 미입력을 구분한다.
    current_class = models.CharField("현재 반", max_length=50, null=True, blank=True)  # noqa: DJ001
    youtube_email = models.EmailField("유튜브 계정", null=True, blank=True)  # noqa: DJ001
    enrollment_status = models.CharField(
        "등록 상태",
        max_length=15,
        choices=EnrollmentStatus.choices,
        default=EnrollmentStatus.PRE_REGISTERED,
    )
    withdrawn_at = models.DateTimeField("퇴원 처리 시각", null=True, blank=True)
    # -- 잠정: '등록 안 한 학생' 정의 확정 필요(설계 문서 §6)
    withdrawn_reason = models.CharField("퇴원 사유", max_length=200, null=True, blank=True)  # noqa: DJ001
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="withdrawn_by",
        related_name="withdrawn_students",
        verbose_name="퇴원 처리자",
    )

    class Meta:
        db_table = "students"
        verbose_name = "학생"
        verbose_name_plural = "학생"

    def __str__(self):
        return f"학생 {self.unique_id} ({self.get_enrollment_status_display()})"


class Parent(models.Model):
    """`parents` — 학부모 (설계 문서 도메인 1 `parents`, PRD 3.4).

    - user는 null 허용: 학생과 동일하게 연락처(사람 행)가 먼저 입력되고
      계정은 출석일 1일 전 자동 발급된다(PRD 3.1.5·3.4).
    - 학생 결합(student_id/relation/is_primary)은 parent_students로 이관된
      최종 상태로 구현(그린필드).
    """

    parent_id = models.BigAutoField(primary_key=True)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_column="user_id",
        related_name="parent",
        verbose_name="로그인 계정",
    )
    name = models.CharField("이름", max_length=50, null=True, blank=True)  # noqa: DJ001  (설계상 NULL)
    phone = models.CharField("연락처", max_length=20)  # 청구서·리포트·SMS 수신(NN)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "parents"
        verbose_name = "학부모"
        verbose_name_plural = "학부모"

    def __str__(self):
        return f"학부모 {self.name or self.phone}"


class ParentStudent(models.Model):
    """`parent_students` — 학부모↔자녀 M:N (설계 문서 도메인 1, PRD 3.4).

    설계는 복합 PK(parent_id, student_id)이지만 현재 Django 5.1에는
    CompositePrimaryKey(5.2+)가 없어 대리 PK + UniqueConstraint(parent, student)로
    동일한 유일성을 보장한다. 5.2 승급 시 복합 PK 전환을 검토한다.
    """

    parent = models.ForeignKey(
        Parent,
        on_delete=models.CASCADE,
        db_column="parent_id",
        related_name="parent_students",
        verbose_name="학부모",
    )
    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        db_column="student_id",
        related_name="parent_students",
        verbose_name="자녀",
    )
    # 부/모/조부모 등. 설계상 NULL 컬럼.
    relation = models.CharField("관계", max_length=10, null=True, blank=True)  # noqa: DJ001
    is_primary_contact = models.BooleanField("주 수신처", default=False)
    created_at = models.DateTimeField("생성 시각", auto_now_add=True)

    class Meta:
        db_table = "parent_students"
        verbose_name = "학부모-자녀 연동"
        verbose_name_plural = "학부모-자녀 연동"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "student"],
                name="uq_parent_students_parent_student",
            ),
        ]

    def __str__(self):
        return f"{self.parent_id}↔{self.student_id}({self.relation or '관계미상'})"
