/**
 * 랜딩 콘텐츠. 화면과 분리해 여기 모은다 — 문구를 고칠 때 마크업을 건드리지 않게.
 *
 * 커리큘럼은 1차에 정적으로 둔다. LMS의 course_weeks는 PRD §4(시작된 주차까지만
 * 공개·경쟁사 차단)에 묶여 있어 비로그인 랜딩에 그대로 쓸 수 없다.
 * 정오표도 지금은 정적이며, 나중에 boards의 정오표 카테고리를 공개 API로
 * 읽어오는 자리다(SPEC §7-2).
 */

/* 히어로에 숨는 것들. 순서가 곧 화면 배치 순서다(field.js LAYOUT과 짝).
   accent 계열을 쓴다 — 같은 개념의 base 버전은 검정에서 흐릿한 유리 덩어리가 되는데,
   accent 는 형태가 또렷하고 색이 남는다(미토콘드리아 크리스타·나선은하·지구 판 경계). */
export const UNITS = [
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
