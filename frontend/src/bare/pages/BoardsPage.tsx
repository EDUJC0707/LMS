/**
 * 게시판 — 카테고리 5종 목록/작성/상세/수정/삭제/댓글 (PRD 3.3.1·3.3.2).
 * 작성 권한 매트릭스는 백엔드가 강제한다 — 권한 없는 작성은 403 사유를 그대로 표시.
 */
/* eslint-disable @typescript-eslint/no-explicit-any */
import { FormEvent, useState } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";

import { api, errMsg } from "../api";
import { Msg, useLoad } from "../ui";

const CATEGORIES = ["공지사항", "질답", "정오표", "자유게시판", "이벤트굿즈"];

function CategoryTabs() {
  return (
    <nav>
      {CATEGORIES.map((category) => (
        <NavLink key={category} to={`/bare/boards/${category}`}>
          [{category}]
        </NavLink>
      ))}
    </nav>
  );
}

export function BoardListPage() {
  const { category = "공지사항" } = useParams();
  const [page, setPage] = useState(1);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [isSecret, setIsSecret] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const list = useLoad<any>(
    async () => (await api.get(`/boards/${category}`, { params: { page } })).data,
    [category, page],
  );

  const create = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    setOk(null);
    try {
      const payload: Record<string, unknown> = { title, body };
      if (category === "질답") payload.is_secret = isSecret;
      await api.post(`/boards/${category}`, payload);
      setOk("작성 완료");
      setTitle("");
      setBody("");
      setIsSecret(false);
      await list.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  return (
    <section>
      <h2>게시판 — {category}</h2>
      <CategoryTabs />
      <Msg error={list.error} />
      {list.data && (
        <>
          <p className="muted">총 {list.data.count}건</p>
          <table>
            <thead>
              <tr>
                <th>번호</th>
                <th>제목</th>
                <th>작성자</th>
                <th>댓글</th>
                <th>주차 연동</th>
                <th>작성 시각</th>
              </tr>
            </thead>
            <tbody>
              {list.data.results.map((post: any) => (
                <tr key={post.post_id}>
                  <td>{post.post_id}</td>
                  <td>
                    <Link to={`/bare/boards/${category}/${post.post_id}`}>
                      {post.is_secret ? "(비밀글) " : ""}
                      {post.title}
                    </Link>
                    {!post.is_published && <span className="muted"> (미게시)</span>}
                    {post.is_mine && <span className="muted"> (내 글)</span>}
                  </td>
                  <td>{post.author_name ?? "-"}</td>
                  <td>{post.comment_count}</td>
                  <td>
                    {post.course_week
                      ? `${post.course_week.course_name} ${post.course_week.week_no}주차`
                      : "-"}
                  </td>
                  <td>{post.created_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="inline">
            <button disabled={!list.data.previous} onClick={() => setPage(page - 1)}>
              이전
            </button>
            <span> {page}쪽 </span>
            <button disabled={!list.data.next} onClick={() => setPage(page + 1)}>
              다음
            </button>
          </p>
        </>
      )}
      <h3>글 작성</h3>
      <p className="muted">
        작성 권한: 공지·정오표·이벤트굿즈=직원(공지작성 키) / 질답=학생·학부모 /
        자유게시판=대표. 권한 없는 작성은 403 사유가 아래 표시된다.
      </p>
      <form onSubmit={create}>
        <p>
          <input
            placeholder="제목"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            size={50}
          />
        </p>
        <p>
          <textarea
            placeholder="본문"
            rows={4}
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
        </p>
        {category === "질답" && (
          <p>
            <label>
              <input
                type="checkbox"
                checked={isSecret}
                onChange={(e) => setIsSecret(e.target.checked)}
              />{" "}
              비밀글(작성자·직원만 열람 — 1:1 문의용)
            </label>
          </p>
        )}
        <button type="submit">등록</button>
      </form>
      <Msg error={error} ok={ok} />
    </section>
  );
}

export function BoardPostPage() {
  const { category = "공지사항", postId } = useParams();
  const navigate = useNavigate();
  const [comment, setComment] = useState("");
  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState("");
  const [editBody, setEditBody] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState<string | null>(null);

  const post = useLoad<any>(
    async () => (await api.get(`/boards/${category}/${postId}`)).data,
    [category, postId],
  );

  const act = async (fn: () => Promise<unknown>, okMessage: string, reload = true) => {
    setError(null);
    setOk(null);
    try {
      await fn();
      setOk(okMessage);
      if (reload) await post.reload();
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const addComment = (event: FormEvent) => {
    event.preventDefault();
    void act(async () => {
      await api.post(`/boards/${category}/${postId}/comments`, { body: comment });
      setComment("");
    }, "댓글 등록");
  };

  const saveEdit = (event: FormEvent) => {
    event.preventDefault();
    void act(async () => {
      await api.patch(`/boards/${category}/${postId}`, { title: editTitle, body: editBody });
      setEditing(false);
    }, "수정 완료(updated_at 스탬프)");
  };

  const removePost = async () => {
    setError(null);
    try {
      await api.delete(`/boards/${category}/${postId}`);
      navigate(`/bare/boards/${category}`);
    } catch (e) {
      setError(errMsg(e));
    }
  };

  const data = post.data;
  return (
    <section>
      <h2>
        {category} 글 <Link to={`/bare/boards/${category}`}>(목록으로)</Link>
      </h2>
      <Msg error={post.error ?? error} ok={ok} />
      {post.loading && <p>불러오는 중…</p>}
      {data && (
        <>
          <h3>
            {data.is_secret ? "(비밀글) " : ""}
            {data.title}
          </h3>
          <p className="muted">
            {data.author_name} · {data.created_at}
            {data.updated_at && ` (수정 ${data.updated_at})`}
            {data.course_week &&
              ` · ${data.course_week.course_name} ${data.course_week.week_no}주차 공지`}
          </p>
          <p style={{ whiteSpace: "pre-wrap" }}>{data.body}</p>
          <p className="inline">
            {data.is_mine && (
              <button
                onClick={() => {
                  setEditing(!editing);
                  setEditTitle(data.title);
                  setEditBody(data.body);
                }}
              >
                {editing ? "수정 취소" : "수정"}
              </button>
            )}
            <button onClick={removePost}>삭제 (본인 또는 직원 운영 삭제)</button>
          </p>
          {editing && (
            <form onSubmit={saveEdit}>
              <p>
                <input
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  size={50}
                />
              </p>
              <p>
                <textarea
                  rows={4}
                  value={editBody}
                  onChange={(e) => setEditBody(e.target.value)}
                />
              </p>
              <button type="submit">수정 저장</button>
            </form>
          )}

          <h3>댓글 {data.comments.length}개</h3>
          <table>
            <tbody>
              {data.comments.map((row: any) => (
                <tr key={row.comment_id}>
                  <td>
                    {row.author_name} ({row.author_role})
                  </td>
                  <td style={{ whiteSpace: "pre-wrap" }}>{row.body}</td>
                  <td>{row.created_at}</td>
                  <td>
                    <button
                      onClick={() =>
                        act(
                          () =>
                            api.delete(
                              `/boards/${category}/${postId}/comments/${row.comment_id}`,
                            ),
                          "댓글 삭제",
                        )
                      }
                    >
                      삭제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <form onSubmit={addComment} className="inline">
            <input
              placeholder="댓글 내용"
              value={comment}
              onChange={(e) => setComment(e.target.value)}
              size={50}
            />
            <button type="submit">댓글 등록</button>
          </form>
        </>
      )}
    </section>
  );
}
