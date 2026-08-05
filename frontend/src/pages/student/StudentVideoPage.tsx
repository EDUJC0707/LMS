/**
 * /student/videos — 복습영상 목록과 재생.
 *
 *   GET /api/student/videos                    지금 볼 수 있는 영상
 *   GET /api/student/videos/{id}/playback      재생 정보 + 워터마크
 *
 * ## 재생 정보를 목록이 아니라 **재생 누를 때** 받는다
 *
 * 워터마크의 시청 날짜가 서버 시각으로 찍히므로, 목록을 열 때 미리 받아 두면
 * 밤 11시 59분에 열어 놓고 자정 넘겨 재생한 학생의 워터마크가 **전날 날짜**로
 * 남는다. 재생 시점에 받으면 그 값이 곧 재생 시작 시각이 된다(2026-07-30 확정 —
 * "그냥 play버튼 눌렀을때로", 재생 중 갱신은 하지 않는다).
 *
 * 덤으로 권한 검사도 재생 시점에 걸린다 — 목록만 열어 두고 몇 시간 뒤 재생하는
 * 경우에도 7일 만료가 제대로 잡힌다.
 *
 * ## 자동재생하지 않는다
 *
 * 목록의 [보기] 는 **여는 것**이고 재생은 학생이 플레이어에서 시작한다.
 * 두 가지 이유다 — ① 잘못 누른 사람에게도 재생이 시작되면 그게 그대로 요금이다
 * (Mux 는 "본 시간" 이 아니라 **"내려간 시간"** 으로 과금한다) ② 목록 버튼이
 * `재생` 인데 실제 재생은 다음 화면에서 일어나면 이름과 동작이 어긋난다.
 *
 * ## 재생 참조는 서버가 정한다
 *
 * 시드 데이터는 재생될 수 없는 가짜 참조(`seed-*`)를 갖는데, 그 대체를 **서버가**
 * 한다(playback.resolve_ref). 여기서 갈아치우면 서명은 원래 값 앞으로 나가고
 * 재생은 다른 자산이 되어 Mux 가 거부한다 — 실제로 그렇게 죽었다(2026-08-04).
 * 프런트는 서버가 준 `external_ref` 와 `tokens` 를 **그대로** 쓴다.
 *
 * ## 워터마크가 지워지면 기록한다
 *
 * 오버레이는 개발자도구 한 줄로 지워진다(`.vd-mark` 를 remove). 서버측 굽기를
 * 파는 업체가 우리 규모에 없어 **원리상 막을 수 없다**(2026-08-04 전수조사).
 * 그래서 막는 대신 적는다 — 실수로 지울 수 있는 물건이 아니므로 기록 한 줄이
 * 곧 의도의 증거다(WatermarkTamper 모델).
 *
 * 지워지면 **다시 붙이고** 신고한다. 다시 붙이는 것은 우연·가벼운 제거를 되돌리고,
 * 신고는 작정한 쪽을 기록에 남긴다. **화면에는 아무 것도 알리지 않는다** —
 * 알리면 신고 요청부터 막는 법을 배우게 된다.
 *
 * ## 워터마크는 플레이어 **안쪽**이다
 *
 * 바깥 래퍼에 얹으면 전체화면에서 사라진다(플레이어 요소만 전체화면이 되므로).
 * 사라지면 그게 곧 우회 방법이라 `mux-player` 의 자식으로 넣는다.
 * 값은 서버가 완성해서 내린 문자열을 **그대로** 그린다 — 프런트가 조립하면
 * 개발자도구로 남의 이름·다른 날짜로 바꿔치기할 수 있다(playback.py 계약).
 */
import MuxPlayer from "@mux/mux-player-react";
import { useEffect, useRef, useState } from "react";

import { http, useApi, useApiAction } from "../../api";
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  Table,
} from "../../components";
import "./video.css";

interface VideoRow {
  video_id: number;
  title: string;
  sequence_no: number;
  duration_seconds: number | null;
  course_name: string | null;
  week_no: number | null;
  expires_at: string;
}

interface PlaybackVideo {
  video_id: number;
  title: string;
  provider: string | null;
  external_ref: string | null;
  /** 서명 정책 영상의 재생 토큰 — 서버가 개인키로 발급한다(playback.py). */
  tokens: { playback?: string; thumbnail?: string; storyboard?: string };
  course_name: string | null;
  week_no: number | null;
}

interface Playback {
  video: PlaybackVideo;
  watermark: string;
  /** Mux Data 시청자 축 — 실명이 아니라 학생 내부 번호다(playback.py). */
  viewer_id: string;
  expires_at: string;
}

/** "1800" → "30분". 없으면 빈 칸. */
function runtime(seconds: number | null): string {
  if (!seconds) return "—";
  const minutes = Math.round(seconds / 60);
  return `${minutes}분`;
}

function dayLabel(iso: string): string {
  const date = new Date(iso);
  return `${date.getMonth() + 1}월 ${date.getDate()}일`;
}

/**
 * 워터마크가 사라지면 되살리고 한 번 신고한다.
 *
 * 세션당 1회만 보낸다 — 되살리기가 다시 관찰을 부르므로 상한이 없으면
 * 무한 루프로 요청이 나간다.
 */
function useWatermarkGuard(
  stageRef: React.RefObject<HTMLDivElement>,
  playing: Playback | null,
) {
  const reported = useRef(false);
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage || !playing) return;
    reported.current = false;
    const observer = new MutationObserver(() => {
      if (stage.querySelector(".vd-mark")) return;
      const mark = document.createElement("div");
      mark.className = "vd-mark";
      const text = document.createElement("span");
      text.className = "vd-mark__text";
      text.textContent = playing.watermark;
      mark.appendChild(text);
      (stage.querySelector("mux-player") ?? stage).appendChild(mark);
      if (!reported.current) {
        reported.current = true;
        void http.post(`/student/videos/${playing.video.video_id}/tamper`).catch(() => {});
      }
    });
    observer.observe(stage, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [stageRef, playing]);
}

export default function StudentVideoPage() {
  const list = useApi(
    () => http.get<{ videos: VideoRow[] }>("/student/videos").then((r) => r.data.videos),
    [],
  );
  const [playing, setPlaying] = useState<Playback | null>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  useWatermarkGuard(stageRef, playing);

  /**
   * 지금 열고 있는 행 — 버튼의 로딩 표시가 **그 행에만** 걸리게 한다.
   *
   * `useApiAction` 의 `pending` 은 페이지에 하나뿐인 불리언이라 어느 행을 눌렀는지
   * 모른다. 그대로 `loading` 에 물리면 한 행을 눌러도 **모든 행이 함께 돌고**,
   * Button 이 `disabled={loading}` 이라 나머지 행이 잠긴다(2026-08-04 실측).
   */
  const [openingId, setOpeningId] = useState<number | null>(null);

  // 재생 정보는 누르는 순간 받는다(파일 머리말 참조).
  const open = useApiAction(async (videoId: number) => {
    setOpeningId(videoId);
    try {
      const res = await http.get<Playback>(`/student/videos/${videoId}/playback`);
      setPlaying(res.data);
      return true;
    } finally {
      setOpeningId(null);
    }
  });

  if (list.initialLoading) return <Loading label="복습영상을 불러오는 중…" />;
  if (list.error) return <ErrorState description={list.error} onRetry={list.reload} />;

  const rows = list.data ?? [];

  if (playing) {
    return (
      <div className="ui-stack">
        <Card
          title={
            <span className="vd-title">
              <button
                type="button"
                className="vd-back"
                onClick={() => setPlaying(null)}
                aria-label="목록으로"
              >
                {/* PageIcon 과 같은 결: viewBox 24 · stroke 1.7 · 둥근 끝 */}
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path
                    d="M14.5 5.5 8 12l6.5 6.5"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  />
                </svg>
              </button>
              {playing.video.title}
            </span>
          }
          aside={`${playing.video.week_no}주차`}
          padding="none"
        >
          <div className="vd-stage" ref={stageRef}>
            <MuxPlayer
              className="vd-player"
              streamType="on-demand"
              playbackId={playing.video.external_ref ?? ""}
              tokens={playing.video.tokens}
              metadata={{
                video_title: playing.video.title,
                // 유출 시 Mux Data 에서 "누가 봤나"를 되짚는 축. 워터마크가
                // 유출본에 찍히는 추적이라면 이건 재생 기록 쪽이다.
                viewer_user_id: playing.viewer_id,
              }}
            >
              {/* 플레이어 안쪽 — 전체화면에서도 남는다(파일 머리말 참조) */}
              <div className="vd-mark">
                <span className="vd-mark__text">{playing.watermark}</span>
              </div>
            </MuxPlayer>
          </div>
        </Card>
      </div>
    );
  }

  return (
    <Card title="복습영상" aside={`${rows.length}개`} padding="none">
      {open.error && (
        <div className="vd-alert">
          <ErrorState description={open.error} onRetry={open.clearError} />
        </div>
      )}
      <Table<VideoRow>
        rows={rows}
        rowKey={(row) => row.video_id}
        caption="복습영상 목록"
        empty={<EmptyState title="볼 수 있는 복습영상이 없습니다" />}
        columns={[
          {
            key: "week",
            header: "주차",
            numeric: true,
            width: "4.5rem",
            // 주차 없는 특강은 뒤로 — 빈 값이 위로 오면 목록 첫 화면이 어수선해진다
            sortValue: (row) => row.week_no ?? 9999,
            cell: (row) => (row.week_no === null ? "—" : `${row.week_no}주차`),
          },
          {
            key: "title",
            header: "제목",
            sortValue: (row) => row.title,
            cell: (row) => row.title,
          },
          {
            key: "runtime",
            header: "길이",
            numeric: true,
            width: "5rem",
            sortValue: (row) => row.duration_seconds ?? 0,
            cell: (row) => runtime(row.duration_seconds),
          },
          {
            key: "expires",
            header: "만료",
            numeric: true,
            width: "7rem",
            sortValue: (row) => row.expires_at,
            cell: (row) => dayLabel(row.expires_at),
          },
          {
            key: "play",
            header: "",
            width: "6rem",
            cell: (row) => (
              <Button
                size="sm"
                variant="primary"
                loading={openingId === row.video_id}
                onClick={() => void open.run(row.video_id)}
              >
                보기
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
