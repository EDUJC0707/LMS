# PROGRESS

> 완료 기록 누적. 최신이 위.

## 2026-07-22

- **grades 앱 구현 완료** (Fable 5 에이전트, TDD): 도메인 2 전체 12개 표(class_sessions, attendances, exams, questions, answer_sheets, sheet_answers, scores, assignments, question_bank_items, question_similar_maps, weakness_check_pdfs, workbook_submissions). Attendance SSOT 계약 docstring+테스트 고정, '퇴원' 값 부재 테스트 강제, 부분 인덱스·GIN 반영. 테스트 47건(curr 19+grades 28) 통과.
- **curriculum 주차 공개 게이팅** (대표 요구 — 상태 기반 노출 원칙의 콘텐츠 축): CourseWeek.release_at(NULL=주 시작일 공개, 둘 다 NULL=비공개가 안전 기본값) + `released()` 쿼리셋 = 소비자 API 유일 진입 계약. 마이그레이션 0002.
- **PRD §4 "상태 기반 노출 원칙" 신설** (대표 요구 정정 반영): 학생·학부모에겐 "지금 해당되는 것만" — 신규 계정 첫 로그인 거의 bare, 기능 단위(동보=결석생만·클리닉=대상자만)·콘텐츠 단위(시작된 주차까지만) 노출, API 레벨 강제.
- **프런트 A/B/C-1 실험 전체 완료**: A안(frontend-design)을 메인 frontend/에 반영(가역), A=5173·B=5199 dev 서버 가동. C-1안(@carbon/react 1.112 + (IBM_sample)DESIGN.md 기준) 완료 — DESIGN.md Do/Don't 검수에서 위반 2건(일요일 Red 60, 마스트헤드 테마) 자체 적발·수정. 3자 비교 후 사용자 선택 대기. Carbon MCP는 IBM 인바이트 승인 대기(C-2 정제 패스용).

## 2026-07-22 (자정 직후)

- **curriculum 앱 구현 완료** (Fable 5 에이전트, TDD): courses·course_weeks·week_day_plans·course_enrollments 4개 표, 부분 인덱스(`WHERE status='수강'`) 실물 확인, 테스트 10건, 로컬 PG migrate OK. 스킬 invoke 증빙(tdd·verification) 검수 통과. 커밋 대기.
- **프런트 A/B 실험 완료** (Fable 5 × 2, worktree 병렬): 학생용 캘린더 홈 동일 스펙 2안. A=frontend-design(도장 인영+주차 거터, 캘린더 중심 2컬럼), B=hallmark(Cobalt·헤어라인 테이블, 마감 카드 상단 전폭). 둘 다 typecheck·build 통과, iPad·데스크탑 스크린샷 scratchpad 저장. 사용자 선택 대기.
- 관리 파일 신설: .claude/to-do.md·progress.md. CLAUDE.md에 "스킬 항상 invoke, Read 대체 금지" 규칙 추가.

## 2026-07-21

- **인프라 파악·정비**: Fly 3앱 확인(edujc-lms v5 가동·edujc-pg PG18·edujc-qbank 자리). 오전 배포가 기본 auth.User로 원격 DB를 밟은 것 발견 → **원격 스키마 리셋 완료·검증**(테이블 0). 로컬은 OrbStack 설치 → docker compose(PG16+Redis7) 가동, migrate 올바른 순서 적용, 테스트 실 PG 통과.
- **accounts 앱 구현 완료** (`decfa7e`): 커스텀 User(login_id, role 5종, must_change_password) + Student/Parent/ParentStudent. AUTH_USER_MODEL 첫 마이그레이션에 정착. 테스트 7건.
- **PRD 정합화 커밋** (`daf6c69`): 미팅 0715·0721 직접 정독 → 영상 호스팅 전환(YouTube+RPA 폐기→외부 DRM 4K, 연동 후순위)·워크북 원번(조교 기입+OCR)·동보 수강료 모순 제거·누락 추가. 미결 9건 결정 반영(아이디=전화번호, 수동 퇴원만, 전화 3회→문자, 결석생 답안입력 1차 제외, 영상 전량 보관, 문제DB 동일서버 등). 남은 미결: 8-1(개인정보)·8-14(오픈 범위)·8-17(7/29 수신).
- **저장소 재구성** (`9224d72`): 작업 표면 4개(backend/frontend/infra/docs/PRD.md)로 정리, archive/ gitignore, .claude/CLAUDE.md 규칙화(에이전트 20개 제한 포함).
- 플러그인: superpowers, mattpocock-skills 설치. Fable 5 서브에이전트 Skill invoke 가능 실측 확인.
