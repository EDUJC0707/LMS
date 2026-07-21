# EduJC LMS — 배포 가이드 (Fly.io 도쿄)

> **소유 모델**: 모든 리소스는 **Fly Organization**이 소유한다. org에 다 만들어 두면,
> 나중에 멤버가 나가거나 배포 토큰을 발급/회수해도 리소스는 그대로 유지된다.
> 나중에 org에서 빠질 때 챙길 것: (1) org에 admin 최소 1명, (2) 결제 카드 주체.
>
> **레포와 무관**: `fly deploy`는 로컬 소스를 빌드해 올린다(GitHub 안 거침).
> 로컬 도커 불필요(Fly 원격 빌더 사용). GitHub 로그인 없이 push만 되는 상태로 OK.

레포 2개 / 앱 2개 / 서버·DB 공용:
```
Fly org (도쿄 nrt)
├─ app  edujc-lms     ← 이 레포                (Django A)
├─ app  edujc-qbank   ← 문제툴 레포(도훈)         (Django B)
├─ pg   edujc-pg      ← Postgres 1클러스터        · database: lms / qbank
├─ storage edujc-lms-storage    (Tigris/S3)     · OMR·워크북·PDF
├─ storage edujc-qbank-storage  (Tigris/S3)     · 문제·선지·표 이미지·원천PDF
└─ redis edujc-redis  (Upstash)                 · Celery (일단 LMS)
```

---

## 0. 인증 (택1)
flyctl은 설치됨(`~/.fly/bin/flyctl`). PATH: `export PATH="$HOME/.fly/bin:$PATH"`
- **A. 대화형 로그인**: `fly auth login` (브라우저)
- **B. 토큰 주입(이 머신에서 브라우저 로그인 없이)**: 로그인된 다른 환경/웹에서 발급 후
  ```bash
  # 셋업까지 하려면 org 토큰(넓은 권한). 짧은 만료 권장.
  fly tokens create org --name edujc-setup --expiry 2h    # → FlyV1 fm2_...
  # 이 머신:
  export FLY_API_TOKEN="FlyV1 fm2_..."
  ```
- 이후 배포 전용은 **좁은 토큰**: `fly tokens create deploy -a edujc-lms`

## 1. org · 결제
```bash
fly orgs create EduJC            # 이미 있으면 생략
# 결제 카드 등록은 대시보드(fly.io/dashboard/<org>/billing)에서 1회
fly orgs invite <개발자이메일> --org EduJC   # 협업자 초대(선택)
```

## 2. LMS 앱 셋업 (edujc-lms)
```bash
# 2-1) 앱 생성
fly apps create edujc-lms --org EduJC

# 2-2) Postgres 클러스터 + lms database attach (DATABASE_URL 자동 주입)
fly postgres create --name edujc-pg --org EduJC --region nrt --vm-size shared-cpu-1x --volume-size 10
fly postgres attach edujc-pg -a edujc-lms --database-name lms --database-user lms
#   (참고: PRD는 Managed Postgres[MPG] 명시 — 안정화 시 `fly mpg create`로 대체 가능)

# 2-3) Redis (Upstash) — REDIS_URL 자동 주입
fly redis create --org EduJC --region nrt --name edujc-redis
fly secrets set REDIS_URL="<위 출력의 redis:// URL>" CELERY_BROKER_URL="<동일>" -a edujc-lms

# 2-4) Tigris 오브젝트 스토리지 (이미지/PDF 버킷)
fly storage create --org EduJC -a edujc-lms --name edujc-lms-storage
#   ⚠️ Tigris는 AWS_ACCESS_KEY_ID/SECRET/ENDPOINT_URL_S3/BUCKET_NAME 을 주입하지만,
#   base.py 는 AWS_STORAGE_BUCKET_NAME · AWS_S3_ENDPOINT_URL 이름을 읽는다 → 별칭 set:
fly secrets set \
  AWS_STORAGE_BUCKET_NAME="edujc-lms-storage" \
  AWS_S3_ENDPOINT_URL="https://t3.storage.dev" \
  AWS_S3_REGION_NAME="auto" \
  -a edujc-lms
#   (ACCESS_KEY_ID/SECRET_ACCESS_KEY 는 fly storage create가 이미 주입함)

# 2-5) 앱 시크릿
fly secrets set \
  DJANGO_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  DJANGO_DEBUG="False" \
  ALLOWED_HOSTS="edujc-lms.fly.dev" \
  CSRF_TRUSTED_ORIGINS="https://edujc-lms.fly.dev" \
  CORS_ALLOWED_ORIGINS="https://<프론트도메인>" \
  -a edujc-lms
#   (SENTRY_DSN 은 Sentry 프로젝트 만들면 추가)

# 2-6) 배포 (⚠️ 레포 루트에서, 빌드 컨텍스트=루트 → -c 로 fly.toml 지정)
cd /path/to/LMS
fly deploy -c infra/fly.toml -a edujc-lms
#   release_command(migrate)가 자동 실행됨 → empty 배포 완료

# 2-7) 검증
curl https://edujc-lms.fly.dev/healthz     # {"status":"ok"}
fly logs -a edujc-lms
```

## 3. 문제툴 앱 (edujc-qbank) — 같은 절차, DB만 같은 클러스터의 다른 database
```bash
fly apps create edujc-qbank --org EduJC
fly postgres attach edujc-pg -a edujc-qbank --database-name qbank --database-user qbank
fly storage create --org EduJC -a edujc-qbank --name edujc-qbank-storage
# 이후 secrets·deploy 는 문제툴 레포의 fly.toml/Dockerfile로 (도훈 담당)
```
> DB는 **한 클러스터 안에 database 2개(lms/qbank)** → 서버 공용, 조인 가능, 스키마는 각자.
> 권한을 더 조이려면 lms 유저에게 qbank는 SELECT만 GRANT(나중에).

## 4. 배포 토큰 (이 머신/CI용, 넓은 권한 회수 후)
```bash
fly tokens create deploy -a edujc-lms      # 이 앱 배포 전용(생성 권한 없음)
# 이 머신: export FLY_API_TOKEN="<deploy 토큰>"  → fly deploy 만 가능
```

---

## 5. 🗂 이미지/파일 스토리지 규약 (어디에 뭐가 들어가나)

**원칙**: 큰 파일은 **DB에 넣지 않는다.** 오브젝트 스토리지(Tigris/S3)에 두고 **DB엔 경로(`*_path`)만.**
Django 모델의 `FileField/ImageField` 가 자동으로 default storage(=Tigris)로 업로드됨.

### LMS 버킷 `edujc-lms-storage`
| 용도 | `upload_to` 경로 규약 | DB 참조 |
|---|---|---|
| OMR 스캔본(PDF/jpeg) | `omr/{exam_id}/{sheet_id}.pdf` | `answer_sheets.scan_image_path` |
| 워크북 사진 | `workbook/{session_id}/{student_id}.jpg` | `workbook_submissions.image_path` |
| 약점체크 PDF | `weakness/{exam_id}/{student_id}.pdf` | `weakness_check_pdfs.pdf_path` |
| 성적표 PDF | `report/{exam_id}/{student_id}.pdf` | (해당 표) |

### 문제툴 버킷 `edujc-qbank-storage` (도훈 소유, LMS는 관여 안 함)
| 용도 | 경로 규약(예시) |
|---|---|
| 원천 PDF | `source-pdf/{batch}/{file}.pdf` |
| 문제 본문/선지/표 이미지 | `question/{bank_item_id}/stem.png`, `.../choice-{n}.png`, `.../table-{n}.png` |
| 확정(published) 렌더 스냅샷 | `question/{bank_item_id}/rendered.png` ← LMS가 소비하는 단 하나 |

> **선지 안 이미지·표 안 이미지**의 복잡성은 전부 문제툴 버킷+스키마 안에서 처리하고,
> LMS는 published된 **렌더 스냅샷 1장**만 참조한다(투 레이어). LMS 버킷엔 문제 이미지가 안 들어옴.

**모델 예시 (참고)**
```python
class AnswerSheet(models.Model):
    scan = models.FileField(upload_to="omr/%(exam_id)s/")   # → Tigris 자동 업로드
    # DB엔 이 필드의 경로 문자열만 저장됨
```

---

## 나중에 org에서 빠질 때
1. org에 다른 **admin 1명** 남기기 (`fly orgs` 멤버 확인)
2. **결제 카드** 주체 지정(빠지는 사람 카드면 교체)
3. 이 머신/CI엔 **deploy 토큰**만 남기고 개인 세션 로그아웃(`fly auth logout`)
4. 리소스(앱·DB·스토리지)는 org 소유라 **그대로 유지됨**
