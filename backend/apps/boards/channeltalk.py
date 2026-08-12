"""채널톡 통화 로그 — 업체가 들어오는 유일한 문 (PRD 9.2, key_considerations §4).

`absence_counselings` 는 채널톡을 모른다. 여기서 업체 형식(E.164 번호,
`engagedAt` 유무, `missedReason`)을 우리 말로 옮겨서 넘긴다.

**발신은 여기서 못 한다.** Meet 엔드포인트가 전부 GET 이라 API 로 전화를 걸
방법이 없다 — 조교가 채널톡 데스크에서 걸고 우리는 그 흔적을 읽을 뿐이다.

**통화 ID 가 없다.** 스펙의 `CallLog` 에 기본키가 없어서 같은 통화를 두 번
읽었는지는 (createdAt, to, direction) 으로만 가릴 수 있다. 그래서 이 모듈은
통화를 저장하지 않고 **화면이 물을 때 조회**만 한다 — 저장하는 순간 그 복합키가
계약이 되고, 업체가 필드를 하나 바꾸면 중복이 쌓인다.
"""
import datetime
import re

import requests
from django.conf import settings
from django.utils import timezone

BASE_URL = "https://api.channel.io"
# 스펙이 날짜 형식으로 버전을 고정한다. 안 보내면 서버 기본값이 쓰이고
# 응답에 Warning 헤더가 붙는다 — 조용히 바뀌는 것보다 박아 두는 편이 낫다.
API_VERSION = "2026-06-01"
TIMEOUT = 10
DEFAULT_WINDOW = datetime.timedelta(hours=6)


def normalize(phone):
    """업체 번호(E.164)를 우리 저장 형식으로 — `+8210…` → `010…`.

    못 알아보는 모양이어도 버리지 않고 숫자만 남긴다. 버리면 매칭이 조용히
    실패하고, 조교는 "왜 안 잡히지"를 화면에서 알 길이 없다.
    """
    digits = re.sub(r"\D", "", phone or "")
    if digits.startswith("82"):
        return "0" + digits[2:]
    return digits


def _credentials():
    key = getattr(settings, "CHANNELTALK_ACCESS_KEY", "")
    secret = getattr(settings, "CHANNELTALK_ACCESS_SECRET", "")
    return (key, secret) if key and secret else (None, None)


def fetch_calls(since, until):
    """[since, until) 통화 로그. 키가 없으면 빈 목록 — 화면은 떠야 한다."""
    key, secret = _credentials()
    if key is None:
        return []
    response = requests.get(
        f"{BASE_URL}/open/meet/call/log",
        params={
            "from": int(since.timestamp() * 1000),
            "to": int(until.timestamp() * 1000),
        },
        headers={
            "x-access-key": key,
            "x-access-secret": secret,
            "Channel-Version": API_VERSION,
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, list) else []


def recent_calls(phone, since=DEFAULT_WINDOW):
    """그 번호로 **우리가 건** 최근 통화 — 화면이 버튼을 미리 채우는 재료.

    inbound 는 뺀다. 학부모가 우리한테 건 것은 우리의 시도가 아니라서
    8-18 의 3회에 섞이면 시도 횟수가 거짓이 된다.
    """
    wanted = normalize(phone)
    if not wanted:
        return []
    until = timezone.now()
    logs = fetch_calls(until - since, until)
    return [
        _call_row(log)
        for log in logs
        if log.get("direction") == "outbound" and normalize(log.get("to")) == wanted
    ]


def _call_row(log):
    """업체 응답 1건 → 화면이 읽는 중립 형태.

    `engagedAt` 이 없으면 아무도 안 받은 것이다(스펙: "Absent if the call was
    never answered"). 그게 8-18 의 미연결 판정 근거다.
    """
    return {
        "direction": log.get("direction"),
        "called_at": log.get("createdAt"),
        "connected": bool(log.get("engagedAt")),
        "missed_reason": log.get("missedReason"),
        # 통화 ID 가 없어서 이것이 유일한 중립 참조다. 녹음·STT 를 나중에
        # 붙일 때도 이 값으로 찾는다.
        "user_chat_id": log.get("userChatId"),
    }
