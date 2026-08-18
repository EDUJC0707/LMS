/**
 * 출결 값집합의 화면 어휘 — 담임 명단 · 학생 캘린더 · 학부모 캘린더 공용.
 *
 * 값집합은 서버 `grades.Attendance.Status` 가 원천이다(2026-08-18 `미입력` 추가):
 *   미입력 / 출석 / 결석 / 결석(동보) / 결석(현보)
 * `미입력` 은 아무것도 안 찍었거나 찍은 것을 해제했을 때의 값이다 — 결석이 아니다
 * ("안 왔다"가 아니라 "모른다"). 여기서는 아무것도 나가지 않는다(FLOW 3-4).
 * `지각` 은 없앴다 — 시험을 수업 초반에 보므로 지각하면 OMR 카드가 안 들어오고,
 * 그 사실은 성적의 `시험 미제출`(is_taken=false)로 이미 드러난다. 출결 값으로도
 * 두면 같은 사실이 두 곳에 갈린다.
 *
 * 여기 두는 이유는 두 가지다:
 * 1) 값이 `결석(동보)` 처럼 **괄호를 포함**한다. 화면 어딘가에서 값을 CSS 클래스나
 *    좁은 칸에 그대로 꽂으면 깨진다(`st-cal__mark--결석(동보)` 는 선택자가 아니다).
 *    색 토큰과 짧은 이름을 값에서 한 번만 뽑아 쓴다.
 * 2) 값이 또 바뀔 때 고칠 자리를 하나로 만든다 — 테스트가 누락을 잡는다.
 */

export type AttendanceStatus = "미입력" | "출석" | "결석" | "결석(동보)" | "결석(현보)";

/** 담임이 찍는 순서 — 왼쪽이 기본값(`미입력`). 라디오·범례가 이 순서를 그대로 쓴다. */
export const ATTENDANCE_STATUSES: AttendanceStatus[] = [
  "미입력",
  "출석",
  "결석",
  "결석(동보)",
  "결석(현보)",
];

/** 색 토큰. CSS 는 `--present` / `--makeup` / `--onsite` / `--absent` / `--blank`. */
export type AttendanceTone = "present" | "makeup" | "onsite" | "absent" | "blank";

// 색은 "손이 얼마나 더 가야 하는가" 순이다. 보강이 정해지지 않은 `결석` 만
// 전화가 남으므로 danger 를 준다 — 동보·현보는 이미 처리가 끝난 결석이다.
const TONE: Record<AttendanceStatus, AttendanceTone> = {
  미입력: "blank",
  출석: "present",
  결석: "absent",
  "결석(동보)": "makeup",
  "결석(현보)": "onsite",
};

// 좁은 칸(캘린더 한 칸·라디오 버튼)에는 괄호를 뗀 이름을 쓴다. 사용자가 쓰는
// 말 그대로다("동보", "현보") — 저장된 값 열에는 원문이 그대로 뜬다.
const SHORT: Record<AttendanceStatus, string> = {
  미입력: "미입력",
  출석: "출석",
  결석: "결석",
  "결석(동보)": "동보",
  "결석(현보)": "현보",
};

/** 좁은 칸용 짧은 이름. 모르는 값은 원문 그대로(화면을 비우지 않는다). */
export function shortAttendance(status: string): string {
  return SHORT[status as AttendanceStatus] ?? status;
}

/** 색 토큰. 모르는 값은 중립 — 상태색을 함부로 태우지 않는다. */
export function attendanceTone(status: string): AttendanceTone {
  return TONE[status as AttendanceStatus] ?? "blank";
}
