# TO-DO

> 갱신 규칙: 완료되면 체크 후 `progress.md`로 요약을 옮긴다. 세션 시작 시 이 파일부터 본다.

## 진행 중

- [x] **A/B/C 실험 2라운드 완료** (2026-07-22): 3안 모두 학부모 홈·관리자 홈·출결 입력 추가, build·typecheck 통과, 학생 홈 회귀 없음. **→ 사용자 최종 선택 대기** (A 단일 통일 vs 역할 분리)
- [ ] 라이브 비교: A=5173(worktree로 전환) · B=5199 · C=5210

## 완료 (2026-07-21~22 1라운드)

- [x] 백엔드: curriculum 앱 구현 — 완료(2026-07-21 밤). 4개 표, 테스트 10건, TDD·검증 스킬 invoke 증빙 확인. 커밋 대기
- [x] 프런트 A/B 실험: 캘린더 홈 두 안 완성(2026-07-22). 둘 다 typecheck·build 통과, 스킬 invoke 증빙 확인. **→ 사용자 승자 선택 대기** (선택 후 해당 worktree 브랜치를 main에 병합, 나머지 폐기)

## 대기

- [ ] **DB 설계 재검토(전면 재설계 허용)** — 사용자 지시 2026-07-21: 진행 중인 에이전트 3개 완료 후 착수. DRM 전환·오늘 결정 9건 반영 관점에서 lms-db-design-2026-07-15.md 전체 재점검
- [ ] **Carbon MCP 연결** — IBM 인바이트 승인 대기(2026-07-22 액세스 요청 제출, seanpark98@gmail.com로 인바이트 코드 수신 예정). 코드 수신 → `claude mcp add-json carbon-mcp '{"type":"http","url":"https://mcp.carbondesignsystem.com/mcp","headers":{"Authorization":"Bearer <토큰>","X-MCP-Session":"<세션>"}}'` → 세션 재시작(진행 중 에이전트 없는 때에). 연결 후 C안 정제 2차 패스
- [x] 프런트 **C-1안**(@carbon/react + DESIGN.md 기준) — 완료(2026-07-22). build·typecheck 통과, DESIGN.md 검수 위반 2건 자체 수정, 스크린샷 저장. **→ A/B/C 3자 비교 후 사용자 선택 대기.** MCP 키 수신 시 C-2 정제 패스
- [x] 백엔드: curriculum 주차 게이팅(release_at + released() 계약) + grades 앱 12개 모델(출결 SSOT) — 완료(2026-07-22), 테스트 47건·전 검증 통과, 재검증 완료. 커밋 대기
- [x] 백엔드 모델 계층 완성(2026-07-22): 8개 앱 중 7개 구현(accounts·curriculum·grades·clinic·boards·payments·notifications), 테스트 118건. **videos만 남음**(DRM 재설계와 묶어 마지막)
- [x] DB 설계 재검토 완료(2026-07-22): 정합성 어긋남 7건, videos 3표 재설계안, staff_feature_grants 설계안, 누락 8건 분류
- [x] 재검토 필수 5건 구현 완료(2026-07-22, `4e6d8da`): 8개 앱 스키마 100%, 테스트 163건, 설계 문서 도메인 4 개정
- [ ] **진행 중**: API 슬라이스 1 — 로그인 3종·로그아웃·비번변경·CSRF·`/api/me`(유효 기능 목록 = 메뉴 계약)·권한 부품(IsRole·FeatureRequired)
- [x] API 슬라이스 1~4 완료·커밋(2026-07-22): 인증·/me → 학생/학부모 홈 → 출결 SSOT+트리거 → 동보·클리닉 신청. 테스트 358건
- [x] **API 슬라이스 5~8 완주(2026-07-22)**: 성적표·게시판·워크북·관리자 운영. **테스트 587건 전체 통과 — 외부 연동 제외 백엔드 완료**
- [ ] **진행 중**: 시드 데이터(seed_demo) + `/bare` 기능 전시 프런트(디자인 無, 전 API 커버) — 사용자 직접 테스팅·공부용 (2026-07-22 지시: "그냥 백대로 붙여서")
- [ ] 그다음: ① 사용자 전 기능 직접 테스팅·공부 ② A/B/C 선택은 그 후(디자인 실험 3안은 worktree 보존) ③ 외부 연동 붙는 대로(알림톡 7/29·결제선생·DRM·OMR·Meet) ④ 첫 실배포 체크리스트
- [ ] 계정 일괄생성 배치 (아이디=전화번호, PRD 8-4)
- [ ] 백엔드 플러그인 설치 검토: pyright-lsp, context7 (사용자 승인 대기)
- [ ] 첫 실배포 전: prod SECRET_KEY fail-fast, whitenoise, `UV_NO_DEV=1`, uv 이미지 태그 고정, CI `FLY_API_TOKEN`
- [ ] **Celery 워커 + Redis 기동 — 아직 아님(2026-07-22 결정, 보류 유지)**. 현재 Fly에 worker 그룹 자체가 없고 Redis 미생성. 이유: `@shared_task` 0건이라 할 일이 없고, 워커는 `auto_stop` 대상이 아니라 24시간 돌며 월 ~$3.3만 나감. **해제 트리거 = 첫 `@shared_task` 작성 시점**(알림톡 발송[7/29 리스트 수신] 또는 영상 처리). 복구는 3단계(`fly redis create` → `REDIS_URL` secret → `fly scale count worker=1`) — 절차·비용·경위 전문은 `infra/DEPLOY.md` 6장

## 외부 대기 (날짜 확정)

- [ ] 알림톡 발송 리스트 수신(PRD 8-17) → 알림 템플릿 개발 해제. **랜딩 컴포넌트는 7/28 수신 완료 → 랜딩 보류 해제됨**(`frontend/landing/SPEC.md`)
- [ ] 박 대표 컨펌 확인: 채널톡 도입·영상 업체(Mux/VdoCipher)·UI 방향 (0721 회의에서 당일 컨펌 예정이었음)
- [ ] 랜딩 정보: 7월 마지막 주 확정
- [ ] PRD 8-14: 1차 오픈 범위 — 개발 1주 돌려보고 재논의
