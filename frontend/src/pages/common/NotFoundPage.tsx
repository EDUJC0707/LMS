/**
 * 없는 주소(404). 자격이 없어 메뉴에서 빠진 화면도 여기로 온다 —
 * 둘을 구분해 알려 주지 않는다(어떤 화면이 있는지 노출하지 않는다, PRD §4).
 */
import { Link, useNavigate } from "react-router-dom";

import { homePathFor } from "../../api";
import { useMe } from "../../auth";
import { Button, Card, EmptyState } from "../../components";
import "./common.css";

export function NotFoundPage() {
  const { me } = useMe();
  const navigate = useNavigate();

  return (
    // 이 화면만 자기 h1 을 갖는다 — pageFor() 가 null 이라 상단바 왼쪽이 비어 있다.
    // 다만 같은 문장을 두 번 보여 주지는 않는다(빈 상태가 이미 크게 말한다).
    <>
      <h1 className="sr-only">찾을 수 없는 화면입니다</h1>
      <Card className="cm-narrow">
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
