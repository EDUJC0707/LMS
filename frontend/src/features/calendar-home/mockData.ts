import type { StudentHomeData } from "./types";

/* 2026년 7월 기준 목 데이터.
   - 커리큘럼: 로직엔제(고2 화학) 10주, 1주차 = 6/28(일)~7/4(토) 주
   - 수업 요일: 수·토 / 기준일: 7/22(수) = 4주차 Day 3 */
export const studentHomeData: StudentHomeData = {
  student: { name: "김서연", className: "고2 로직엔제 B반" },
  course: { name: "로직엔제", totalWeeks: 10, currentWeek: 4 },
  today: "2026-07-22",
  year: 2026,
  month: 7,
  classWeekdays: [3, 6],
  attendance: {
    "2026-07-01": "present",
    "2026-07-04": "present",
    "2026-07-08": "present",
    "2026-07-11": "absent",
    "2026-07-15": "present",
    "2026-07-18": "present",
  },
  weeks: [
    {
      index: 1,
      start: "2026-06-28",
      notice: "오메가 블랙 1회 응시 — 7/1(수) 수업 시간 내",
      plans: [
        { day: 1, title: "화학 결합 개념 강의 · 오리엔테이션" },
        { day: 2, title: "워크북 p.12–19 (화학 결합)" },
        { day: 3, title: "오메가 블랙 1회 오답 정리" },
        { day: 4, title: "복습영상 1강 시청" },
        { day: 5, title: "미니테스트 1회 대비 개념 암기" },
        { day: 6, title: "주말 자율 복습 · 질문 정리" },
      ],
    },
    {
      index: 2,
      start: "2026-07-05",
      notice: "미니테스트 1회 응시 — 7/8(수)",
      plans: [
        { day: 1, title: "분자 구조와 결합각 개념 정리" },
        { day: 2, title: "워크북 p.20–27 (분자 구조)" },
        { day: 3, title: "미니테스트 1회 오답 유사문항 풀기" },
        { day: 4, title: "복습영상 2강 시청" },
        { day: 5, title: "약점체크 PDF 다시풀기" },
        { day: 6, title: "주말 복습 · 질답 게시판에 질문 올리기" },
      ],
    },
    {
      index: 3,
      start: "2026-07-12",
      notice: "워크북 검사 주간 — 마지막 페이지 코멘트 확인",
      plans: [
        { day: 1, title: "동적 평형 개념 강의" },
        { day: 2, title: "워크북 p.28–35 (동적 평형)" },
        { day: 3, title: "7/11(토) 결석분 동보 영상 시청" },
        { day: 4, title: "복습영상 3강 시청" },
        { day: 5, title: "미니테스트 2회 대비" },
        { day: 6, title: "주말 자율 복습" },
      ],
    },
    {
      index: 4,
      start: "2026-07-19",
      notice: "오메가 블랙 2회 응시 — 7/25(토) 수업 시간 내",
      plans: [
        { day: 1, title: "산과 염기 개념 강의 복습" },
        { day: 2, title: "워크북 p.36–43 (중화 반응)" },
        { day: 3, title: "미니테스트 2회 오답 유사문항 풀기" },
        { day: 4, title: "복습영상 4강 시청 (7/23 만료)" },
        { day: 5, title: "오메가 블랙 2회 대비 요약 정리" },
        { day: 6, title: "오메가 블랙 2회 응시 후 가채점" },
      ],
    },
    {
      index: 5,
      start: "2026-07-26",
      notice: "여름 특강 신청 접수 시작 — 7/27(월)",
      plans: [
        { day: 1, title: "중화 적정 실험 분석" },
        { day: 2, title: "워크북 p.44–51 (중화 적정)" },
        { day: 3, title: "오메가 블랙 2회 오답 정리" },
        { day: 4, title: "복습영상 5강 시청" },
        { day: 5, title: "미니테스트 3회 대비" },
        { day: 6, title: "주말 자율 복습" },
      ],
    },
  ],
  deadlines: [
    {
      id: "clinic-0722",
      kind: "clinic",
      title: "클리닉 1:1 화상 보충",
      meta: "오늘 17:00–18:00 · 구글 미트",
      note: "입장 링크는 시작 5분 전에 열려요",
      due: "2026-07-22",
      actionLabel: "신청 내역 보기",
    },
    {
      id: "video-0723",
      kind: "video",
      title: "3주차 복습영상 만료",
      meta: "7월 23일(목) 자정까지 시청 가능",
      due: "2026-07-23",
      actionLabel: "지금 시청",
    },
    {
      id: "payment-0726",
      kind: "payment",
      title: "로직엔제 교재 결제",
      meta: "7월 26일(일)까지 · 결제선생",
      due: "2026-07-26",
      actionLabel: "결제하기",
    },
  ],
};
