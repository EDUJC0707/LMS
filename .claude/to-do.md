# TO-DO

> 갱신 규칙: 완료되면 체크 후 `progress.md`로 요약을 옮긴다. 세션 시작 시 이 파일부터 본다.
> 완료 항목은 여기 쌓아두지 말 것 — 이 파일은 **앞으로 할 일만** 남긴다.
> 최종 정리: 2026-07-28

## 진행 중

- [ ] **API 갭 보강 워크플로** (2026-07-28 발사): 백엔드 4건 완료(attendance_id 노출·학생 명부 API·children enrollment_status·직원 재활성) → **프런트 배선 진행 중**(동보 신청 완결·워크북 학생 검색·등록 전환·메뉴 정합). 완료 시 재검증 → 커밋

## 다음 (워크플로 끝나면 순서대로)

- [ ] **seed_demo 파일 누적 버그 수정**: DB 행은 리셋되는데 `backend/media/workbook/demo/` 스토리지 파일은 안 지워져 재실행마다 Django 랜덤 접미사로 누적(6회 실행 → 58개). 시드 시작 시 디렉터리 비우기 + `.gitignore`에 `backend/media/` 추가
- [ ] **사용자 직접 테스팅** — 실앱(http://localhost:5173) 전 기능 순회. 이상한 점·빠진 기능 피드백 받아 수정
- [ ] PRD 3장 대비 **API 미구현 목록** 채우기(우선순위는 테스팅 후 결정):
  OMR 스캔 업로드·자동 채점·보정 UI / 문항 정보 입력 / 성적표·약점체크 PDF 생성 /
  퇴원 처리 / 학부모 상담 신청 / 관리자 발송내역 조회 / 문제은행·유사문항 매칭 /
  교재 청구 개시 API / 시험·상담 목록 서버 필터·페이징
- [ ] PRD 8-14: **1차 오픈 범위** 확정 — 개발 속도 나왔으니 이번 주 결정 가능

## 배포 전 (반나절 거리, 첫 실배포 직전 일괄)

- [ ] prod `SECRET_KEY` fail-fast(기본값 제거), whitenoise + collectstatic(현재 /static/ 404)
- [ ] `infra/Dockerfile`에 `ENV UV_NO_DEV=1`(부팅 13초 지연), uv 이미지 태그 고정
- [ ] CI `FLY_API_TOKEN` 시크릿(현재 미설정이라 자동배포 실행 자체가 안 됨)
- [ ] Fly `edujc-lms` 헬스체크 critical 상태 원인 확인
- [ ] **Sentry 붙이기 — 사용자 가입만 남음**(2026-07-28 보류). 코드는 이미 완료: `prod.py`에 `sentry_sdk.init()`(DSN 있으면 활성화, `send_default_pii=False`) + `sentry-sdk>=2.14` 의존성. **남은 건 DSN 하나.** `fly ext sentry create`는 **불가**(7/28 실행 확인: "Sentry is no longer accepting new Fly.io integrations" — Team 1년 무료 딜 소멸) → **sentry.io 직접 가입**(Developer 무료: 에러 5천건/월·1명, LMS 규모엔 충분) → 플랫폼 Django → DSN 복사 → `fly secrets set SENTRY_DSN="<DSN>" -a edujc-lms` → 실제 에러 1건으로 수집 검증. **동기**: `fly logs`가 ~30분만 남아 "어제 왜 500났지"를 사후 추적 못 함(7/28 qbank 500 조사에서 실제로 막힘)
- [ ] **Celery 워커 + Redis 기동 — 아직 아님**(2026-07-22 결정, 보류 유지). `@shared_task` 0건이라 할 일이 없고 워커는 auto_stop 대상이 아니라 24시간 돌며 월 ~$3.3. **해제 트리거 = 첫 `@shared_task` 작성 시점**(알림톡 발송 또는 영상 처리). 복구 3단계와 경위는 `infra/DEPLOY.md` 6장

## 외부 대기 (오는 대로 붙임 — 자리는 다 파여 있음)

- [ ] **알림톡 발송 시점 리스트**(PRD 8-17) → 솔라피 연동 + 첫 Celery 태스크. 랜딩 컴포넌트는 7/28 수신 완료
- [ ] **박 대표 컨펌**: 채널톡 도입 · 영상 업체(Mux/VdoCipher) · UI 방향 (0721 회의에서 당일 컨펌 예정이었음)
- [ ] 결제선생 연동 스펙 / OMR 인식 엔진 / Meet API(현재 meet_url 수동 입력)
- [ ] **Carbon MCP 인바이트** — IBM 승인 대기(7/22 요청). 코드 오면 `claude mcp add-json carbon-mcp ...` → 세션 재시작. **단 현재 디자인은 hallmark 네이비로 확정됐으므로 참고용으로 격하**

## 보류·판단 대기

- [ ] 백엔드 플러그인 설치 검토: pyright-lsp, context7 (사용자 승인 대기)
- [ ] A/B/C 디자인 실험 worktree 3개 — hallmark 네이비 전면 재구현으로 **역할 종료**. 삭제 여부 사용자 확인 필요(`.claude/worktrees/`)
- [ ] `docs/backlog.md` — 내용이 PRD §8.1로 흡수됨. 삭제 후보
