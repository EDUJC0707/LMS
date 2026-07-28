/**
 * 예비등록·퇴원 자녀를 고른 상태에서 성적·워크북·동보 화면에 대신 그리는 안내.
 *
 * 학생 화면은 예비등록이면 메뉴 자체가 없다(auth/nav.ts 의 enrolled 게이트).
 * 학부모는 자녀를 바꿔 가며 보는 화면이라 메뉴를 통째로 없앨 수 없으므로,
 * 대상이 아닌 자녀를 고른 동안 화면 본문을 이 안내로 바꾼다 —
 * 없는 데이터를 빈 표로 보여 주지 않는다(PRD §4 상태 기반 노출).
 */
import { MeChild } from "../../api";
import { Badge, Card, EmptyState } from "../../components";
import "./parent.css";

export interface PreEnrollNoticeProps {
  child: MeChild | null;
  /** 이 화면이 무엇인지 — "성적", "워크북", "보강 영상 신청" */
  what: string;
}

export function PreEnrollNotice({ child, what }: PreEnrollNoticeProps) {
  const name = child?.name ?? "자녀";
  const status = child?.enrollment_status ?? "미등록";
  const withdrawn = status === "퇴원";

  return (
    <Card title="지금 상태">
      <div className="ui-row">
        <Badge tone={withdrawn ? "neutral" : "warning"}>{status}</Badge>
        <span className="parent-note">{name} 학생</span>
      </div>
      <div style={{ marginTop: "var(--space-md)" }}>
        <EmptyState title={`${name} 학생은 아직 ${what} 대상이 아닙니다`} />
      </div>
    </Card>
  );
}
