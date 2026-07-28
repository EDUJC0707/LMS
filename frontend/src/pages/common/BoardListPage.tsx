/**
 * 게시판 목록 — /boards/:category (공지사항·질답·정오표·자유게시판·이벤트굿즈).
 *
 * API: GET  /api/boards/{category}?page=   목록(최신순·20건)
 *      POST /api/boards/{category}         작성(권한 매트릭스는 서버가 강제)
 *      GET  /api/boards/{category}/{id}    자유게시판 피드 본문(목록에 본문이 없다)
 *
 * 화면 규칙
 * - 비밀글은 서버가 제목·작성자를 가려서 내려준다. 가려진 줄은 링크로 만들지
 *   않는다(눌러도 404 인 곳으로 보내지 않는다).
 * - 글쓰기 버튼은 그 게시판에 쓸 수 있는 사람에게만 보인다(PRD §4).
 * - 자유게시판은 강사가 짧게 올리는 피드라 목록 자체가 읽는 화면이다.
 */
import { FormEvent, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { http, useApi, useApiAction } from "../../api";
import { useMe } from "../../auth";
import {
  Alert,
  Badge,
  Button,
  Card,
  Checkbox,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  PageHeader,
  Pagination,
  Tabs,
  Textarea,
} from "../../components";
import {
  BOARD_BODY_LABEL,
  BOARD_CATEGORIES,
  BOARD_EMPTY,
  API_PAGE_SIZE,
  BOARD_TITLE_LABEL,
  BOARD_WRITE_LABEL,
  BoardCategory,
  Paged,
  PostDetail,
  PostRow,
  allowsSecret,
  canWriteBoard,
  formatDay,
  isBoardCategory,
  isMasked,
} from "./boards";
import "./common.css";

export default function BoardListPage() {
  const { category = "" } = useParams();
  const decoded = decodeURIComponent(category);

  if (!isBoardCategory(decoded)) {
    return (
      <>
        <PageHeader title="게시판" />
        <Card>
          <EmptyState
            title="없는 게시판입니다"
            action={
              <Link className="ui-btn ui-btn--primary" to="/boards/공지사항">
                공지사항 보기
              </Link>
            }
          />
        </Card>
      </>
    );
  }

  return <BoardList category={decoded} />;
}

function BoardList({ category }: { category: BoardCategory }) {
  const navigate = useNavigate();
  const { me } = useMe();
  const [page, setPage] = useState(1);
  const [writing, setWriting] = useState(false);

  useEffect(() => {
    setPage(1);
  }, [category]);

  const list = useApi(
    () =>
      http
        .get<Paged<PostRow>>(`/boards/${encodeURIComponent(category)}`, { params: { page } })
        .then((response) => response.data),
    [category, page],
  );

  const rows = list.data?.results ?? [];
  const isFeed = category === "자유게시판";
  const feedIds = isFeed ? rows.map((row) => row.post_id) : [];
  const feedKey = feedIds.join(",");

  // 목록 응답에는 본문이 없다. 피드로 읽히려면 본문이 필요하므로 이 페이지에
  // 보이는 글만큼만(한 쪽 최대 20건) 상세를 함께 불러온다.
  const bodies = useApi(async () => {
    if (!feedKey) return {} as Record<number, string>;
    const loaded = await Promise.all(
      feedIds.map(async (id) => {
        try {
          const response = await http.get<PostDetail>(
            `/boards/${encodeURIComponent(category)}/${id}`,
          );
          return [id, response.data.body] as const;
        } catch {
          return [id, ""] as const;
        }
      }),
    );
    return Object.fromEntries(loaded) as Record<number, string>;
  }, [category, feedKey]);

  const canWrite = canWriteBoard(category, me);
  const totalPages = Math.max(1, Math.ceil((list.data?.count ?? 0) / API_PAGE_SIZE));
  const busy = list.loading || (isFeed && bodies.loading);

  const afterCreate = async () => {
    setWriting(false);
    if (page !== 1) setPage(1);
    else await list.reload();
  };

  return (
    <>
      <PageHeader
        title={category}
        actions={
          canWrite && (
            <Button variant="primary" onClick={() => setWriting(true)}>
              {BOARD_WRITE_LABEL[category]}
            </Button>
          )
        }
      />

      <div className="ui-stack">
        <Tabs
          label="게시판 종류"
          value={category}
          onChange={(next) => navigate(`/boards/${next}`)}
          items={BOARD_CATEGORIES.map((name) => ({ key: name, label: name }))}
        />

        {busy ? (
          <Loading label="글을 불러오는 중…" />
        ) : list.error ? (
          <ErrorState description={list.error} onRetry={list.reload} />
        ) : rows.length === 0 ? (
          <Card>
            <EmptyState
              title={BOARD_EMPTY[category]}
              action={
                canWrite && (
                  <Button variant="primary" onClick={() => setWriting(true)}>
                    {BOARD_WRITE_LABEL[category]}
                  </Button>
                )
              }
            />
          </Card>
        ) : (
          <>
            <Card padding="none" className="cm-clip">
              {isFeed ? (
                <ul className="cm-feed">
                  {rows.map((post) => (
                    <li key={post.post_id}>
                      <FeedItem
                        post={post}
                        body={bodies.data?.[post.post_id] ?? ""}
                        category={category}
                      />
                    </li>
                  ))}
                </ul>
              ) : (
                <ul className="cm-list">
                  {rows.map((post) => (
                    <li key={post.post_id}>
                      <PostRowItem post={post} category={category} />
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <Pagination
              page={page}
              totalPages={totalPages}
              onChange={setPage}
              status={`전체 ${list.data?.count ?? 0}건`}
            />
          </>
        )}
      </div>

      <WriteDialog
        category={category}
        open={writing}
        onClose={() => setWriting(false)}
        onCreated={afterCreate}
      />
    </>
  );
}

/** 목록 한 줄. 가려진 비밀글은 링크가 아니다. */
function PostRowItem({ post, category }: { post: PostRow; category: BoardCategory }) {
  if (isMasked(post)) {
    return (
      <div className="cm-row cm-row--locked">
        <span className="cm-row__main">
          <span className="cm-row__title">비밀글입니다</span>
        </span>
        <span className="cm-row__meta">작성자와 학원 직원만 볼 수 있습니다</span>
      </div>
    );
  }

  return (
    <Link className="cm-row" to={`/boards/${category}/${post.post_id}`}>
      <span className="cm-row__main">
        <span className="cm-row__title">{post.title}</span>
        <RowBadges post={post} category={category} />
      </span>
      <span className="cm-row__meta">
        <span>{post.author_name}</span>
        <span aria-hidden="true">·</span>
        <span>{formatDay(post.created_at)}</span>
        {post.comment_count > 0 && (
          <>
            <span aria-hidden="true">·</span>
            <span className="cm-row__count">댓글 {post.comment_count}</span>
          </>
        )}
      </span>
    </Link>
  );
}

function RowBadges({ post, category }: { post: PostRow; category: BoardCategory }) {
  return (
    <>
      {post.is_secret && <Badge tone="neutral">비밀글</Badge>}
      {category === "질답" && post.comment_count > 0 && <Badge tone="success">답변 완료</Badge>}
      {post.course_week && (
        <Badge tone="outline">
          {post.course_week.course_name} {post.course_week.week_no}주차
        </Badge>
      )}
      {!post.is_published && <Badge tone="warning">미게시</Badge>}
      {post.is_mine && <Badge tone="accent">내 글</Badge>}
    </>
  );
}

/** 자유게시판 — 제목을 누르지 않아도 본문이 보이는 피드 한 칸. */
function FeedItem({
  post,
  body,
  category,
}: {
  post: PostRow;
  body: string;
  category: BoardCategory;
}) {
  return (
    <article className="cm-feed__item">
      <header className="cm-feed__head">
        <span className="cm-feed__author">{post.author_name ?? "작성자 비공개"}</span>
        <span aria-hidden="true">·</span>
        <span>{formatDay(post.created_at)}</span>
        {post.updated_at && <span>(수정됨)</span>}
        {!post.is_published && <Badge tone="warning">미게시</Badge>}
      </header>
      <h2 className="cm-feed__title">{post.title}</h2>
      {body ? (
        <p className="cm-prose">{body}</p>
      ) : (
        <p className="cm-row__meta">본문은 글을 열어서 볼 수 있습니다.</p>
      )}
      <footer className="cm-feed__foot">
        <Link to={`/boards/${category}/${post.post_id}`}>
          {post.comment_count > 0 ? `댓글 ${post.comment_count}개 보기` : "댓글 남기기"}
        </Link>
      </footer>
    </article>
  );
}

/** 글쓰기 — 모달 안에서 실패하면 토스트가 가려지므로 Alert 로 보여준다. */
function WriteDialog({
  category,
  open,
  onClose,
  onCreated,
}: {
  category: BoardCategory;
  open: boolean;
  onClose: () => void;
  onCreated: () => void | Promise<void>;
}) {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [secret, setSecret] = useState(false);
  const [titleError, setTitleError] = useState<string | null>(null);
  const [bodyError, setBodyError] = useState<string | null>(null);

  const create = useApiAction(async (payload: Record<string, unknown>) => {
    await http.post(`/boards/${encodeURIComponent(category)}`, payload);
    return true as const;
  });

  const close = () => {
    create.clearError();
    setTitleError(null);
    setBodyError(null);
    onClose();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmedTitle = title.trim();
    setTitleError(trimmedTitle ? null : "제목을 입력해 주세요.");
    setBodyError(body.trim() ? null : "내용을 입력해 주세요.");
    if (!trimmedTitle || !body.trim()) return;

    const payload: Record<string, unknown> = { title: trimmedTitle, body };
    if (allowsSecret(category)) payload.is_secret = secret;

    const done = await create.run(payload);
    if (!done) return;
    setTitle("");
    setBody("");
    setSecret(false);
    await onCreated();
  };

  return (
    <Modal
      open={open}
      onClose={close}
      title={BOARD_WRITE_LABEL[category]}
      footer={
        <>
          <Button onClick={close}>취소</Button>
          <Button type="submit" form="cm-write-form" variant="primary" loading={create.pending}>
            등록
          </Button>
        </>
      }
    >
      <form id="cm-write-form" onSubmit={submit} noValidate className="ui-stack ui-stack--sm">
        {create.error && <Alert tone="danger">{create.error}</Alert>}

        <Field label={BOARD_TITLE_LABEL[category]} error={titleError} required>
          {(props) => (
            <Input
              {...props}
              value={title}
              maxLength={200}
              onChange={(event) => {
                setTitle(event.target.value);
                if (titleError) setTitleError(null);
              }}
            />
          )}
        </Field>

        <Field
          label={BOARD_BODY_LABEL[category]}
          error={bodyError}
          required
        >
          {(props) => (
            <Textarea
              {...props}
              rows={6}
              value={body}
              onChange={(event) => {
                setBody(event.target.value);
                if (bodyError) setBodyError(null);
              }}
            />
          )}
        </Field>

        {allowsSecret(category) && (
          <Checkbox
            label="비밀글로 남기기 — 나와 학원 직원만 볼 수 있습니다"
            checked={secret}
            onChange={(event) => setSecret(event.target.checked)}
          />
        )}
      </form>
    </Modal>
  );
}
