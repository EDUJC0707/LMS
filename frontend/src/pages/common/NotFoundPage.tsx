/**
 * 없는 주소(404). 자격이 없어 메뉴에서 빠진 화면도 여기로 온다 —
 * 둘을 구분해 알려 주지 않는다(어떤 화면이 있는지 노출하지 않는다, PRD §4).
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
      <PageHeader title="찾을 수 없는 화면입니다" />
      <Card>
        <EmptyState
          title="찾을 수 없는 화면입니다"
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
              <Link className="ui-btn ui-btn--primary" to="/login">
                로그인 화면으로
              </Link>
            )
          }
        />
      </Card>
    </>
  );
}
