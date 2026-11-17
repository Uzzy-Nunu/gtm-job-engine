"""HubSpotClient.upload: multipart request shape and fallback path (no network)."""

import json

import pytest

from src.hubspot_client import FILE_UPLOAD_PATHS, HubSpotClient, HubSpotError


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body, self.headers = status, body, {}
        self.content = json.dumps(body).encode()
        self.text = self.content.decode()

    def json(self):
        return self._body


class StubSession:
    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    def request(self, method, url, **kw):
        self.sent.append((method, url, kw))
        return self.answers.pop(0)


def client(answers):
    c = HubSpotClient(token="test-token", max_retries=0)
    c.session = StubSession(answers)
    return c


def test_upload_sends_private_multipart_file():
    c = client([Resp(201, {"id": "77", "name": "CV.docx"})])
    assert c.upload("CV.docx", b"PK..", "/gtm-job-engine/drafts")["id"] == "77"
    method, url, kw = c.session.sent[0]
    assert method == "POST" and url.endswith(FILE_UPLOAD_PATHS[0])
    assert kw["files"]["file"][0] == "CV.docx" and kw["headers"] == {"Content-Type": None}
    assert json.loads(kw["data"]["options"]) == {"access": "PRIVATE"}
    assert kw["data"]["folderPath"] == "/gtm-job-engine/drafts" and kw["json"] is None


def test_upload_falls_back_on_404_but_not_on_missing_scope():
    c = client([Resp(404, {"message": "gone"}), Resp(201, {"id": "78"})])
    assert c.upload("CV.docx", b"PK..", "/x")["id"] == "78"
    assert c.session.sent[1][1].endswith(FILE_UPLOAD_PATHS[1])

    c = client([Resp(403, {"message": "missing scopes", "category": "MISSING_SCOPES",
                           "context": {"requiredGranularScopes": ["files"]}})])
    with pytest.raises(HubSpotError, match="required scopes"):
        c.upload("CV.docx", b"PK..", "/x")
    assert len(c.session.sent) == 1
