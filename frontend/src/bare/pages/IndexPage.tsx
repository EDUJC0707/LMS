/** 전 기능 인덱스 — 카탈로그 전체 + 현재 계정 기준 접근 가능 여부. */
import { Link } from "react-router-dom";

import { useMe } from "../MeContext";
import { PAGES, accessLabel, canAccess } from "../catalog";

const SEED_ACCOUNTS: Array<[string, string, string]> = [
  ["대표", "한종철0001", "전권"],
  ["관리자", "김관리0002", "관리자 프리셋"],
  ["조교", "박조교0003", "워크북업로드·클리닉배정"],
  ["학생", "김하늘0001 · 이서준0002 …", "30명(29·30번은 예비등록)"],
  ["학부모", "김하늘0001p · 이서준0002p …", "10명(자녀 1~2명 연동)"],
];

export default function IndexPage() {
  const { me } = useMe();
  return (
    <section>
      <h2>기능 인덱스</h2>
      <p className="muted">
        메뉴는 /api/me 의 role·features 로 조립된다(PRD §4). 아래 표는 전체 카탈로그이며,
        접근 불가 페이지도 직접 열어 403 응답을 확인할 수 있다.
      </p>
      <table>
        <thead>
          <tr>
            <th>페이지</th>
            <th>필요 권한</th>
            <th>현재 계정으로 접근</th>
            <th>설명</th>
          </tr>
        </thead>
        <tbody>
          {PAGES.map((page) => (
            <tr key={page.path}>
              <td>
                <Link to={page.path}>{page.label}</Link>
              </td>
              <td>{accessLabel(page.access)}</td>
              <td>{canAccess(me, page) ? "가능" : "불가(메뉴 숨김)"}</td>
              <td>{page.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <h2>시드 계정 (비밀번호 전부 test1234)</h2>
      <table>
        <thead>
          <tr>
            <th>역할</th>
            <th>아이디</th>
            <th>비고</th>
          </tr>
        </thead>
        <tbody>
          {SEED_ACCOUNTS.map(([role, id, note]) => (
            <tr key={role}>
              <td>{role}</td>
              <td>{id}</td>
              <td>{note}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted">시드 재생성: backend 에서 `uv run python manage.py seed_demo`</p>
    </section>
  );
}
