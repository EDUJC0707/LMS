/**
 * 없는 주소(404). 자격이 없어 메뉴에서 빠진 화면도 여기로 온다 —
 * 둘을 구분해 알려 주지 않는다(어떤 화면이 있는지 노출하지 않는다, PRD §4).
 * 기능 권한이 없어 막힌 경우(403)는 RequireFeature 가 화면 안에서 안내한다.
 */
import { Link, useNavigate } from "react-router-dom";

import { homePathFor } from "../../api";
import { useMe } from "../../auth";
import { Button, Card, EmptyState, PageHeader } from "../../components";

export function NotFoundPage() {
  const { me } = useMe();
  const navigate = useNavigate();

  return (
    <>
      <PageHeader
        title="찾을 수 없는 화면입니다"
        description="주소가 바뀌었거나, 지금 로그인한 계정에서는 볼 수 없는 화면입니다."
      />
      <Card>
        <EmptyState
          title="주소를 다시 확인해 주세요"
          description={
            me
              ? "왼쪽 메뉴에는 지금 계정에서 쓸 수 있는 화면만 있습니다. 거기서 다시 찾아 주세요."
              : "로그인한 뒤에 다시 시도해 주세요."
          }
          action={
            me ? (
              <div className="ui-row">
                <Button
                  variant="primary"
                  onClick={() => navigate(homePathFor(me.role), { replace: true })}
                >
                  홈으로 가기
                </Button>
                <Link className="ui-btn ui-btn--secondary" to="/boards/공지사항">
                  공지사항 보기
                </Link>
              </div>
            ) : (
              <Link className="ui-btn ui-btn--primary" to="/login/student">
                로그인 화면으로
              </Link>
            )
          }
        />
      </Card>
    </>
  );
}
