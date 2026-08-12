"""버킷 안 자리 — 업로드본이 어디에 놓이나.

경로를 **한 곳에서** 만든다. 예전에는 네 파일에 f-string 으로 흩어져 있었고,
시드 정리(`seed_demo`)가 지울 접두사를 손으로 따라 적고 있었다 — 한쪽만 고치면
지워지지 않는 쓰레기가 남는다.

## 짜임

    omr/scans/{시험}/{내용해시}.jpg     판독 대상 스캔 — **개인정보**
    omr/batches/{시험}/{uuid}.pdf       업로드 원본 — 판독 끝나면 지운다
    workbook/pages/{연}/{월}/{uuid}.ext 워크북 사진 — **개인정보**
    demo/…                              시드. 실제 데이터와 최상위에서 갈린다

두 가지를 노린다:

- **`demo/` 를 최상위로 뺀다.** 예전엔 `omr/demo/` 라 실제 스캔과 같은 가지에
  있었다. 시드를 지우려면 실제 것과 안 겹치는지 매번 따져야 했고, 접두사를
  하나 잘못 적으면 실물을 지운다. 이제 `demo/` 하나만 지우면 되고 그 아래에는
  실물이 있을 수 없다
- **개인정보가 든 자리를 접두사로 짚을 수 있다.** 폐기 정책은 아직 유예돼
  있지만(대표 2026-08-12), 걸 때가 오면 `omr/scans/` 와 `workbook/pages/`
  둘이다. 지금 갈라 두지 않으면 그때 파일을 하나씩 봐야 한다
"""
#: 시드가 만든 것 전부. `seed_demo` 가 이 하나만 지운다.
DEMO = "demo"


def omr_scan(exam_id, digest, suffix="jpg"):
    """판독 대상 스캔 한 장. 이름이 **내용 주소**라 같은 지면이면 같은 자리다."""
    return f"omr/scans/{exam_id}/{digest}.{suffix}"


def omr_batch(exam_id, token):
    """업로드된 PDF. 판독이 끝나면 지운다 — 장별 이미지가 이미 다 들어갔다."""
    return f"omr/batches/{exam_id}/{token}.pdf"


def workbook_page(year, month, token, suffix):
    """워크북 마지막 페이지 사진. 월별로 나눠 한 폴더가 무한정 커지지 않게."""
    return f"workbook/pages/{year:04d}/{month:02d}/{token}.{suffix}"


def demo(*parts):
    """시드 산출물. 실제 업로드본과 최상위에서 갈린다."""
    return "/".join((DEMO, *(str(part) for part in parts)))
