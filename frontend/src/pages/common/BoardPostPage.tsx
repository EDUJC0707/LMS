/**
 * 게시글 상세 — /boards/:category/:postId.
 *
 * API: GET    /api/boards/{category}/{id}                     본문 + 댓글
 *      PATCH  /api/boards/{category}/{id}                     수정(본인 글)
 *      DELETE /api/boards/{category}/{id}                     삭제(본인 · 직원)
 *      POST   /api/boards/{category}/{id}/comments            댓글 작성
 *      DELETE /api/boards/{category}/{id}/comments/{id}       댓글 삭제
 *
 * 화면 규칙
 * - 볼 수 없는 글(삭제됨·남의 비밀글)은 서버가 404 로 단일화한다. 화면도
 *   "없는 글"과 "권한 없는 글"을 구분하지 않고 한 문장으로 안내한다.
 * - 삭제는 되돌릴 수 없다(서버 하드 삭제) — 글은 확인 모달, 댓글은 그 자리에서
 *   한 번 더 묻는다.
 *
 * 상단바는 여기서도 "게시판"까지만 말한다 — 어느 게시판의 무슨 글인지는 본문이
 * 들고 있어야 한다. 글 제목은 첫 카드의 제목, 카테고리·작성자·시각은 그 옆
 * aside 다. 수정·삭제는 그 글을 가진 카드의 액션으로 붙는다.
 */
import { FormEvent, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { http, statusOf, toMessage, useApi, useApiAction } from "../../api";
import { useMe } from "../../auth";
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  ErrorState,
  Field,
  Input,
  Loading,
  Modal,
  Textarea,
} from "../../components";
import {
  BoardCategory,
  CommentRow,
  PostDetail,
  canModerateBoard,
  formatStamp,
  isBoardCategory,
} from "./boards";
import "./common.css";

/** 삭제됐거나 볼 자격이 없는 글 — 서버가 둘을 구분하지 않는다(존재 비노출). */
const GONE = "이미 지워졌거나, 작성자와 학원 직원만 볼 수 있는 글입니다.";

const STAFF_ROLE_LABELS = ["대표", "관리자", "조교"];

export default function BoardPostPage() {
  const { category = "", postId = "" } = useParams();
  const decoded = decodeURIComponent(category);
  const id = Number(postId);

  if (!isBoardCategory(decoded) || !Number.isInteger(id)) {
    return (
      <Card>
        <EmptyState title="없는 주소입니다" />
      </Card>
    );
  }

  return <BoardPost category={decoded} postId={id} />;
}

function BoardPost({ category, postId }: { category: BoardCategory; postId: number }) {
  const navigate = useNavigate();
  const { me } = useMe();
  const base = `/boards/${encodeURIComponent(category)}/${postId}`;
  const listPath = `/boards/${category}`;

  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const post = useApi(async () => {
    try {
      const response = await http.get<PostDetail>(base);
      return response.data;
    } catch (caught) {
      throw new Error(statusOf(caught) === 404 ? GONE : toMessage(caught));
    }
  }, [base]);

  const remove = useApiAction(async () => {
    await http.delete(base);
    return true as const;
  });

  const data = post.data;
  const canEdit = !!data?.is_mine;
  const canDelete = !!data && (data.is_mine || canModerateBoard(me));

  if (post.loading) {
    return <Loading label="글을 불러오는 중…" />;
  }

  if (post.error || !data) {
    const gone = post.error === GONE;
    return gone ? (
      <Card>
        <EmptyState
          title="글을 열 수 없습니다"
          description={GONE}
          action={
            <Button variant="primary" onClick={() => navigate(listPath)}>
              목록으로
            </Button>
          }
        />
      </Card>
    ) : (
      <ErrorState description={post.error ?? undefined} onRetry={post.reload} />
    );
  }

  return (
    <>
      <div className="ui-stack cm-measure">
        <Card
          title={data.title}
          aside={
            <>
              {category} · {data.author_name} · {formatStamp(data.created_at)}
              {data.updated_at && ` · ${formatStamp(data.updated_at)} 수정`}
              {data.course_week &&
                ` · ${data.course_week.course_name} ${data.course_week.week_no}주차`}
            </>
          }
          actions={
            editing || !(canEdit || canDelete) ? undefined : (
              <>
                {canEdit && (
                  <Button size="sm" onClick={() => setEditing(true)}>
                    수정
                  </Button>
                )}
                {canDelete && (
                  <Button size="sm" variant="danger" onClick={() => setConfirmDelete(true)}>
                    삭제
                  </Button>
                )}
              </>
            )
          }
        >
          {(data.is_secret || !data.is_published) && (
            <p className="ui-row cm-flags">
              {data.is_secret && <Badge tone="neutral">비밀글</Badge>}
              {!data.is_published && <Badge tone="warning">미게시</Badge>}
            </p>
          )}

          {editing ? (
            <EditForm
              base={base}
              post={data}
              onCancel={() => setEditing(false)}
              onSaved={async () => {
                setEditing(false);
                await post.reload();
              }}
            />
          ) : (
            <p className="cm-prose">{data.body}</p>
          )}
        </Card>

        <Comments base={base} post={data} onChanged={post.reload} />
      </div>

      <Modal
        open={confirmDelete}
        onClose={() => {
          remove.clearError();
          setConfirmDelete(false);
        }}
        title="이 글을 지울까요?"
        footer={
          <>
            <Button
              onClick={() => {
                remove.clearError();
                setConfirmDelete(false);
              }}
            >
              그대로 두기
            </Button>
            <Button
              variant="danger"
              loading={remove.pending}
              onClick={async () => {
                const done = await remove.run();
                if (done) navigate(listPath, { replace: true });
              }}
            >
              지우기
            </Button>
          </>
        }
      >
        {/* 모달 본문은 block 이라 형제끼리 붙는다 — 오류줄이 뜨면 문장과 맞닿는다. */}
        <div className="ui-stack ui-stack--sm">
          {remove.error && <Alert tone="danger">{remove.error}</Alert>}
          <p>지운 글과 댓글은 되돌릴 수 없습니다. 「{data.title}」을(를) 지웁니다.</p>
        </div>
      </Modal>
    </>
  );
}

/** 본문 수정 — 카드 안에서 그대로 편집한다(모달로 옮기면 본문이 좁아진다). */
function EditForm({
  base,
  post,
  onCancel,
  onSaved,
}: {
  base: string;
  post: PostDetail;
  onCancel: () => void;
  onSaved: () => void | Promise<void>;
}) {
  const [title, setTitle] = useState(post.title);
  const [body, setBody] = useState(post.body);
  const [titleError, setTitleError] = useState<string | null>(null);
  const [bodyError, setBodyError] = useState<string | null>(null);

  const save = useApiAction(async (payload: { title: string; body: string }) => {
    await http.patch(base, payload);
    return true as const;
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = title.trim();
    setTitleError(trimmed ? null : "제목을 입력해 주세요.");
    setBodyError(body.trim() ? null : "내용을 입력해 주세요.");
    if (!trimmed || !body.trim()) return;
    const done = await save.run({ title: trimmed, body });
    if (done) await onSaved();
  };

  return (
    <form onSubmit={submit} noValidate className="ui-stack ui-stack--sm">
      {save.error && <Alert tone="danger">{save.error}</Alert>}

      <Field label="제목" error={titleError} required>
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

      <Field label="내용" error={bodyError} required>
        {(props) => (
          <Textarea
            {...props}
            rows={10}
            value={body}
            onChange={(event) => {
              setBody(event.target.value);
              if (bodyError) setBodyError(null);
            }}
          />
        )}
      </Field>

      <div className="ui-row">
        <Button type="submit" variant="primary" loading={save.pending}>
          저장
        </Button>
        <Button onClick={onCancel}>취소</Button>
      </div>
    </form>
  );
}

/** 댓글 — 글을 볼 수 있는 사람은 누구나 쓸 수 있다(서버 규칙과 동일). */
function Comments({
  base,
  post,
  onChanged,
}: {
  base: string;
  post: PostDetail;
  onChanged: () => Promise<void>;
}) {
  const { me } = useMe();
  const [body, setBody] = useState("");
  const [bodyError, setBodyError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);
  const moderator = canModerateBoard(me);

  const add = useApiAction(async (text: string) => {
    await http.post(`${base}/comments`, { body: text });
    return true as const;
  });

  const drop = useApiAction(async (commentId: number) => {
    await http.delete(`${base}/comments/${commentId}`);
    return true as const;
  });

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!body.trim()) {
      setBodyError("댓글 내용을 입력해 주세요.");
      return;
    }
    const done = await add.run(body);
    if (!done) return;
    setBody("");
    setBodyError(null);
    await onChanged();
  };

  const label = post.category === "질답" ? "답변" : "댓글";

  return (
    <Card
      title={`${label} ${post.comments.length}`}
      padding="none"
      className="cm-clip"
    >
      {post.comments.length === 0 ? (
        <EmptyState
          title={post.category === "질답" ? "아직 답변이 없습니다" : "아직 댓글이 없습니다"}
        />
      ) : (
        <ul className="cm-comments">
          {post.comments.map((comment) => (
            <li key={comment.comment_id}>
              <CommentItem
                comment={comment}
                canDelete={comment.is_mine || moderator}
                confirming={confirming === comment.comment_id}
                pending={drop.pending}
                onAskDelete={() => {
                  drop.clearError();
                  setConfirming(comment.comment_id);
                }}
                onCancelDelete={() => setConfirming(null)}
                onConfirmDelete={async () => {
                  const done = await drop.run(comment.comment_id);
                  setConfirming(null);
                  if (done) await onChanged();
                }}
              />
            </li>
          ))}
        </ul>
      )}

      <form onSubmit={submit} noValidate className="cm-composer">
        {add.error && <Alert tone="danger">{add.error}</Alert>}
        {drop.error && <Alert tone="danger">{drop.error}</Alert>}
        <Field
          label={post.category === "질답" ? "답변·추가 질문 쓰기" : "댓글 쓰기"}
          error={bodyError}
        >
          {(props) => (
            <Textarea
              {...props}
              rows={3}
              value={body}
              onChange={(event) => {
                setBody(event.target.value);
                if (bodyError) setBodyError(null);
              }}
            />
          )}
        </Field>
        <div className="cm-composer__row">
          <Button type="submit" variant="primary" loading={add.pending}>
            등록
          </Button>
        </div>
      </form>
    </Card>
  );
}

function CommentItem({
  comment,
  canDelete,
  confirming,
  pending,
  onAskDelete,
  onCancelDelete,
  onConfirmDelete,
}: {
  comment: CommentRow;
  canDelete: boolean;
  confirming: boolean;
  pending: boolean;
  onAskDelete: () => void;
  onCancelDelete: () => void;
  onConfirmDelete: () => void;
}) {
  const isStaffAuthor = STAFF_ROLE_LABELS.includes(comment.author_role);
  return (
    <article className="cm-comment">
      <header className="cm-comment__head">
        <span className="cm-comment__author">{comment.author_name}</span>
        {isStaffAuthor && <Badge tone="accent">{comment.author_role}</Badge>}
        <span>{formatStamp(comment.created_at)}</span>
        {canDelete && (
          <span className="cm-comment__tail">
            {confirming ? (
              <>
                <span className="cm-comment__confirm">지우면 되돌릴 수 없습니다.</span>
                <Button size="sm" variant="danger" loading={pending} onClick={onConfirmDelete}>
                  지우기
                </Button>
                <Button size="sm" variant="ghost" onClick={onCancelDelete}>
                  취소
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" onClick={onAskDelete}>
                삭제
              </Button>
            )}
          </span>
        )}
      </header>
      <p className="cm-prose">{comment.body}</p>
    </article>
  );
}
