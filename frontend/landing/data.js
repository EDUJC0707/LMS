/**
 * 랜딩 콘텐츠. 화면과 분리해 여기 모은다 — 문구를 고칠 때 마크업을 건드리지 않게.
 *
 * 커리큘럼은 1차에 정적으로 둔다. LMS의 course_weeks는 PRD §4(시작된 주차까지만
 * 공개·경쟁사 차단)에 묶여 있어 비로그인 랜딩에 그대로 쓸 수 없다.
 * 정오표도 지금은 정적이며, 나중에 boards의 정오표 카테고리를 공개 API로
 * 읽어오는 자리다(SPEC §7-2).
 */

/* 히어로 배경 후보. 디버그 패널(⌘⌥D) **배경** 그룹에 그대로 뜬다.
   원본 PNG(41MB, 최대 4000x3271)는 그대로 못 쓴다 — 폭 2560 webp 로 구웠다(1.0MB).
   배경은 cover 로 깔리고 opacity .45 로 눌리므로 더 키워도 안 보이고 무게만 는다.
   원본은 같은 폴더에 남겨 둔다(다시 구울 일이 있으므로).

   **밝기 주의** — 좌측 1/3 이 헤드라인 자리다. .45 를 적용한 좌측 평균 휘도:
     carina 26 · catseye 17 · ngc1333 46
   헤드라인 1행이 110 이므로 ngc1333 은 빡빡하다. 쓰려면 밝기를 더 눌러야 한다.

   영상 둘은 원본 24.9초(컷 없는 단일 샷, 별이 블랙홀에 찢겨 들어감)에서 잘랐다.
     tde-dark   0~6초. 가장 어둡고(좌45% 휘도 5.0) 가장 느리다(모션 0.52).
                다만 밝은 별 덩어리가 x21~52% · y33~53% 에 있어 **헤드라인과 겹친다**.
                루프에 크로스페이드 15프레임을 넣었는데, 시작·끝의 별 위치가 달라
                이음새에서 별이 0.6초간 절반쯤 어두워진다(피할 방법 없음 — 4~8초
                창 460개를 다 훑었다).
     tde-nebula 14~19초. 확산형 성운이라 **이음새가 거의 완벽하다**. 대신 2.5배 밝고
                3배 빠르다. 좌상단 성운 기둥이 헤드라인 윗줄에 얹힐 수 있다.
   확장자로 사진/영상을 가른다(.mp4 면 영상). */
export const SPACE = [
  { key: 'carina',  label: '사진 · 카리나 성운',        src: 'assets/space/carina.webp' },
  { key: 'catseye', label: '사진 · 고양이눈 성운',      src: 'assets/space/catseye.webp' },
  { key: 'ngc1333', label: '사진 · NGC 1333',           src: 'assets/space/ngc1333.webp' },
  { key: 'tdeDark', label: '영상 · 별이 빨려듦 (6초)',  src: 'assets/space/tde-dark.mp4' },
  { key: 'tdeNeb',  label: '영상 · 성운 (5초)',         src: 'assets/space/tde-nebula.mp4' },
];

/* 히어로에 숨던 모티프 10종 — **2026-07-29 폐기.** 다른 비주얼로 교체한다.
   화면은 더 이상 이걸 읽지 않는다(index.html 이 mountField 에 빈 목록을 넘긴다).
   되살릴 때를 위해 이름과 경로만 남긴다. 왜 있었고 무엇을 배웠는지는 SPEC.md §4-옛.
   에셋은 assets/motifs/ 에 그대로 있고 굽기 전 원본은 local/assets/motifs_accent/. */
export const RETIRED_UNITS = [
  { key: 'atom', asset: 'assets/motifs/atom.webp' },
  { key: 'dna', asset: 'assets/motifs/dna.webp' },
  { key: 'chromosome', asset: 'assets/motifs/chromosome.webp' },
  { key: 'mitochondria', asset: 'assets/motifs/mitochondria.webp' },
  { key: 'chloroplast', asset: 'assets/motifs/chloroplast.webp' },
  { key: 'synapse', asset: 'assets/motifs/synapse.webp' },
  { key: 'population', asset: 'assets/motifs/population.webp' },
  { key: 'element', asset: 'assets/motifs/element.webp' },
  { key: 'tectonics', asset: 'assets/motifs/tectonics.webp' },
  { key: 'universe', asset: 'assets/motifs/universe.webp' },
];
/**
 * 커리큘럼 — 4단계 × 2트랙.
 * 통합과학은 2028이 첫 시행이라 수능 기출이 없어 `기출분석` 단계를 두지 않았다.
 * 가격·강의수·수강기간은 넣지 않는다(업계 불문율, SPEC §7-1).
 */
export const CURRICULUM = {
  naesin: [
    {
      stage: '입문', badge: '',
      title: '중등 과학에서 통합과학으로 건너오는 구간',
      units: ['과학의 기초'],
    },
    {
      stage: '개념완성', badge: '필수',
      title: '철두철미 완자 통합과학 — 물화생지 전 영역 개념의 완결',
      units: ['물질과 규칙성', '시스템과 상호작용', '변화와 다양성', '환경과 에너지'],
    },
    {
      stage: '문제풀이', badge: '',
      title: '로직N제 — 개념을 문항으로 바꾸는 훈련',
      units: ['물질과 규칙성', '시스템과 상호작용'],
    },
    {
      stage: '직전대비', badge: '',
      title: '학교별 기출 분석과 내신 마무리',
      units: [],
    },
  ],
  suneung: [
    {
      stage: '입문', badge: '',
      title: '수능 통합과학이 무엇을 묻는 시험인지부터',
      units: ['과학의 기초'],
    },
    {
      stage: '개념완성', badge: '필수',
      title: '철두철미 개념완성 — 6개 대단원을 빠짐없이',
      units: ['물질과 규칙성', '시스템과 상호작용', '변화와 다양성', '환경과 에너지', '과학과 미래 사회'],
    },
    {
      stage: '문제풀이', badge: '',
      title: '자료 분석의 기술 · 만점시퀀스 — 40분 안에 25문항',
      units: ['시스템과 상호작용', '변화와 다양성', '환경과 에너지'],
    },
    {
      stage: '직전대비', badge: '',
      title: '파이널 — 시험장에서 쓸 것만 남긴다',
      units: [],
    },
  ],
};

/**
 * 교재 정오표.
 * 날짜는 사람이 제목에 박지 않는다 — created/updated를 데이터로 두고 화면이 읽는다.
 * 정렬은 최종 수정일 내림차순 하나뿐이고 정렬 UI를 주지 않는다(그게 옳은 정렬이므로).
 * 비어 있으면 숨기지 말고 빈 상태로 보여준다 — 숨기면 "없는 것"과 "안 하는 것"이
 * 구분되지 않는다.
 */
export const ERRATA = [];
