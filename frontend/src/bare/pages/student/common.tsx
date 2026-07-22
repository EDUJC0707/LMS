/** 학생 페이지 공용 조각. */
export function currentMonth(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}`;
}

export function DebugNote() {
  return (
    <p className="muted">응답 JSON 원문은 페이지 하단 디버그 패널에서 확인.</p>
  );
}
