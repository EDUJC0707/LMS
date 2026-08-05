/**
 * 재생기 조작 문구를 한국어로 — media-chrome i18n 등록.
 *
 * Mux Player 는 media-chrome 위에 올라가 있고, 재생·음소거·화질 같은 조작
 * 버튼의 **hover 툴팁과 스크린리더 라벨이 전부 영어**로 나온다
 * (`Play` · `Seek backward` · `Enter fullscreen mode` …).
 * 학생·학부모가 쓰는 화면이라 그대로 두면 안 된다.
 *
 * media-chrome 4.19 는 de·en·es·fr·pt·zh 만 싣고 **한국어가 없다.**
 * 대신 `addTranslation(코드, 사전)` 공개 API 가 있어 우리가 넣는다.
 *
 * ## `{...}` 자리는 그대로 둔다
 *
 * 값이 런타임에 꽂히는 자리다(`seek back {seekOffset} seconds`).
 * 번역하면서 지우면 "10초 뒤로" 가 "초 뒤로" 가 된다.
 *
 * ## 여기서 못 고치는 것
 *
 * **재생 실패 메시지는 Mux Player 자신의 문구**라 이 사전으로 안 바뀐다
 * ("The video URL or playback-token are formatted with incorrect information").
 * playback-core 가 조회 함수만 내보내고 등록 API 를 안 열어 뒀다(2026-08-04 확인).
 * 그건 우리가 `onError` 로 받아 직접 그려야 한다 — 아직 안 했다.
 *
 * 앱 시작 시 한 번만 실행되면 된다(main.tsx 에서 import).
 */
import type { TranslateDictionary } from "media-chrome/dist/lang/en.js";
import { addTranslation, setLanguage } from "media-chrome/dist/utils/i18n.js";

/** media-chrome 4.19 의 en 사전 키를 그대로 따른다(키가 다르면 조용히 영어로 남는다). */
const Ko: TranslateDictionary = {
  // ── 조작 버튼 (툴팁) ────────────────────────────────────────────────
  Play: "재생",
  Pause: "일시정지",
  Mute: "음소거",
  Unmute: "음소거 해제",
  Loop: "반복",
  "Seek backward": "뒤로",
  "Seek forward": "앞으로",
  "Enter fullscreen mode": "전체화면",
  "Exit fullscreen mode": "전체화면 나가기",
  "Enter picture in picture mode": "작은 화면",
  "Exit picture in picture mode": "작은 화면 끄기",
  "Start airplay": "AirPlay 시작",
  "Stop airplay": "AirPlay 중지",
  "Start casting": "캐스트 시작",
  "Stop casting": "캐스트 중지",
  Captions: "자막",
  "Enable captions": "자막 켜기",
  "Disable captions": "자막 끄기",
  Audio: "오디오",
  Quality: "화질",
  "Playback rate": "재생 속도",
  "Playback rate {playbackRate}": "재생 속도 {playbackRate}",
  Settings: "설정",
  Auto: "자동",
  Off: "끔",

  // ── 스크린리더 라벨 (소문자 키가 따로 있다) ─────────────────────────
  "audio player": "오디오 재생기",
  "video player": "영상 재생기",
  volume: "음량",
  seek: "탐색",
  "closed captions": "자막",
  "current playback rate": "현재 재생 속도",
  "playback time": "재생 시간",
  "media loading": "불러오는 중",
  settings: "설정",
  "audio tracks": "오디오 트랙",
  quality: "화질",
  play: "재생",
  pause: "일시정지",
  mute: "음소거",
  unmute: "음소거 해제",
  live: "실시간",
  "start airplay": "AirPlay 시작",
  "stop airplay": "AirPlay 중지",
  "start casting": "캐스트 시작",
  "stop casting": "캐스트 중지",
  "enter fullscreen mode": "전체화면",
  "exit fullscreen mode": "전체화면 나가기",
  "enter picture in picture mode": "작은 화면",
  "exit picture in picture mode": "작은 화면 끄기",
  "seek to live": "실시간으로 이동",
  "playing live": "실시간 재생 중",
  "seek back {seekOffset} seconds": "{seekOffset}초 뒤로",
  "seek forward {seekOffset} seconds": "{seekOffset}초 앞으로",
  "video not loaded, unknown time.": "영상을 불러오지 못했습니다.",
  "chapter: {chapterName}": "챕터: {chapterName}",
  "{time} remaining": "{time} 남음",
  "{currentTime} of {totalTime}": "{totalTime} 중 {currentTime}",

  // ── 오류 (media-chrome 쪽) ─────────────────────────────────────────
  "Network Error": "네트워크 오류",
  "Decode Error": "재생 오류",
  "Source Not Supported": "지원하지 않는 형식",
  "Encryption Error": "복호화 오류",
  "A network error caused the media download to fail.":
    "네트워크 문제로 영상을 받지 못했습니다.",
  "A media error caused playback to be aborted. The media could be corrupt or your browser does not support this format.":
    "영상을 재생하지 못했습니다. 파일이 손상됐거나 브라우저가 이 형식을 지원하지 않습니다.",
  "An unsupported error occurred. The server or network failed, or your browser does not support this format.":
    "재생에 실패했습니다. 서버·네트워크 문제이거나 브라우저가 이 형식을 지원하지 않습니다.",
  "The media is encrypted and there are no keys to decrypt it.":
    "영상이 암호화돼 있고 복호화 키가 없습니다.",

  // ── 시간 단위 ──────────────────────────────────────────────────────
  hour: "시간",
  hours: "시간",
  minute: "분",
  minutes: "분",
  second: "초",
  seconds: "초",
};

addTranslation("ko", Ko);
setLanguage("ko");
