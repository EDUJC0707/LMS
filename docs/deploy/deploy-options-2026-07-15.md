# 학원 LMS 백엔드 배포 옵션 비교 (2026-07-15)

> 대상: **솔로 + 초보 개발자**가 운영/인수인계할 한국 학원 LMS 백엔드
> 스택(예상): **Python(Django 유력) + PostgreSQL + Celery(백그라운드) + Redis**, 프론트는 React SPA(정적 별도 호스팅)
> 요구: **한국 지연시간(서울 이상적·도쿄 수용) · 수업일 트래픽 스파이크 대응(오토스케일, 단 콜드스타트 리스크) · 관리형 선호 · S3 호환 오브젝트 스토리지 · 2026-08 오픈 · 비용 억대 아님**

**조사 방법:** 8개 후보를 서비스별로 병렬 웹리서치(공식 docs/pricing 우선, 각 주장에 출처 URL). 가격·리전·기능은 2026년 7월 기준으로 재확인. 검증 못한 값은 `확인 필요`로 명시.

**표기:** `[공식]`=공식 문서/가격페이지 확인 · `[3P]`=서드파티 가격추적(공식 페이지가 JS렌더링 등으로 기계판독 불가) · `[추정]`=공식 수치 기반 계산 · **확인 필요**=현행 1차 출처로 미검증.

---

## 0. 한 줄 결론 (TL;DR)

- **탈락 2종:** **AWS App Runner**는 2026-04-30부로 **신규 가입 불가**(생성 자체 불가) → 이 프로젝트에서 제외. **Heroku**는 2026-02 **유지보수(sustaining) 모드** 전환 + **아시아 리전 없음(신규는 사실상 불가)** + 무료티어 폐지 → 신규 프로젝트에 비권장.
- **한국 지연 최적:** **Google Cloud Run** (유일하게 **서울 리전** 보유). 단 하이퍼스케일러라 초보 학습곡선·부가 관리(IAM/VPC/Cloud SQL) 존재.
- **지연 + 관리형 + 스택 통합의 균형 최적(초보 현실적 1순위):** **Fly.io** (**도쿄 리전**에 관리형 Postgres(MPG)+Upstash Redis+Tigris S3스토리지를 한 곳에 집적, scale-to-zero + 상시 웜 유지 용이).
- **가장 손 안 가는 대시보드형 관리형:** **Render** 또는 **DigitalOcean App Platform** — 단 둘 다 **아시아=싱가포르뿐**(도쿄보다 지연 큼).

---

## 1. 리전 / 한국 지연시간 (⭐ 최우선 축)

| 서비스 | 서울(ICN) | 도쿄(NRT) | 그 외 최근접 | 한국 체감 |
|---|---|---|---|---|
| **Google Cloud Run** | ✅ `asia-northeast3` (Tier 2 요금) | ✅ `asia-northeast1` | — | **최적** (서울 인리전) |
| **Fly.io** | ❌ | ✅ `nrt` | sin(싱가포르) | **양호** (도쿄) |
| **Koyeb** | ❌ | ✅ `TYO`(compute만) | sin | 양호(단, 관리형 DB는 도쿄 없음 → 아래 주의) |
| **AWS App Runner** | ❌ | ✅ `ap-northeast-1` | sin, 뭄바이 | (신규가입 불가라 무의미) |
| **Render** | ❌ | ❌ | **싱가포르** | 보통 (~싱가포르) |
| **Railway** | ❌ | ❌ | **싱가포르** `asia-southeast1` | 보통 (~싱가포르) |
| **DigitalOcean App Platform** | ❌ | ❌ | **싱가포르 SGP1** (차선 방갈로르) | 보통 (~싱가포르) |
| **Heroku** | ❌ | ❌(엔터프라이즈 Private Spaces만) | **US/EU만** | **나쁨** (미국/유럽) |

**대략 왕복지연(단일 출처 WonderNetwork, `[3P]` — 실측/CDN 구성에 따라 변동):** 서울↔도쿄 **~31ms**, 서울↔싱가포르 **~73ms**, 서울↔미국동부 ~150ms+.
→ **도쿄 vs 싱가포르 차이 약 +40ms.** 서울 인리전(Cloud Run)이 이상적, 도쿄(Fly/Koyeb/Cloud Run)가 차선, 싱가포르(Render/Railway/DO)는 수용 가능하나 한 단계 아래, Heroku(US/EU)는 부적합.

> **데이터 상주(residency)**가 법적으로 서울이어야 한다면 후보 중 **Cloud Run만** 충족(그 외엔 AWS 서울/Naver Cloud 등 별도 IaaS 검토 필요).

---

## 2. 종합 비교표 (이 프로젝트 관점 핵심 축)

| 서비스 | 초보 온보딩 | 오토스케일 / scale-to-zero·콜드스타트 | 관리형 PostgreSQL | 워커(Celery)·크론·Redis | S3호환 스토리지 | 월비용 추정(소규모 상시) `[추정]` | 상태·리스크 |
|---|---|---|---|---|---|---|---|
| **Render** | ★★★★★ 대시보드, Django 공식가이드 | 목표치 기반 **수평 오토스케일(Pro 워크스페이스 $25 필요)**. 유료=상시가동(콜드스타트 없음), 무료만 15분후 슬립 | ✅ **진짜 관리형**(PITR·HA·읽기복제) | 워커 서비스 O, **Celery 공식가이드**, Cron 서비스, **Key Value(Redis호환) 관리형** | ⚠️ 네이티브는 **alpha**(미사용 권장) → 외부 R2 권장 | **~$43** (오토스케일 시 +$25 → ~$68) | 안정적. 2026-08-01 워크스페이스 이관+대역폭 100→5GB 축소 주의 |
| **Railway** | ★★★★★ 대시보드/CLI, Django 템플릿 | **수동 레플리카**(진짜 오토스케일 아님)+수직 자동버스트. Serverless(opt-in) scale-to-zero, **첫 요청 502 콜드스타트** | ⚠️ **비관리형**(백업/PITR 기능은 있으나 운영책임) | 워커 O, 네이티브 Cron(최소 5분), Redis 제공하나 **비관리형** | ✅ **Railway Buckets**(네이티브, 퍼블릭버킷 미지원) | **~$20~40** (사용량 기반) | 2025~26 **대형 장애 다발**(GCP 계정정지 8h 등). 비용 상한 없음 |
| **Fly.io** | ★★★☆☆ **CLI 중심**(fly launch가 Django 자동감지) | scale-to-zero 기본, **`min_machines_running≥1`로 웜 유지 쉬움**, wake 매우 빠름(ms). 진짜 metric 오토스케일은 별도 fly-autoscaler | ✅ **Managed Postgres(MPG)**: HA·자동백업, **도쿄 지원** | 워커=별도 머신, cron=supercronic, **Upstash Redis 네이티브** | ✅ **Tigris**(네이티브 S3, **egress 무료**, $0.02/GB) | **~$48~65** (MPG Basic $38이 최대) | 신규 무료티어 없음. suspend 비내구성 등 초보 함정 |
| **Koyeb** | ★★★★☆ git push+빌드팩 자동 | scale-to-zero, **Light Sleep ~200ms / Deep Sleep 1~5s** 콜드스타트, 요청/CPU 오토스케일 | △ managed지만 **도쿄 없음**(FRA/WAS/**SIN**만) → 앱-DB 리전 분리 | 워커 서비스 O, **Celery 가이드**, **관리형 Redis 없음**(자가운영/외부) | ❌ 네이티브 없음(외부 R2/S3/MinIO) | **~$45~60** | Postgres 도쿄 부재+Redis/스토리지 외부조립이 이 스택 감점 |
| **Google Cloud Run** | ★★★☆☆ 하이퍼스케일러(IAM/VPC 학습), 단 `--source` 원커맨드 배포·Django Codelab | **scale-to-zero + `min-instances≥1` 웜 유지**(콜드스타트 방지). 자동 수평확장, concurrency로 스파이크 흡수 | Cloud SQL 페어링. `db-f1-micro` ~$8~10(공유코어 SLA無), 전용소형 $25~50대 | **Worker Pools(2026-04 GA)** 또는 always-on 서비스로 Celery, Cloud Scheduler, **Memorystore Redis ~$36/1GB(비쌈)** | ✅ **GCS**(S3 상호운용) | **~$65~80** (Redis+상시). scale-to-zero+셀프Redis 시 $20~30대 | **서울 리전** 유일 장점. 부가 관리 복잡도 |
| **AWS App Runner** | — | scale-to-zero **불가**(min 1). | RDS 페어링(VPC 커넥터) | ⚠️ **Celery 네이티브 불가**(별도 ECS/Fargate 필요), ElastiCache Redis | ✅ S3 | (신규가입 불가) | 🚫 **2026-04-30 신규 차단 + 서울 없음 → 제외**. 대체=ECS Express Mode |
| **DigitalOcean App Platform** | ★★★★★ 대시보드, 예측가능 요금 | 수평 오토스케일. **Request 기반 오토스케일 Basic부터 가능(저예산 장점)**. Scale-to-Zero 있으나 콜드스타트 | ✅ 관리형 **$15~**(HA $30~), 자동백업·PITR. (App 내 Dev DB $7, 운영 비권장) | Worker 컴포넌트(celery-worker/beat), **Scheduled Jobs(최소 15분)**, **관리형 Valkey(Redis호환) $15~** | ✅ **Spaces**(네이티브 S3, **$5/250GiB+1TiB전송+CDN**, SGP1 가능) | **~$59** (스토리지 포함) / 최소 ~$37 | 안정적. 앱당 단일리전, Redis 최저 $15 |
| **Heroku** | ★★★★★ `git push heroku` | 네이티브 오토스케일=**Performance $250/dyno~만**. Eco는 30분후 슬립, Basic$7 상시 | 관리형 우수. Essential-0 **$5**/-1 $9/-2 $20(HA無), Standard-0 $50 | 워커 dyno($7), Scheduler(무료 크론), **KV Store Mini $3(~25MB)** | ❌ 네이티브 없음 → **외부 S3 필수** | **~$22 + 외부 S3** | 🚨 **유지보수 모드(2026-02) + 아시아 리전 없음 + 강한 락인 → 신규 비권장** |

---

## 3. 서비스별 짧은 코멘트 (10축 요약)

### Render — "가장 무난한 대시보드형 관리형, 단 싱가포르"
초보 온보딩·문서·안정성이 최상급이고 Postgres/Redis(Key Value)가 **진짜 관리형**(PITR·HA)이라 솔로 초보에게 운영 부담이 가장 낮다. **Celery 배포 공식 가이드**까지 있다. 약점은 (1) **아시아=싱가포르뿐**(도쿄 대비 +40ms), (2) 목표치 기반 **오토스케일이 Pro 워크스페이스($25 정액)** 게이팅, (3) 네이티브 오브젝트 스토리지가 alpha라 **파일은 외부(Cloudflare R2) 권장**. 2026-08-01 워크스페이스 이관에서 **포함 대역폭 100GB→5GB 축소**가 런칭 시점과 겹치니 주의. 예상 ~$43/월(오토스케일 시 ~$68).

### Railway — "가장 저렴·유연하나 비관리형 DB·안정성 리스크"
사용량 기반이라 소규모면 **~$20~40**로 가장 쌀 수 있고, **Railway Buckets**(네이티브 S3, Tigris)로 파일 저장을 외부 없이 해결 가능하며 PR 프리뷰 환경이 훌륭하다. 그러나 (1) **DB가 비관리형**(업그레이드/백업 운영책임 → 초보에게 부담), (2) **수동 레플리카**라 수업일 자동 급증 대응이 약하고, (3) **2025~2026 대형 장애가 잦았다**(GCP가 계정을 무단정지해 플랫폼 전체 ~8시간 다운 등). 수업일 안정성 우선이면 감점.

### Fly.io — "도쿄에 풀스택 집적, 초보엔 CLI가 관문 (균형 최적)"
**도쿄(nrt)에 관리형 Postgres(MPG, HA+백업) + Upstash Redis(네이티브) + Tigris(S3, egress 무료)** 를 모두 둘 수 있어, 이 프로젝트의 스택(PG/Celery/Redis/파일업로드)을 **한 리전·한 청구서**로 관리형 구성 가능. scale-to-zero가 기본이며 `min_machines_running≥1`로 **수업 중 웜 유지가 간단**. 약점은 (1) **CLI 중심**이라 대시보드형보다 초보 진입이 다소 가파름, (2) 신규 무료티어 없음, (3) MPG Basic이 ~$38로 비용의 대부분. 예상 ~$48~65/월.

### Koyeb — "첫 배포는 쉬우나 도쿄 관리형 DB·Redis·스토리지 부재"
git push + 빌드팩 자동감지로 첫 배포 UX는 좋고 **Light Sleep 콜드스타트 ~200ms**로 빠르다. 하지만 이 프로젝트엔 결정적 약점: **관리형 Postgres가 도쿄에 없음**(FRA/WAS/싱가포르만) → 앱(도쿄)-DB(싱가포르) 리전 분리 또는 전부 싱가포르, 그리고 **관리형 Redis·오브젝트 스토리지가 네이티브로 없음**(외부 조립 필요). 관리형·통합 편의를 원하는 솔로 초보에겐 손이 더 간다.

### Google Cloud Run — "한국 지연 최적(서울), 대신 하이퍼스케일러 복잡도"
**유일하게 서울(asia-northeast3) 리전** → 한국 지연 최적. **scale-to-zero + `min-instances≥1` 웜 유지**로 "평소 저비용 / 수업일 콜드스타트 방지"를 동시에 충족하고, **Worker Pools(2026-04 GA)** 로 Celery, Buildpacks로 **Dockerfile 없이 Django** 배포 가능. GCS는 S3 상호운용. 약점은 (1) **IAM/서비스계정/VPC(Direct VPC egress)·Cloud SQL 배선** 등 부가 관리(초보 학습곡선), (2) **Memorystore Redis가 소규모엔 ~$36로 비쌈**(셀프호스팅/서드파티로 절감 가능), (3) Cloud SQL 최저 전용티어도 고정비 존재. 예상 ~$65~80/월(구성에 따라 $20~30대까지 절감).

### AWS App Runner — 🚫 제외
**2026-04-30부로 신규 고객에게 닫힘**(공식 문서가 현재시제로 "no longer open to new customers"). 신규 솔로 개발자가 **생성 자체 불가**. 추가로 **서울 리전 없음**, **Celery 네이티브 불가**(별도 ECS/Fargate 필요), 사실상 유지보수 수순. AWS 권장 대체는 App Runner가 아닌 **ECS Express Mode**(Fargate+ALB, 학습곡선 더 높음). → 이 프로젝트 후보에서 제외.

### DigitalOcean App Platform — "예측가능·저예산 오토스케일·네이티브 스토리지, 단 싱가포르"
대시보드가 쉽고 요금이 컴포넌트 단위로 예측 가능. **Request 기반 오토스케일이 Basic 플랜부터** 되어 저예산에서도 수업일 급증 대응이 가능하고, **Spaces**(네이티브 S3, $5에 250GiB+1TiB전송+CDN)와 관리형 Postgres($15)/Valkey($15)를 **싱가포르(SGP1)에 전체 배치** 가능. 약점은 **아시아=싱가포르뿐**(도쿄보다 지연 큼)과 관리형 Redis 최저가 $15. 예상 ~$59/월(스토리지 포함). Render의 강력한 대안.

### Heroku — 🚨 신규 비권장
**2026-02 유지보수(sustaining) 모드 전환**(신규 기능 개발·신규 엔터프라이즈 판매 중단). 무료티어는 2022년 폐지되어 없고(최저 Basic $7 상시), **Common Runtime은 US/EU뿐**이라 한국 지연이 나쁘며 아시아는 엔터프라이즈 Private Spaces(신규 판매 중단)뿐. **네이티브 오브젝트 스토리지 없음**(외부 S3). 저예산 티어에선 **네이티브 오토스케일 불가**($250 dyno~). CI/CD(Review Apps)와 초보 편의성은 여전히 좋지만, 신규 프로젝트가 채택할 이유가 약하고 **락인이 강하다**.

---

## 4. 이 프로젝트 기준 추천

### 1순위(추천) — **Fly.io** (균형: 지연+관리형+스택통합)
초보에게 대시보드형(Render/DO)보다 CLI가 다소 가파른 점만 넘기면, **도쿄 리전에 관리형 Postgres·Redis·S3스토리지를 한 곳에 통합**해 이 프로젝트의 4대 요구(한국 지연·Celery/Redis·파일업로드·관리형)를 가장 균형 있게 충족한다. 수업 중엔 `min_machines_running≥1`로 웜 유지, 유휴 시간대엔 scale-to-zero로 절감이 가능하다.

### 공동 1순위(지연 최우선이면) — **Google Cloud Run**
"서울 인리전"이 반드시 필요하거나 향후 성장(스파이크·트래픽 증가)을 크게 본다면 Cloud Run이 지연·확장성 면에서 최상. 단 **GCP 기본기(IAM/VPC/Cloud SQL) 학습 의지**가 전제이며, Memorystore Redis 비용(~$36)만 유의(초기엔 셀프호스팅/서드파티 Redis로 시작 후 필요 시 전환 가능).

> 요약하면: **"초보 편의·통합 관리 우선 → Fly.io"**, **"한국 지연·확장성 우선 & GCP 학습 감수 → Cloud Run"**.

---

## 5. 우선순위가 다를 때의 대안

| 우선순위 | 추천 | 근거 |
|---|---|---|
| **가장 저렴** | **Railway**(~$20~40) 또는 Render 최소구성(~$30) | Railway는 사용량 기반 최저가지만 **비관리형 DB·안정성 리스크** 감수. 안정성까지 원하면 Render 저티어. |
| **가장 손 안 가는(관리형·대시보드)** | **Render** (차선 **DigitalOcean App Platform**) | 진짜 관리형 PG/Redis + 대시보드 + 안정성. 단 **싱가포르 지연**과 Render 오브젝트 스토리지 alpha(→R2). |
| **한국 지연 최적** | **Google Cloud Run**(서울) > **Fly.io**(도쿄) | 서울 인리전은 Cloud Run뿐. 도쿄로 충분하면 Fly가 관리 편함. |
| **scale-to-zero로 유휴비용 0** | **Google Cloud Run**(관대한 무료티어+빠른 콜드스타트) 또는 **Fly.io**(빠른 wake) | 단 **수업 중 콜드스타트 리스크** → 수업 시간대만 min-instance≥1로 웜 유지하는 하이브리드 권장. |
| **네이티브 S3 스토리지 통합** | **DigitalOcean(Spaces)** / **Fly(Tigris)** / **Railway(Buckets)** | 세 곳은 플랫폼 내 S3호환 제공. Render/Koyeb/Heroku는 외부(R2 권장). |

---

## 6. 주의사항 (걸릴 수 있는 지점)

- **콜드스타트 vs 유휴비용:** scale-to-zero는 유휴비용을 0으로 만들지만 **수업 중 첫 요청 지연/오류 리스크**. 권장: 수업 시간대에는 웜 인스턴스 유지 — Cloud Run `min-instances≥1`, Fly `min_machines_running≥1`, Render/DO는 유료=상시가동(scale-to-zero 끄기), Railway는 Serverless 끄기. Railway Serverless는 **첫 요청 502** 보고가 있으니 프로덕션 비권장.
- **리전:** 후보 중 **서울은 Cloud Run만**. 도쿄=Fly/Koyeb/Cloud Run, 싱가포르=Render/Railway/DO, US/EU=Heroku. **Koyeb는 앱은 도쿄여도 관리형 DB가 도쿄에 없어** 리전이 갈린다(지연·복잡도↑). 데이터 상주가 서울 강제면 Cloud Run 또는 별도 서울 IaaS(AWS 서울/Naver Cloud) 필요.
- **워커/Redis:** **App Runner는 Celery 네이티브 불가**(별도 Fargate). **Koyeb·Railway·Fly는 Redis가 비관리형이거나 외부(Upstash)** — 관리형 Redis가 플랫폼 내에 있는 곳은 Render(Key Value)/DO(Valkey)/Heroku(KV)/Cloud Run(Memorystore, 비쌈). **Railway·Fly의 Postgres는 관리 성격에 유의**(Railway 비관리형, Fly는 레거시 Postgres 아닌 **MPG**를 써야 관리형). 크론 최소간격 제약(Railway 5분, DO 15분)은 Celery beat(초/분 단위)에 부적합 → **beat는 상시 워커로** 실행.
- **스토리지:** **Render 네이티브 오브젝트 스토리지는 alpha**(프로덕션 의존 금지), **Heroku·Koyeb는 네이티브 없음**(외부 S3). 어느 플랫폼이든 **Cloudflare R2**가 유력(egress 무료 → 한국 사용자에 반복 서빙 시 비용 유리; AWS S3 서울 egress는 비쌈). 블록 디스크(Render Disk/Railway·Fly Volume)는 오브젝트 스토리지가 아니며 **부착 시 수평 스케일이 막힐 수 있음**.
- **플랫폼 리스크:** **App Runner 신규차단·Heroku 유지보수 모드**는 신규 채택 부적합 신호. **Railway는 2025~26 장애 이력**이 있어 수업일 안정성 민감하면 감점.
- **비용 급증:** Railway·Cloud Run은 **사용량 기반 → 상한/알림 설정** 필수. Render 오토스케일은 Pro 워크스페이스($25) 필요. 관리형 DB/Redis의 **고정 최저비용**(예: Cloud SQL 전용티어, Memorystore $36, DO/Heroku Redis $15/$3)이 소규모에선 총비용을 좌우.

---

## 7. 불확실/미확인 항목 (정직 표기)

- **리전별 정확 요금(도쿄/서울 마크업):** Fly 도쿄 compute 정확요율(확보치는 암스테르담 기준), Cloud Run **Tier 2(서울) 초당 정확요율**(공식 페이지 fetch가 잘려 서드파티 스니펫 기준 — Tier 1은 교차확인), RDS/ElastiCache/Fargate 도쿄 요율(상당수 us-east-1 값) → 모두 **확인 필요**.
- **Render 인스턴스/DB/KV 세부 가격:** 공식 가격페이지가 JS렌더링이라 기계판독 불가 → **서드파티 추적치**. 최저 Postgres $6 vs $7 상충 **확인 필요**.
- **Cloud Run 무료티어의 서울(Tier 2) 적용 여부** 자료 엇갈림 → **확인 필요**.
- **Koyeb** Postgres Small 정확 월요금($29.76 vs serverless 시간과금 표기 상충)·**백업 보존정책 미명시**, Pro($29) 플랜의 프로덕션 필수 여부 → **확인 필요**.
- **월 비용 총액은 모두 `[추정]`** — 실제 사용량(RAM/CPU/트래픽/스토리지)에 크게 의존.
- **지연 ms**(서울↔도쿄/싱가포르)는 **단일 출처(WonderNetwork)** — 실측 권장.
- **Railway** Hobby app-sleeping 버그(끈 상태에서도 잠든다는 커뮤니티 제보), Trial 리전선택 가능 여부 → **확인 필요**.
- **Heroku** KV Store Mini "25MB/20커넥션" 세부 스펙은 2차 출처 → 공식 애드온 페이지 재확인 권장.

---

## 8. 출처 (Sources)

### Render
- https://render.com/docs/regions · https://render.com/docs/scaling · https://render.com/docs/platform-features-by-plan
- https://render.com/docs/free · https://render.com/docs/deploy-django · https://render.com/docs/deploy-celery · https://render.com/docs/background-workers · https://render.com/docs/cronjobs
- https://render.com/docs/postgresql-backups · https://render.com/docs/postgresql-high-availability · https://render.com/docs/key-value · https://render.com/docs/disks · https://render.com/docs/deploy-minio · https://feedback.render.com/features/p/cloud-object-storage
- https://render.com/docs/preview-environments · https://render.com/docs/deploys · https://render.com/docs/github · https://render.com/docs/blueprint-spec
- https://render.com/changelog/updated-plans-for-render-workspaces · https://render.com/docs/new-workspace-plans · https://render.com/pricing (JS렌더링)

### Railway
- https://docs.railway.com/reference/regions · https://docs.railway.com/reference/pricing/plans · https://docs.railway.com/pricing/free-trial · https://blog.railway.com/p/pricing-and-plans-migration-guide-2023
- https://docs.railway.com/deployments/scaling · https://docs.railway.com/reference/app-sleeping · https://docs.railway.com/quick-start · https://docs.railway.com/guides/django
- https://docs.railway.com/databases · https://docs.railway.com/databases/postgresql · https://docs.railway.com/volumes/backups · https://docs.railway.com/volumes/point-in-time-recovery
- https://docs.railway.com/storage-buckets · https://docs.railway.com/cron-jobs · https://docs.railway.com/guides/cron-workers-queues · https://docs.railway.com/guides/preview-deployments-with-pr-environments · https://docs.railway.com/deployments/github-autodeploys
- https://blog.railway.com/p/incident-report-may-19-2026-gcp-account-outage · https://status.railway.com/historical · https://www.theregister.com/off-prem/2026/05/20/google-cloud-suspended-major-customer-railwaycom-without-cause-causing-outage/

### Fly.io
- https://fly.io/docs/reference/regions/ · https://fly.io/docs/about/pricing/ · https://fly.io/docs/mpg/ · https://fly.io/mpg/
- https://fly.io/docs/launch/autostop-autostart/ · https://fly.io/docs/reference/suspend-resume/ · https://community.fly.io/t/we-are-going-to-start-charging-for-mpg-inter-region-private-network-usage-from-febuary-2026/26561
- https://fly.io/docs/tigris/ · https://www.tigrisdata.com/pricing/ · https://fly.io/docs/upstash/redis/
- https://fly.io/docs/django/getting-started/ · https://fly.io/docs/launch/continuous-deployment-with-github-actions/ · https://fly.io/docs/blueprints/review-apps-guide/

### Koyeb
- https://www.koyeb.com/docs/reference/regions · https://www.koyeb.com/blog/paris-and-tokyo-regions-are-now-generally-available · https://www.koyeb.com/docs/reference/instances
- https://www.koyeb.com/docs/databases · https://www.koyeb.com/blog/koyeb-serverless-postgres-pricing · https://www.koyeb.com/pricing · https://www.koyeb.com/docs/faqs/pricing
- https://www.koyeb.com/docs/run-and-scale/scale-to-zero · https://www.koyeb.com/blog/scale-to-zero-wake-vms-in-200-ms-with-light-sleep-ebpf-and-snapshots
- https://www.koyeb.com/tutorials/deploy-a-python-celery-worker · https://www.koyeb.com/tutorials/deploy-redis-as-an-in-memory-database-for-koyeb-applications · https://www.koyeb.com/docs/build-and-deploy/deploy-with-git

### Google Cloud Run
- https://cloud.google.com/run/pricing · https://docs.cloud.google.com/run/docs/locations · https://docs.cloud.google.com/run/docs/configuring/min-instances · https://docs.cloud.google.com/run/docs/configuring/billing-settings
- https://docs.cloud.google.com/run/docs/deploying-source-code · https://cloud.google.com/python/django/run · https://cloud.google.com/blog/products/serverless/cloud-run-worker-pools-at-estee-lauder-companies · https://github.com/celery/celery/discussions/9942
- https://cloud.google.com/sql/pricing · https://cloud.google.com/memorystore/docs/redis/pricing · https://docs.cloud.google.com/storage/docs/interoperability · https://cloud.google.com/blog/products/serverless/announcing-direct-vpc-egress-for-cloud-run
- 교차확인(3P): https://cloudchipr.com/blog/cloud-run-pricing · https://www.prosperops.com/blog/google-cloud-run-pricing-and-cost-optimization/ · https://upstash.com/blog/redis-pricing-comparison-every-major-provider-in-2026-with-numbers

### AWS App Runner
- https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html · https://docs.aws.amazon.com/apprunner/latest/relnotes/relnotes.html · https://docs.aws.amazon.com/general/latest/gr/apprunner.html
- https://aws.amazon.com/apprunner/pricing/ · https://docs.aws.amazon.com/apprunner/latest/dg/manage-autoscaling.html · https://github.com/aws/apprunner-roadmap/issues/9 · https://docs.aws.amazon.com/apprunner/latest/dg/network-vpc.html
- https://aws.amazon.com/rds/postgresql/pricing/ · https://aws.amazon.com/elasticache/pricing/

### DigitalOcean App Platform
- https://docs.digitalocean.com/products/app-platform/details/pricing/ · https://docs.digitalocean.com/products/app-platform/details/availability/ · https://docs.digitalocean.com/platform/regional-availability/
- https://docs.digitalocean.com/products/app-platform/how-to/scale-app/ · https://www.digitalocean.com/blog/introducing-cpu-based-autoscaling-app-platform · https://docs.digitalocean.com/products/app-platform/reference/buildpacks/python/ · https://docs.digitalocean.com/products/app-platform/how-to/manage-jobs/
- https://www.digitalocean.com/pricing/managed-databases · https://docs.digitalocean.com/products/databases/postgresql/details/pricing/ · https://docs.digitalocean.com/products/spaces/details/pricing/ · https://docs.digitalocean.com/products/spaces/details/availability/ · https://docs.digitalocean.com/products/app-platform/how-to/deploy-from-github-actions/

### Heroku
- https://www.heroku.com/pricing/ · https://help.heroku.com/RSBRUH58/removal-of-heroku-free-product-plans-faq · https://help.heroku.com/1CDF2VHY/what-are-your-cheapest-heroku-postgres-and-heroku-data-for-redis-plans
- https://devcenter.heroku.com/articles/heroku-postgres-plans · https://elements.heroku.com/addons/heroku-postgresql · https://devcenter.heroku.com/articles/regions · https://devcenter.heroku.com/articles/autoscaling · https://devcenter.heroku.com/articles/scheduler
- https://www.heroku.com/flow/ · https://devcenter.heroku.com/articles/github-integration-review-apps · https://www.theregister.com/2026/02/09/heroku_freeze/ · https://siliconangle.com/2026/02/06/salesforce-stop-selling-enterprise-heroku-subscriptions-scale-back-upgrades/

### 오브젝트 스토리지 / 지연 (공통)
- https://developers.cloudflare.com/r2/pricing/ · https://aws.amazon.com/s3/pricing/ · https://wondernetwork.com/pings/Seoul/Tokyo · https://wondernetwork.com/pings/Seoul/Singapore
