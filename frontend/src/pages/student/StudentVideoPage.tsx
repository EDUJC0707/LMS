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
 * ## 워터마크는 플레이어 **안쪽**이다
 *
 * 바깥 래퍼에 얹으면 전체화면에서 사라진다(플레이어 요소만 전체화면이 되므로).
 * 사라지면 그게 곧 우회 방법이라 `mux-player` 의 자식으로 넣는다.
 * 값은 서버가 완성해서 내린 문자열을 **그대로** 그린다 — 프런트가 조립하면
 * 개발자도구로 남의 이름·다른 날짜로 바꿔치기할 수 있다(playback.py 계약).
 */
import MuxPlayer from "@mux/mux-player-react";
import { useState } from "react";

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

/**
 * 실계정 전환 지점 — 여기만 갈아 끼우면 된다.
 *
 * Mux 계정이 아직 없다(결제를 런칭 직전으로 미룸 — docs/decisions.md §3).
 * 서버가 내리는 `provider`·`external_ref` 가 채워지면 그 값을 쓰고, 비어 있는
 * 동안은 Mux 공개 데모 재생 ID 로 화면을 확인한다.
 */
const DEMO_PLAYBACK_ID = "qxb01i6T202018GFS02vp9RIe01icTcDCjVzQpmaB00CUisJ4";

/** 시드가 넣는 가짜 참조의 접두 — 실제 Mux 값이 아니라는 표시(seed_demo.py). */
const SEED_REF_PREFIX = "seed-";

/** 데모로 떨어지는가 — 참조가 없거나 시드용 가짜 값일 때. */
function isDemo(video: PlaybackVideo): boolean {
  return (
    video.provider !== "mux" ||
    !video.external_ref ||
    video.external_ref.startsWith(SEED_REF_PREFIX)
  );
}

function playbackIdOf(video: PlaybackVideo): string {
  // 시드 데이터는 재생될 수 없는 값이라 데모로 떨어뜨린다. 실제 참조는 그대로 쓴다 —
  // 여기서 관대하게 폴백하면 **잘못 적은 참조도 데모가 재생돼** 오류가 묻힌다.
  return isDemo(video) ? DEMO_PLAYBACK_ID : video.external_ref!;
}

/**
 * 데모로 떨어질 때는 토큰을 **빼야 한다.**
 *
 * 서버는 `external_ref`(예: `seed-1-1`)로 서명하는데 재생기는 그 값일 때 데모
 * 영상을 튼다. 서명 대상과 재생 대상이 어긋난 토큰을 넘기면 Mux 가
 * "playback-token formatted with incorrect information" 으로 거부한다
 * (2026-08-04 실측 — 시드 영상이 전부 이걸로 죽었다).
 * 데모 자산은 공개라 토큰이 필요 없다.
 */
function tokensOf(playing: Playback): Playback["video"]["tokens"] {
  return isDemo(playing.video) ? {} : playing.video.tokens;
}

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

export default function StudentVideoPage() {
  const list = useApi(
    () => http.get<{ videos: VideoRow[] }>("/student/videos").then((r) => r.data.videos),
    [],
  );
  const [playing, setPlaying] = useState<Playback | null>(null);

  // 재생 정보는 누르는 순간 받는다(파일 머리말 참조).
  const open = useApiAction(async (videoId: number) => {
    const res = await http.get<Playback>(`/student/videos/${videoId}/playback`);
    setPlaying(res.data);
    return true;
  });

  if (list.initialLoading) return <Loading label="복습영상을 불러오는 중…" />;
  if (list.error) return <ErrorState description={list.error} onRetry={list.reload} />;

  const rows = list.data ?? [];

  if (playing) {
    return (
      <div className="ui-stack">
        <Button variant="ghost" onClick={() => setPlaying(null)}>
          목록으로
        </Button>

        <Card
          title={playing.video.title}
          aside={`${playing.video.week_no}주차`}
          padding="none"
        >
          <div className="vd-stage">
            <MuxPlayer
              className="vd-player"
              streamType="on-demand"
              playbackId={playbackIdOf(playing.video)}
              tokens={tokensOf(playing)}
              metadata={{
                video_title: playing.video.title,
                // 유출 시 Mux Data 에서 "누가 봤나"를 되짚는 축. 워터마크가
                // 유출본에 찍히는 추적이라면 이건 재생 기록 쪽이다.
                viewer_user_id: playing.viewer_id,
              }}
              autoPlay
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
                loading={open.pending}
                onClick={() => void open.run(row.video_id)}
              >
                재생
              </Button>
            ),
          },
        ]}
      />
    </Card>
  );
}
