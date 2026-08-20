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
└─ redis edujc-redis  (Upstash Fixed 250MB)     · Celery 브로커 + 결과 백엔드
```

> **실제 가동 현황(2026-08-19 기준)**: `edujc-lms` web · worker · beat + `edujc-pg` primary.
> Celery 는 **2026-08-12 부터 돌고 있다** — 경위와 운영 규칙은 [6장](#6-celery-워커--beat--redis).

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
#   ✅ 이게 전부다. 별칭을 손으로 set 할 필요 없다 — base.py 가 Tigris 가 넣어 주는
#   이름(BUCKET_NAME · AWS_ENDPOINT_URL_S3 · AWS_REGION)을 그대로 읽는다.
#
#   ⚠️ 2026-08-12 경위: 예전에는 여기 "별칭을 손으로 set 하라"는 단계가 있었고
#   **그 단계가 빠져 있었다.** 버킷은 만들어져 있는데 Django 는 못 읽어서 앱이
#   아무 소리 없이 컨테이너 파일시스템에 쓰고 있었다(재배포마다 사라지는 자리).
#   손 절차는 잊힌다 — 그래서 코드가 두 이름을 다 읽도록 바꿨다(config/tests.py 가 고정).

# 2-5) 앱 시크릿
fly secrets set \
  DJANGO_SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_urlsafe(64))')" \
  DJANGO_DEBUG="False" \
  ALLOWED_HOSTS="edujc-lms.fly.dev" \
  CSRF_TRUSTED_ORIGINS="https://edujc-lms.fly.dev" \
  CORS_ALLOWED_ORIGINS="https://<프론트도메인>" \
  -a edujc-lms
#   (SENTRY_DSN 은 8장 — 가입부터 수집 검증까지 절차가 거기 있다)

# 2-6) 복습영상(Mux) — **없으면 영상이 통째로 안 나온다.**
#   apps/videos/mux.py 는 키가 없으면 예외를 던지지 않고 서명을 건너뛴다(로컬이
#   키 없이 돌아야 하므로). 그래서 시크릿을 빠뜨리면 토큰이 빈 채로 내려가고,
#   signed 정책 자산은 Mux 가 전부 403 을 내는데 **서버 로그에는 아무것도 안 남는다** —
#   화면에서 "권한 없음" 과 구분되지 않는다. 넣었는지 반드시 확인할 것.
fly secrets set \
  MUX_SIGNING_KEY_ID="..." \
  MUX_SIGNING_PRIVATE_KEY="<base64 개인키>" \
  MUX_PLAYBACK_RESTRICTION_ID="..." \
  -a edujc-lms
#   MUX_TOKEN_ID/SECRET 은 업로드 커맨드 전용이라 웹 프로세스에는 필요 없다.
#   MUX_DEMO_PLAYBACK_ID 는 **운영에서 비워 둔다**(시드 대체용 개발 편의).
#   MUX_PLAYBACK_RESTRICTION_ID 를 빠뜨리면 서명 URL 을 복사해 curl 로 스트림을
#   받아갈 수 있다 — 규칙은 `manage.py mux_restriction --domain <운영도메인>` 으로 만든다.

# 2-7) 쿠키 도메인 — 프런트와 API 가 다른 서브도메인이면 **필수**.
#   기본값(None)이면 쿠키가 API 도메인 전용으로 발급돼 프런트에서 로그인이 유지되지 않는다.
fly secrets set \
  SESSION_COOKIE_DOMAIN=".hjcedu.com" \
  CSRF_COOKIE_DOMAIN=".hjcedu.com" \
  -a edujc-lms

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

## 6. Celery 워커 / beat / Redis

**돈다.** 2026-08-12 에 세웠고(`599ca82`), 그때 supercronic 을 걷어냈다.

> 이 장은 오래 **"의도적으로 미가동"** 이라고 적혀 있었다. 그 문장이 2026-08-19
> 까지 남아 있어서, 이 문서만 읽은 사람은 "워커가 없으니 OMR 판독을 어디에
> 올릴지부터 정해야 한다"는 반대 결론에 도달한다. 실제로 그렇게 됐다.

### 지금 뜨는 것

| 프로세스 | 명령 | 크기 | 대수 |
|---|---|---|---|
| `web` | gunicorn (sync 3) | 512MB | 최소 1 (auto-start) |
| `worker` | `celery -A config worker` | 512MB | 1 |
| `beat` | `celery -A config beat` | 256MB | **정확히 1** |

**beat 는 2026-08-19 에 워커에서 분리했다.** 그전에는 `-B` 로 워커 안에 있었고,
머신 하나를 아끼는 대신 두 가지를 잃고 있었다:

- **워커를 2대로 못 늘린다** — 두 머신이 같은 시각에 같은 작업을 발행한다
- **워커가 죽으면 스케줄러도 같이 죽는다** — OMR 배치가 워커에 올라온 뒤로
  워커는 무거운 일을 하는 프로세스가 됐다. beat 는 DB 조회 한 번씩 하는 가벼운
  프로세스라 같이 죽을 이유가 없다

> ⚠ **`beat` 는 절대 2대로 올리지 말 것.** 스케줄이 중복 발행된다.
> 워커는 얼마든지 늘려도 된다(`fly scale count worker=N`).

### 워커 안전장치 (`config/settings/base.py`)

명령줄이 아니라 **설정에** 있다 — 두 군데 적으면 한쪽만 고치는 날이 온다.

| | 값 | 왜 |
|---|---|---|
| `task_soft_time_limit` / `task_time_limit` | 10분 / 12분 | OMR 실측이 386장 배치에 CPU 11초다. 분 단위면 진행이 아니라 멎은 것 |
| `worker_max_memory_per_child` | 250MB | 실측: Django 97MB → OMR 임포트 117MB → 실물 65장 읽고 **252MB**. 배치가 끝나면 자식을 갈아 돌려준다 |
| `worker_concurrency` | **1** | 자식 둘이면 505MB + 부모라 **512MB 머신이 OOM 으로 죽는다.** 늘릴 이유도 없다 — 1 vCPU 에 CPU 작업이라 처리량이 안 는다 |
| `worker_prefetch_multiplier` | 1 | 기본 4 는 한 자식이 넷을 쥔 채 나머지가 논다 |

### 비용 (2026-08-19)

| 리소스 | 사양 | 월 |
|---|---|---|
| web (상시) | shared-cpu-1x 512MB | ~$3.32 |
| worker | shared-cpu-1x 512MB | ~$3.32 |
| beat | shared-cpu-1x 256MB | ~$1.94 |
| `edujc-pg` + 볼륨 3GB | shared-cpu-1x 256MB | ~$2.47 |
| Upstash Redis Fixed 250MB | 정액 | $10 |

**종량제 Redis 를 쓰지 않는다** — Upstash 문서가 "Celery 는 큐가 비어도 계속
폴링해서 종량제에서 비용이 커진다"고 명시한다(2026-08-12 에 종량제로 만들었다가
이 줄을 읽고 정액으로 다시 만들었다).

### 확인

```bash
export PATH="$HOME/.fly/bin:$PATH"
fly scale show -a edujc-lms     # web / worker / beat 세 그룹
fly logs -a edujc-lms           # "celery@... ready." · beat "Scheduler: Sending due task"
```

되돌리기: `fly scale count worker=0 beat=0 -a edujc-lms`.
Redis 재시도 에러가 보이면 `REDIS_URL` 시크릿이 빠진 것이다.

### 판독이 느려지면 — 머신을 키우지 말고 대수를 늘린다

`fly scale count worker=2`. 자식을 늘리는(concurrency) 쪽은 1 vCPU 라 처리량이
안 늘고 메모리만 먹는다. **beat 를 분리해 뒀으므로 워커 대수는 이제 자유다.**

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

## 8. Sentry — 에러 추적 ✅ 가동 중 (2026-08-04)

> **이미 붙어 있다.** 조직 EDUJC · US 리전 · Developer(무료) · 프로젝트 `edujc-lms`.
> `SENTRY_DSN` 은 `fly secrets` 에 들어 있고, 실제 500 한 건으로 수집을 확인했다
> (이슈 `EDUJC-LMS-1` — `RuntimeError: Sentry 수집 확인용 예외`). 확인 후
> `SENTRY_DEBUG_TOKEN` 은 회수했고 `/sentry-debug` 는 다시 404 다.
> 아래는 **다시 세팅할 일이 생겼을 때**(DSN 교체·재발급·다른 앱에 붙일 때) 그대로 따라갈 절차다.

**왜 붙였나**: 2026-07-28 qbank 500 을 사후 추적하지 못했다. 오래 "`fly logs` 가 30분치만
남는다" 고 적어 뒀는데 **틀렸다**(2026-08-05 확인) — Fly 는 약 7일 보관하고, `fly logs
--no-tail` 이 마지막 **100줄**만 보여 준 것이다(실측). 막힌 것은 보관 기간이 아니라 도구였다.
그래도 Sentry 가 하는 일은 로그와 다르다(8-4 아래). "어제 왜 500 났지"를 사후에 추적할
수단이 없어 2026-07-28 qbank 500 조사에서 실제로 막혔다.

코드는 붙어 있다(`backend/config/observability.py`). **`SENTRY_DSN` 이 비면 아무것도
하지 않는다** — 로컬·테스트에서는 꺼진 채로 돈다. 계약은 `backend/config/tests.py` 가 지킨다.

### 8-1. DSN 발급 — 사람이 해야 한다

`fly ext sentry create` 는 **안 된다**(2026-07-28 실행 확인: *"Sentry is no longer
accepting new Fly.io integrations"* — Fly 경유 Team 1년 무료 딜은 소멸). sentry.io 에 직접 가입한다.

1. <https://sentry.io/signup/> 가입 (Developer 플랜 무료 — 1인·소규모 한도)
2. 조직 이름 정하고 → **Create Project** → 플랫폼 **Django** 선택
3. 온보딩 코드 스니펫의 `dsn="https://…@…ingest…sentry.io/…"` 에서 **따옴표 안 URL 만** 복사
   - 지나쳤으면: **Settings → Projects → \<프로젝트\> → Client Keys (DSN)**
4. 온보딩이 시키는 코드 붙여넣기·패키지 설치는 **하지 않는다.** 이미 다 돼 있다

> DSN 은 비밀번호가 아니라 공개 키에 가깝다(브라우저 SDK 에도 박히는 값). 그래도
> 알면 아무나 우리 프로젝트에 이벤트를 밀어넣어 한도를 태울 수 있으니 **저장소에 넣지 않는다.**

### 8-2. 주입

```bash
export PATH="$HOME/.fly/bin:$PATH"
fly secrets set SENTRY_DSN="<복사한 DSN>" -a edujc-lms     # 시크릿을 넣으면 앱이 재배포·재시작된다
```

DSN 형식이 잘못돼도 **부팅은 죽지 않는다.** 대신 꺼진 채로 뜨고 로그에 경고가 남는다 —
`fly logs -a edujc-lms` 에 `SENTRY_DSN 형식이 올바르지 않아` 가 보이면 값을 다시 넣는다.

### 8-3. 검증 — 실제 에러 1건을 일부러 낸다

`/sentry-debug` 는 **토큰이 맞을 때만** 500 을 낸다(토큰이 없으면 404). 상시 열린
500 엔드포인트를 두지 않으려는 것이고, 확인이 끝나면 토큰을 빼서 다시 닫는다.

```bash
# 1) 확인용 열쇠를 잠깐 건다
TOKEN="$(python3 -c 'import secrets;print(secrets.token_urlsafe(24))')"
fly secrets set SENTRY_DEBUG_TOKEN="$TOKEN" -a edujc-lms

# 2) 진짜 웹 요청으로 500 을 낸다 (gunicorn → Django → Sentry 전 경로를 탄다)
curl -i "https://edujc-lms.fly.dev/sentry-debug?token=$TOKEN"
#    → HTTP/2 500.   토큰이 없거나 틀리면 404 다.

# 3) Sentry → Issues 에 몇 초 안에 뜬다:
#    RuntimeError: Sentry 수집 확인용 예외      (culprit: config.urls in sentry_debug)
#    안 뜨면 → fly logs -a edujc-lms 로 경고 확인 → DSN 재확인

# 4) 확인 끝나면 열쇠를 뺀다 — 경로가 다시 404 가 된다
fly secrets unset SENTRY_DEBUG_TOKEN -a edujc-lms
curl -i "https://edujc-lms.fly.dev/sentry-debug?token=$TOKEN"    # → 404 여야 한다
```

이슈가 떴으면 **그 이슈 화면에서 아래 3개를 눈으로 확인한다**(8-4 가 지켜졌는지):
`request` 에 본문(`data`)이 없을 것 · 쿼리 값이 `[Filtered]` 일 것 · 스택 프레임에
`Local variables` 가 없을 것.

### 8-4. 무엇을 보내고 무엇을 막나

보내는 것은 **예외와 그 예외가 난 위치**뿐이다. 학생 이름·전화번호가 실릴 수 있는 자리는 전부 막았다.

| 자리 | 어떻게 막나 |
|---|---|
| 요청 본문 | `max_request_body_size="never"` + `before_send` 에서 제거 |
| 쿼리스트링 | `before_send` 에서 값 마스킹(`q=[Filtered]`) — 키는 남긴다 |
| 스택 지역변수 | `include_local_variables=False` |
| 쿠키·세션·IP·로그인 계정 | `send_default_pii=False` |

`send_default_pii=False` **하나로는 위의 앞 셋이 막히지 않는다** — 각각 다른 옵션 소관이고,
SDK 기본 스크러버는 `password`·`token` 류만 잡는다(이름·전화번호는 그대로 통과). 이름과
휴대폰 번호는 미성년 학생의 개인정보이고 Sentry 는 국외 서비스라, 기본값을 **안 보내는 쪽**으로 뒀다.

> 되짚어야 할 때(예: 요청 본문이 꼭 필요한 버그) 는 `config/observability.py` 한 곳만 고치면 되고,
> 고치는 순간 `config/tests.py` 가 빨개진다 — 실수로 열리지는 않는다는 뜻이다.

**추정이 아니라 실측이다**(2026-08-04). 가짜 수집 서버로 DSN 을 돌리고 prod 설정 + 진짜 WSGI
(운영과 같은 `config.wsgi.application`)로 500 을 낸 뒤, 나가는 엔벨로프를 그대로 열어 봤다.
학생 이름·휴대폰·비밀번호를 쿼리와 본문에 둘 다 실어 보냈고 결과는 —

```
남은 것:  RuntimeError | Sentry 수집 확인용 예외
          url=…/sentry-debug · method=POST · transaction=/sentry-debug
          마지막 프레임 config/urls.py:36 sentry_debug
막힌 것:  query_string='token=[Filtered]&q=[Filtered]&page=[Filtered]'
          data=None · user=None · cookies=None · 지역변수 실린 프레임 없음
          headers = Host/User-Agent/Content-Type 등 무해한 것만
페이로드 원문에서 이름·전화번호·비밀번호 검색 → 0건
```

즉 **어느 엔드포인트에서 몇 번째 줄이 터졌는지는 남고, 누구의 무엇이었는지는 안 남는다.**

성능 추적은 `traces_sample_rate=0.1`(요청 10건 중 1건)로 켜져 있다. 에러 한도와 별개 항목이라
한도를 태우면 이 값을 0 으로 내린다.

### 8-5. 한도·범위에 관해 같이 실측한 것 (2026-08-04)

- **500 한 건 = 이벤트 1건.** Django 가 500 마다 `django.request` 로 ERROR 로그도 남기지만
  중복 이벤트가 되지 않는다. 무료 한도(에러 5천건/월)가 반으로 줄지 않는다는 뜻이다
- **Celery 도 이미 잡힌다.** 활성 통합에 `celery`·`redis`·`boto3` 가 자동으로 들어간다
  (`prod.py` 는 Django 만 명시하지만 SDK 가 설치된 패키지를 감지해 붙인다). 워커를 띄우는
  날(6장) 알림 발송 태스크 실패는 별도 작업 없이 수집된다
- **`release` 는 빌드가 넣는다**(2026-08-04 처리). 이미지에 `.git` 이 없어 SDK 가 스스로
  추론할 수단이 없다 → `Dockerfile` 의 `ARG GIT_SHA` → `ENV SENTRY_RELEASE`.
  넘기는 쪽은 두 군데뿐이다: CI(`--build-arg GIT_SHA=${{ github.sha }}`)와 `make deploy`.
  **`fly deploy` 를 손으로 직접 치면 태그가 조용히 사라진다** — 그래서 `make deploy` 가 있다.
  로컬 도커 빌드로 실측: 인자를 넘기면 `options['release']` 가 그 값, 안 넘기면 `None`

---

## 나중에 org에서 빠질 때
1. org에 다른 **admin 1명** 남기기 (`fly orgs` 멤버 확인)
2. **결제 카드** 주체 지정(빠지는 사람 카드면 교체)
3. 이 머신/CI엔 **deploy 토큰**만 남기고 개인 세션 로그아웃(`fly auth logout`)
4. 리소스(앱·DB·스토리지)는 org 소유라 **그대로 유지됨**
