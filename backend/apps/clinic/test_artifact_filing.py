"""감독 자료 정리 — **문서가 아니라 회의 폴더**를 옮긴다.

구글은 회의마다 `Google Meet/{회의코드} - {시각}/` 을 만들고 그 안에 산출물을
넣는다. 문서만 꺼내 오면 빈 껍데기가 회의 수만큼 쌓이고, 나중에 녹화나 출석
리포트를 켰을 때 그것들은 따라오지 않아 코드를 또 고쳐야 한다.
폴더째 옮기면 구글이 그 회의에 무엇을 더 넣든 같이 따라온다.
"""
import json

from django.test import SimpleTestCase, override_settings

from .google_meet import GoogleMeetAdapter

CREDENTIALS = {
    "GOOGLE_MEET_CLIENT_ID": "cid",
    "GOOGLE_MEET_CLIENT_SECRET": "secret",
    "GOOGLE_MEET_REFRESH_TOKEN": "1//refresh",
}

DOC_ID = "doc-1"
MEETING_FOLDER = "meetfolder-1"


class RoutingTransport:
    """순서가 아니라 **무엇을 부르는가**로 답한다 — 호출 순서에 안 묶이게."""

    def __init__(self, meeting_folder_name="hbj-opib-vak - 2026/08/04 08:15 UTC"):
        self.meeting_folder_name = meeting_folder_name
        self.patches = []
        self.created = []

    def __call__(self, method, url, body, headers, timeout):
        payload = json.loads(body.decode()) if body and url.endswith(("files", DOC_ID)) else None
        if "oauth2" in url:
            return 200, json.dumps({"access_token": "ya29"}).encode()
        if "conferenceRecords?" in url:
            record = {"name": "conferenceRecords/r1", "endTime": "2026-08-04T08:19:34Z"}
            return 200, json.dumps({"conferenceRecords": [record]}).encode()
        if url.endswith("/smartNotes"):
            return 200, json.dumps(
                {"smartNotes": [{"docsDestination": {"document": DOC_ID, "exportUri": "https://x/doc"}}]}
            ).encode()
        if "/export?" in url:
            return 200, "요약\n내용\n📖 스크립트\nSean：hi".encode()
        if method == "GET" and url.endswith(f"files/{DOC_ID}?fields=parents"):
            return 200, json.dumps({"parents": [MEETING_FOLDER]}).encode()
        if method == "GET" and f"files/{MEETING_FOLDER}?" in url:
            return 200, json.dumps(
                {"name": self.meeting_folder_name, "parents": ["gmeet-root"]}
            ).encode()
        if method == "GET" and "files?" in url:  # 폴더 검색 — 없다고 답한다
            return 200, json.dumps({"files": []}).encode()
        if method == "POST" and url.endswith("files"):
            self.created.append(payload["name"])
            return 200, json.dumps({"id": f"folder-{payload['name']}"}).encode()
        if method == "PATCH":
            self.patches.append({"url": url, "body": payload or json.loads(body.decode())})
            return 200, json.dumps({"id": "ok"}).encode()
        return 404, b"{}"


@override_settings(**CREDENTIALS)
class FileMeetingFolderTests(SimpleTestCase):
    def collect(self, transport, file_as="clinic/2026-08/2026-08-03_1900_박지우0003"):
        return GoogleMeetAdapter(transport=transport).fetch_supervision(
            "spaces/S1", file_as=file_as
        )

    def test_moves_the_meeting_folder_not_the_document(self):
        transport = RoutingTransport()
        self.collect(transport)
        patched = [p["url"] for p in transport.patches]
        self.assertTrue(any(MEETING_FOLDER in url for url in patched), patched)
        self.assertFalse(any(f"files/{DOC_ID}?" in url for url in patched), patched)

    def test_renames_the_folder_to_the_leaf(self):
        transport = RoutingTransport()
        self.collect(transport)
        self.assertEqual(transport.patches[0]["body"]["name"], "2026-08-03_1900_박지우0003")

    def test_detaches_from_the_google_meet_folder(self):
        # removeParents 없이 addParents 만 보내면 두 곳에 걸린 채로 남는다
        transport = RoutingTransport()
        self.collect(transport)
        self.assertIn("removeParents=gmeet-root", transport.patches[0]["url"])

    def test_creates_the_month_folders(self):
        transport = RoutingTransport()
        self.collect(transport)
        self.assertEqual(transport.created, ["clinic", "2026-08"])

    def test_never_renames_googles_own_root(self):
        # 문서가 회의 폴더가 아니라 `Google Meet` 바로 아래 있으면 손대지 않는다.
        # 그걸 이름 바꾸면 앞으로 모든 회의 산출물이 엉뚱한 데로 들어간다.
        transport = RoutingTransport(meeting_folder_name="Google Meet")
        self.collect(transport)
        self.assertEqual(transport.patches, [])

    def test_summary_survives_a_filing_failure(self):
        # 정리는 편의고 요약·링크가 본론이다
        class Failing(RoutingTransport):
            def __call__(self, method, url, body, headers, timeout):
                if method in ("PATCH", "POST") and "drive" in url:
                    return 500, b"{}"
                return super().__call__(method, url, body, headers, timeout)

        found = self.collect(Failing())
        self.assertEqual(found.transcript_ref, DOC_ID)
        self.assertIn("내용", found.summary)
