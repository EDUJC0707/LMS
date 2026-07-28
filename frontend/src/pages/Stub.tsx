import { PageHeader } from "../components";

/**
 * 아직 구현되지 않은 화면의 자리표시. 각 담당 에이전트가 자기 페이지 파일을
 * 통째로 갈아끼우면서 이 컴포넌트 사용도 함께 없앤다.
 * (라우터는 이미 최종 형태이므로 라우터 파일은 건드리지 않는다.)
 */
export function Stub({ title, description }: { title: string; description?: string }) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <p style={{ color: "var(--color-muted)" }}>준비 중입니다.</p>
    </>
  );
}
