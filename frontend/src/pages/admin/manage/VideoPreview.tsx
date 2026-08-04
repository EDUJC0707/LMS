/**
 * 관리자 미리보기 — 등록한 영상이 실제로 나오는지 그 자리에서 확인한다.
 *
 *   GET /api/admin/videos/{id}/preview
 *
 * 학생 재생 API 는 `IsStudent` + 활성 권한 이중 게이트라 직원 계정으로는 절대
 * 열리지 않는다. 그래서 재생 ID 를 잘못 넣어도 목록에는 값이 찍혀 있어 멀쩡해
 * 보이고, **학생이 "영상 안 나와요" 할 때** 알게 됐다.
 * (2026-08-04 실제로 Asset ID 를 Playback ID 자리에 넣어 한 번 헛돌았다.)
 *
 * **`준비중` 도 재생된다.** 공개 전에 확인하는 것이 이 화면의 목적이라
 * 상태·권한을 보지 않는다 — 접근 통제는 서버의 `영상지급관리` 게이트가 진다.
 *
 * 워터마크는 **직원 본인** 이름으로 찍힌다. 학생 것으로 찍으면 이 화면이
 * 유출됐을 때 엉뚱한 학생이 지목된다.
 */
import MuxPlayer from "@mux/mux-player-react";

import { http, useApi } from "../../../api";
import { ErrorState, Loading, Modal } from "../../../components";
import "../../student/video.css";

interface PreviewPayload {
  video: {
    video_id: number;
    title: string;
    provider: string | null;
    external_ref: string | null;
    tokens: { playback?: string; thumbnail?: string; storyboard?: string };
  };
  watermark: string;
  viewer_id: string;
}

interface Props {
  videoId: number;
  title: string;
  onClose: () => void;
}

export function VideoPreview({ videoId, title, onClose }: Props) {
  const preview = useApi(
    () =>
      http
        .get<PreviewPayload>(`/admin/videos/${videoId}/preview`)
        .then((r) => r.data),
    [videoId],
  );

  return (
    <Modal open onClose={onClose} title={title} wide>
      {preview.initialLoading && <Loading label="영상을 불러오는 중…" />}
      {preview.error && (
        <ErrorState description={preview.error} onRetry={preview.reload} />
      )}
      {preview.data && (
        <div className="vd-stage">
          <MuxPlayer
            className="vd-player"
            streamType="on-demand"
            playbackId={preview.data.video.external_ref ?? ""}
            tokens={preview.data.video.tokens}
            metadata={{
              video_title: preview.data.video.title,
              viewer_user_id: preview.data.viewer_id,
            }}
            autoPlay
          >
            {/* 플레이어 안쪽 — 전체화면에서도 남는다(student/video.css) */}
            <div className="vd-mark">
              <span className="vd-mark__text">{preview.data.watermark}</span>
            </div>
          </MuxPlayer>
        </div>
      )}
    </Modal>
  );
}
