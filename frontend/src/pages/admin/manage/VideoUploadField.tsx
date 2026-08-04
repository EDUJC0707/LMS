/**
 * 영상 파일 업로드 — **완성돼 있지만 화면에 연결돼 있지 않다**(2026-08-04 사용자 지시).
 *
 * 서버 자리(`POST /api/admin/videos/uploads`)도, 이 컴포넌트도 실제 Mux 로 왕복
 * 확인까지 끝났다. 다만 **학원 회선에서 3~4GB 전송이 견딜 만한지 재보기 전까지**
 * 조교에게 내놓지 않는다.
 *
 * ## 연결하는 법 (두 줄)
 *
 * `VideoManagePage` 의 모달 안에 넣는다:
 *
 *     import { VideoUploadField } from "./VideoUploadField";
 *     // 모달 <div className="ui-stack ui-stack--md"> 안, 등록 모드에서만
 *     {!editing && <VideoUploadField form={form} onDone={() => { setOpen(false); void list.reload(); }} />}
 *
 * 지우지 말 것 — 되살리는 비용이 지금 두는 비용보다 크다.
 *
 * ## 파일은 우리 서버를 지나지 않는다
 *
 *     조교 PC ──(3.5GB)──> Mux
 *        우리 서버는 일회용 URL 하나 발급하고 빠진다
 *
 * 원본이 GB 단위라 우리 서버를 통과시키면 대역폭·타임아웃·디스크가 전부 문제가
 * 되는데 그 셋이 통째로 사라진다. UpChunk 가 조각내 올리고 **끊기면 이어서 재개**
 * 한다(탭을 닫으면 처음부터다 — 그게 이 기능을 보류한 이유이기도 하다).
 *
 * ## 등급·해상도·정책은 서버가 정한다
 *
 * `provider`·`external_ref` 를 여기서 보내지 않는다. 우리가 Mux 로 올리는 중이라
 * provider 는 정해져 있고 참조 ID 는 인코딩이 끝나야 생긴다. 등급(premium)·
 * 해상도(1080p)·정책(signed)도 서버에 박혀 있다 — **자산 생성 시 확정이라
 * 틀리면 재인코딩**이고, 실제로 손으로 고르다 두 번 헛돌았다.
 */
import * as UpChunk from "@mux/upchunk";
import { useRef, useState } from "react";

import { http, useApiAction } from "../../../api";
import { Button, ErrorState, Field, Input } from "../../../components";

/** 등록 폼에서 업로드가 쓰는 값만. 페이지의 FormState 가 이것을 만족한다. */
export interface UploadMeta {
  title: string;
  course_week_id: string;
  sequence_no: string;
}

interface Props {
  form: UploadMeta;
  /** 전송이 끝났을 때 — 보통 모달을 닫고 목록을 다시 읽는다. */
  onDone: () => void;
}

export function VideoUploadField({ form, onDone }: Props) {
  /** 진행률 0~100. null 이면 업로드 중이 아니다. */
  const [progress, setProgress] = useState<number | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // 폼 값을 **인자로 받는다.** useApiAction 은 action 을 의존성에서 빼 첫 렌더의
  // 클로저를 붙들기 때문에(api/useApi.ts), 클로저로 읽으면 항상 빈 폼이 나간다
  // (2026-08-04 실측 · 2026-07-29 클리닉에서도 같은 함정).
  const upload = useApiAction(async (meta: UploadMeta, file: File) => {
    const num = (raw: string) => (raw.trim() === "" ? null : Number(raw));
    const res = await http.post<{ video: { video_id: number }; upload_url: string }>(
      "/admin/videos/uploads",
      {
        title: meta.title.trim(),
        course_week_id: num(meta.course_week_id),
        sequence_no: num(meta.sequence_no),
      },
    );
    const { video, upload_url } = res.data;
    setProgress(0);
    await new Promise<void>((resolve, reject) => {
      const chunked = UpChunk.createUpload({ endpoint: upload_url, file });
      chunked.on("progress", (e) => setProgress(Math.round(e.detail)));
      chunked.on("error", (e) => reject(new Error(e.detail.message)));
      chunked.on("success", () => resolve());
    });
    setProgress(null);
    onDone();
    // 인코딩은 전송 뒤에도 몇 분 더 걸린다. 관리 목록이 열릴 때 서버가 확인하므로
    // 여기서 기다리지 않는다 — 조교를 붙잡아 둘 이유가 없다.
    void http.post(`/admin/videos/${video.video_id}/sync`).catch(() => {});
    return true;
  });

  return (
    <>
      {upload.error && (
        <ErrorState description={upload.error} onRetry={upload.clearError} />
      )}

      <Field label="영상 파일">
        {(props) => (
          <Input
            {...props}
            ref={fileRef}
            type="file"
            accept="video/*"
            disabled={progress !== null}
          />
        )}
      </Field>

      {progress !== null && (
        <progress className="pm-progress" value={progress} max={100}>
          {progress}%
        </progress>
      )}

      <Button
        loading={upload.pending}
        onClick={() => {
          const file = fileRef.current?.files?.[0];
          if (file) void upload.run(form, file);
        }}
      >
        올리기
      </Button>
    </>
  );
}
