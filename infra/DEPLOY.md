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
└─ redis edujc-redis  (Upstash)                 · Celery (일단 LMS) ⛔ **미생성 — 6장 참조**
```

> **실제 가동 현황(2026-07-22 확인)**: `edujc-lms` web 1대 + `edujc-pg` primary 1대만 떠 있다.
> **Celery worker와 Redis는 의도적으로 미가동** — 이유·복구 절차는 [6장](#6-celery-워커--redis--미가동-보류-2026-07-22).

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
#   ⚠️ 실제 생성된 것은 shared-cpu-1x:256MB + 볼륨 3GB(--volume-size 10 아님). 2026-07-22 확인.

# 2-3) Redis (Upstash) — ⛔ 아직 실행하지 않음. 6장의 보류 결정을 먼저 읽을 것.
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

## 6. Celery 워커 / Redis — 미가동 (보류, 2026-07-22)

**결정: 아직 띄우지 않는다.** 첫 Celery 태스크를 실제로 작성할 때 Redis와 묶어 한 번에 올린다.

### 경위 (추측 금지 — 실제 확인된 사실)

- 2026-07-21 15:09 KST 배포로 worker 머신(`8747747f672698`)이 생성됐다.
- Redis가 없어서 Celery가 기본값 `redis://localhost:6379`로 붙으려다 **72회 재시도**하며 에러 로그만 쌓았다.
- 2026-07-21 15:43 KST **`SOURCE=user`로 destroy** — 크래시가 아니라 사람이 명령으로 지웠다.
  (머신 이벤트 로그 `destroying │ destroy │ user` 로 확인. flyd 자동 정리가 아님.)
- 현재 `fly scale show`에 **worker 그룹 자체가 없다**(web 1대만).

### 왜 지금 안 띄우나

1. ~~**할 일이 없다** — `@shared_task` 정의 0건~~ → **2026-08-04 부터는 있다.**
   `apps/clinic/tasks.py`(클리닉 감독 자료 수집)가 첫 태스크이고 beat 일정도
   `CELERY_BEAT_SCHEDULE` 에 20분 주기로 선언돼 있다.
   **그래도 안 띄운다** — 배포 보류(2026-08-04 사용자 지시). 그동안 그 일은
   `manage.py collect_clinic_supervision` 을 손으로 돌려 메운다. 배치가 멱등이라
   언제 몇 번을 돌려도 결과가 같아서 이 우회가 성립한다.
2. **auto-stop이 안 먹는다** — `fly.toml`의 `auto_stop_machines`는 `[http_service]`에만 걸린다.
   워커는 HTTP로 깨우는 대상이 아니라 **한번 띄우면 24시간 계속 돈다.**
3. 즉 지금 띄우면 20분에 한 번 2초 일하는 머신에 **월 ~$3.3**을 낸다.

### 비용 (fly.io/docs/about/pricing, 2026-07-22 확인 — Fly 무료 티어 없음)

| 리소스 | 사양 | 월 |
|---|---|---|
| `edujc-lms` web (상시, `min_machines_running=1`) | shared-cpu-1x 512MB | ~$3.32 |
| `edujc-pg` | shared-cpu-1x 256MB | ~$2.02 |
| pg 볼륨 | 3GB × $0.15 | $0.45 |
| **현재 합계** | | **~$5.8** |
| *(추가 시)* worker | shared-cpu-1x 512MB | +~$3.32 |
| *(추가 시)* Upstash Redis | pay-as-you-go, 최소요금 없음 | $0.20 / 100k 요청 |

Redis는 부담이 아니다 — 최소요금이 없어 요청이 없으면 사실상 $0. **비용은 워커 머신 쪽**이다.

### 해제 트리거

~~**첫 `@shared_task` 를 작성하는 시점.**~~ → **도달했다(2026-08-04)** — 클리닉 감독
자료 수집. 그런데 **띄우지 않기로 했다**: 손으로 돌리는 우회가 성립하고(배치가
멱등), 알림톡 발송이 곧 같은 워커를 필요로 하니 그때 한 번에 세우는 편이 낫다.

**다음 트리거 = 알림톡 발송 연동**(8-17 목록 도착 시). 그때 워커를 세우면 클리닉
수집도 같이 자동으로 돈다 — beat 일정이 이미 선언돼 있어 코드는 손댈 것이 없다.

> ⚠ **worker 만 켜지 말 것.** `beat` 를 같이 띄워야 주기 작업이 실제로 불린다.
> worker 만 있으면 태스크가 등록만 된 채 아무도 안 불러 조용히 안 돈다.

### 복구 절차 (트리거 도달 시, 3단계)

```bash
export PATH="$HOME/.fly/bin:$PATH"
cd /path/to/LMS

# 1) Redis 생성 (--plan 미지정 시 pay-as-you-go)
fly redis create --org EduJC --region nrt --name edujc-redis
#    → 출력된 redis://... URL 을 복사

# 2) secret 주입 (base.py 는 REDIS_URL 을 읽고 CELERY_BROKER_URL 기본값으로 재사용)
fly secrets set REDIS_URL="redis://..." -a edujc-lms

# 3) 워커 기동 — fly.toml 의 [processes] worker 정의는 그대로 살아 있으므로 count 만 올리면 된다
fly scale count worker=1 -a edujc-lms

# 검증: 아래에 Redis 재시도 에러가 없고 "celery@... ready." 가 떠야 성공
fly logs -a edujc-lms
fly scale show -a edujc-lms          # worker 그룹이 COUNT 1 로 보여야 함
```

> 되돌리기: `fly scale count worker=0 -a edujc-lms`

---

## 7. 로컬에서 DB 접속 (DBeaver 등) — 함정 2개

`edujc-pg`에는 **private IPv6(`fdaa:...`)밖에 없다.** 공인 IP가 없으므로 인터넷에서 직접 못 붙고
**반드시 `fly proxy`(WireGuard 터널)를 거쳐야 한다.**

```bash
make db-proxy        # 레포 루트에서. 이 터미널은 켜둔 채로 유지
#   └ 실제 실행: PATH="$HOME/.fly/bin:$PATH" fly proxy 15432:5432 -a edujc-pg
```

DBeaver 설정: Host `localhost` / Port **`15432`** / DB `lms` / User `lms` / SSL 끄기
비밀번호: `fly ssh console -a edujc-lms -C "printenv DATABASE_URL"` 로 확인

**함정 1 — 프록시는 조용히 죽는다.** 포그라운드 프로세스라 터미널을 닫거나 맥이 절전에 들어가면
사라진다. "어제까진 됐는데 안 된다"의 대부분이 이것이다. 먼저 확인:
```bash
lsof -nP -iTCP:15432 -sTCP:LISTEN     # 아무것도 안 나오면 프록시가 죽은 것
```

**함정 2 — 5432를 쓰지 말 것.** 로컬 `docker-compose.yml`의 postgres(OrbStack)가 5432를 점유한다.
- `fly proxy 5432:5432` → bind 실패
- DBeaver가 `localhost:5432`로 붙으면 fly DB가 아니라 **로컬 도커 DB(lms/lms/lms)에 조용히 연결된다**
  → "연결은 되는데 테이블이 비어 있다" 증상의 정체. 반드시 **15432** 같은 다른 포트를 쓴다.

---

## 나중에 org에서 빠질 때
1. org에 다른 **admin 1명** 남기기 (`fly orgs` 멤버 확인)
2. **결제 카드** 주체 지정(빠지는 사람 카드면 교체)
3. 이 머신/CI엔 **deploy 토큰**만 남기고 개인 세션 로그아웃(`fly auth logout`)
4. 리소스(앱·DB·스토리지)는 org 소유라 **그대로 유지됨**
