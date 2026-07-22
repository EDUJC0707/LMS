# TO-DO

> 갱신 규칙: 완료되면 체크 후 `progress.md`로 요약을 옮긴다. 세션 시작 시 이 파일부터 본다.

## 진행 중 (2026-07-21 발사)

- [x] 백엔드: curriculum 앱 구현 — 완료(2026-07-21 밤). 4개 표, 테스트 10건, TDD·검증 스킬 invoke 증빙 확인. 커밋 대기
- [x] 프런트 A/B 실험: 캘린더 홈 두 안 완성(2026-07-22). 둘 다 typecheck·build 통과, 스킬 invoke 증빙 확인. **→ 사용자 승자 선택 대기** (선택 후 해당 worktree 브랜치를 main에 병합, 나머지 폐기)

## 대기

- [ ] **DB 설계 재검토(전면 재설계 허용)** — 사용자 지시 2026-07-21: 진행 중인 에이전트 3개 완료 후 착수. DRM 전환·오늘 결정 9건 반영 관점에서 lms-db-design-2026-07-15.md 전체 재점검
- [ ] **Carbon MCP 연결** — IBM 인바이트 승인 대기(2026-07-22 액세스 요청 제출, seanpark98@gmail.com로 인바이트 코드 수신 예정). 코드 수신 → `claude mcp add-json carbon-mcp '{"type":"http","url":"https://mcp.carbondesignsystem.com/mcp","headers":{"Authorization":"Bearer <토큰>","X-MCP-Session":"<세션>"}}'` → 세션 재시작(진행 중 에이전트 없는 때에). 연결 후 C안 정제 2차 패스
- [x] 프런트 **C-1안**(@carbon/react + DESIGN.md 기준) — 완료(2026-07-22). build·typecheck 통과, DESIGN.md 검수 위반 2건 자체 수정, 스크린샷 저장. **→ A/B/C 3자 비교 후 사용자 선택 대기.** MCP 키 수신 시 C-2 정제 패스
- [x] 백엔드: curriculum 주차 게이팅(release_at + released() 계약) + grades 앱 12개 모델(출결 SSOT) — 완료(2026-07-22), 테스트 47건·전 검증 통과, 재검증 완료. 커밋 대기
- [ ] 백엔드 다음 순서: grades(출결 SSOT) → clinic → boards → payments → videos(마지막)
- [ ] videos 착수 전: DB 설계의 `youtube_email`·유튜브 권한 상태기계를 DRM 전제로 정리
- [ ] 계정 일괄생성 배치 (아이디=전화번호, PRD 8-4)
- [ ] 백엔드 플러그인 설치 검토: pyright-lsp, context7 (사용자 승인 대기)
- [ ] 첫 실배포 전: prod SECRET_KEY fail-fast, whitenoise, `UV_NO_DEV=1`, uv 이미지 태그 고정, CI `FLY_API_TOKEN`

## 외부 대기 (날짜 확정)

- [ ] 7/29(수): 알림톡 발송 리스트 + 랜딩 컴포넌트 수신(PRD 8-17) → 알림 템플릿·랜딩 개발 해제
- [ ] 박 대표 컨펌 확인: 채널톡 도입·영상 업체(Mux/VdoCipher)·UI 방향 (0721 회의에서 당일 컨펌 예정이었음)
- [ ] 랜딩 정보: 7월 마지막 주 확정
- [ ] PRD 8-14: 1차 오픈 범위 — 개발 1주 돌려보고 재논의
