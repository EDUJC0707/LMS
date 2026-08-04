"""감독 문서에서 요약만 잘라내기 — 전사 원문은 넘어오면 안 된다.

구글이 만드는 문서 하나에 **요약과 전사가 같이** 들어 있다(2026-08-04 실측).
요약은 우리 DB 로 들이고 전사 원문은 링크로만 두기로 했으므로(개인정보 —
PRD 8-1) 자르는 자리가 틀리면 학생 발화가 통째로 DB 에 쌓인다.

여기 쓰는 본문은 2026-08-04 실제 회의에서 나온 문서를 줄인 것이다.
"""
from django.test import SimpleTestCase

from .google_meet import split_summary

REAL_DOC = """﻿📝 회의록
8월 4, 2026
회의 일정: 2026년 8월 4일 08:15 UTC
회의 기록 스크립트

요약
회의 녹화 방침 및 클리닉 운영 효율화와 학습 환경 개선 방안을 논의함.

녹화 및 기록 지침
회의 기록은 영상 녹화 없이 음성 녹음만 진행하기로 결정함.

상세정보
* 녹화 및 기록 방식: Sean Park과 Plain Yoon은 영상 녹화는 끄고 음성 녹음만 (00:00:08).

Gemini가 작성한 회의록이 정확한지 검토해야 합니다. 회의록 작성 방법은 도움말을 알아보세요.
이 특정 메모의 품질은 어떤가요? 간단한 설문조사에 참여하여 의견을 들려 주세요.
📖 스크립트
8월 4, 2026
회의 일정: 2026년 8월 4일 08:15 UTC - 스크립트
00:00:08

Sean Park：자
Plain Yoon：안녕하세요. 박세현입니다. 전사가 되는지 봐야 돼요.

00:03:34 후 스크립트 작성이 종료되었습니다.
"""


class SplitSummaryTests(SimpleTestCase):
    def test_keeps_the_notes(self):
        summary = split_summary(REAL_DOC)
        self.assertIn("클리닉 운영 효율화", summary)
        self.assertIn("상세정보", summary)

    def test_drops_the_transcript(self):
        # 이것이 이 함수의 존재 이유다 — 학생 발화가 DB 로 넘어오면 안 된다
        summary = split_summary(REAL_DOC)
        self.assertNotIn("박세현입니다", summary)
        self.assertNotIn("Plain Yoon：", summary)
        self.assertNotIn("스크립트 작성이 종료", summary)

    def test_drops_gemini_boilerplate(self):
        # 감독 기록에 설문조사 안내가 남을 이유가 없다
        summary = split_summary(REAL_DOC)
        self.assertNotIn("설문조사", summary)
        self.assertNotIn("도움말을 알아보세요", summary)

    def test_missing_marker_yields_nothing(self):
        # 구글이 형식을 바꿔 자를 자리를 못 찾으면 **아무것도 저장하지 않는다**.
        # 통째로 넣는 쪽이 편하지만 그 순간 전사 원문이 DB 에 들어간다
        # (닫힘이 안전 기본값 — key_considerations §5).
        self.assertIsNone(split_summary("요약\n뭔가 적혀 있지만 표식이 없다"))

    def test_empty_notes_yield_nothing(self):
        self.assertIsNone(split_summary("📖 스크립트\nSean Park：자"))

    def test_handles_english_transcript_heading(self):
        # 계정 언어가 바뀌면 제목은 `Transcript` 가 되지만 이모지는 그대로다
        doc = "📝 Notes\n요약\n내용\n📖 Transcript\nSean：hello"
        self.assertNotIn("hello", split_summary(doc))
