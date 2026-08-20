/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** vite 프록시가 넘길 백엔드. 개발 전용이고 번들에는 안 들어간다. */
  readonly VITE_API_TARGET?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
