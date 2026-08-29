"""
Tests for services/gmail_service.py - finding the Rate Confirmation PDF in a
company's inbox, and sending the POD back to the broker.

Everything here mocks the Gmail API client at _build_gmail_client, so no
network call or real inbox is involved. What's being tested is the logic
around the API: how the search query is built (including the injection
guard on the driver-supplied load ID), how a message's parts are walked to
find an attachment, and the recipient validation on the send path.
"""
import base64
from unittest.mock import MagicMock, patch

import pytest

from services import gmail_service


def _pdf_part(filename="rate_con.pdf", attachment_id="att-1"):
    return {"filename": filename, "body": {"attachmentId": attachment_id}}


def _mock_service(messages_list=None, message_bodies=None, attachments=None):
    """Builds a stand-in for the googleapiclient Gmail resource. Only the
    call chains gmail_service actually uses are wired up."""
    service = MagicMock()
    users = service.users.return_value
    msgs = users.messages.return_value

    msgs.list.return_value.execute.return_value = {"messages": messages_list or []}

    bodies = message_bodies or {}
    msgs.get.side_effect = lambda userId, id: MagicMock(
        execute=MagicMock(return_value=bodies.get(id, {"id": id, "payload": {}}))
    )

    att_map = attachments or {}
    msgs.attachments.return_value.get.side_effect = lambda userId, messageId, id: MagicMock(
        execute=MagicMock(return_value={"data": att_map.get(id, "")})
    )
    return service


class TestFindRcPdfByLoadId:
    def test_returns_the_first_pdf_attachment_found(self):
        pdf = b"%PDF-1.4 fake rate confirmation"
        service = _mock_service(
            messages_list=[{"id": "m1"}],
            message_bodies={"m1": {"id": "m1", "payload": {"parts": [_pdf_part()]}}},
            attachments={"att-1": base64.urlsafe_b64encode(pdf).decode()},
        )
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            assert gmail_service.find_rc_pdf_by_load_id(1, "12345") == pdf

    def test_quotes_are_stripped_from_the_load_id(self):
        """load_id is whatever the driver typed after /dispatch. Left
        unescaped it would close the quoted search term and let extra Gmail
        operators through - e.g. from: pointed at another sender's mail.
        Stripping quotes keeps the whole thing inside one quoted literal,
        where an operator is just text."""
        service = _mock_service()
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            gmail_service.find_rc_pdf_by_load_id(1, '12345" OR from:attacker@evil.com "')

        query = service.users().messages().list.call_args.kwargs["q"]

        # Exactly one quoted term - the injected quotes are gone, so nothing
        # the driver typed can escape it.
        assert query.count('"') == 2, f"unbalanced quotes let operators escape: {query!r}"
        search_term = query.split('"')[1]
        assert "from:attacker@evil.com" in search_term, "the operator must stay inert inside the term"
        assert query == '"12345 OR from:attacker@evil.com " has:attachment filename:pdf'

    def test_query_asks_gmail_only_for_messages_with_a_pdf(self):
        service = _mock_service()
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            gmail_service.find_rc_pdf_by_load_id(1, "98765")

        query = service.users().messages().list.call_args.kwargs["q"]
        assert '"98765"' in query
        assert "has:attachment" in query
        assert "filename:pdf" in query

    def test_returns_none_when_no_messages_match(self):
        service = _mock_service(messages_list=[])
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            assert gmail_service.find_rc_pdf_by_load_id(1, "00000") is None

    def test_keeps_looking_when_an_earlier_message_has_no_pdf(self):
        """Gmail's search matches the load number in the body too, so the
        first hit is often a plain reply with no attachment. Stopping there
        would report "no RC found" for a load that does have one."""
        pdf = b"%PDF real one"
        service = _mock_service(
            messages_list=[{"id": "no-pdf"}, {"id": "has-pdf"}],
            message_bodies={
                "no-pdf": {"id": "no-pdf", "payload": {"parts": [
                    {"filename": "signature.png", "body": {"attachmentId": "img"}}
                ]}},
                "has-pdf": {"id": "has-pdf", "payload": {"parts": [_pdf_part(attachment_id="att-2")]}},
            },
            attachments={"att-2": base64.urlsafe_b64encode(pdf).decode()},
        )
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            assert gmail_service.find_rc_pdf_by_load_id(1, "12345") == pdf

    def test_returns_none_when_no_message_has_a_pdf(self):
        service = _mock_service(
            messages_list=[{"id": "m1"}],
            message_bodies={"m1": {"id": "m1", "payload": {"parts": [
                {"filename": "notes.txt", "body": {"attachmentId": "a"}}
            ]}}},
        )
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            assert gmail_service.find_rc_pdf_by_load_id(1, "12345") is None


class TestExtractFirstPdfAttachment:
    def test_matches_pdf_extension_case_insensitively(self):
        pdf = b"%PDF upper"
        service = _mock_service(attachments={"att-1": base64.urlsafe_b64encode(pdf).decode()})
        message = {"id": "m1", "payload": {"parts": [_pdf_part(filename="RATE_CON.PDF")]}}

        assert gmail_service._extract_first_pdf_attachment(service, message) == pdf

    def test_skips_a_pdf_part_that_has_no_attachment_id(self):
        """An inline/nested part can name a PDF without carrying a
        downloadable body - taking it would crash on the None id."""
        pdf = b"%PDF second"
        service = _mock_service(attachments={"att-2": base64.urlsafe_b64encode(pdf).decode()})
        message = {"id": "m1", "payload": {"parts": [
            {"filename": "inline.pdf", "body": {}},
            _pdf_part(attachment_id="att-2"),
        ]}}

        assert gmail_service._extract_first_pdf_attachment(service, message) == pdf

    def test_message_with_no_parts_returns_none(self):
        service = _mock_service()
        assert gmail_service._extract_first_pdf_attachment(service, {"id": "m1", "payload": {}}) is None
        assert gmail_service._extract_first_pdf_attachment(service, {"id": "m1"}) is None

    def test_null_parts_list_is_treated_as_empty(self):
        service = _mock_service()
        message = {"id": "m1", "payload": {"parts": None}}
        assert gmail_service._extract_first_pdf_attachment(service, message) is None

    def test_decodes_url_safe_base64(self):
        """Gmail returns attachment data base64url-encoded - decoding it as
        standard base64 corrupts any payload containing - or _."""
        raw = bytes(range(256))
        service = _mock_service(attachments={"att-1": base64.urlsafe_b64encode(raw).decode()})
        message = {"id": "m1", "payload": {"parts": [_pdf_part()]}}

        assert gmail_service._extract_first_pdf_attachment(service, message) == raw


class TestSendEmail:
    @pytest.mark.parametrize("bad", ["", None, "not-an-email", "missing@tld", "@nodomain.com"])
    def test_rejects_an_invalid_recipient_before_calling_gmail(self, bad):
        """The broker address comes from AI extraction of the RC, so it can
        be missing or garbled. Failing loudly here beats a confusing Gmail
        API error, and proves no send was attempted."""
        service = _mock_service()
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            with pytest.raises(ValueError, match="recipient email"):
                gmail_service.send_email(1, bad, "POD", "body")

        service.users().messages().send.assert_not_called()

    def test_sends_a_plain_message_when_there_are_no_attachments(self):
        service = _mock_service()
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            gmail_service.send_email(1, "broker@example.com", "POD for 12345", "Attached.")

        body = service.users().messages().send.call_args.kwargs["body"]
        decoded = base64.urlsafe_b64decode(body["raw"]).decode()
        assert "to: broker@example.com" in decoded.lower()
        assert "POD for 12345" in decoded
        assert "Attached." in decoded

    def test_attaches_the_pod_file(self):
        pod = b"%PDF signed delivery receipt"
        service = _mock_service()
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            gmail_service.send_email(
                1, "broker@example.com", "POD", "See attached.",
                attachments=[{"filename": "pod_12345.pdf", "data": pod, "mime_type": "application/pdf"}],
            )

        body = service.users().messages().send.call_args.kwargs["body"]
        decoded = base64.urlsafe_b64decode(body["raw"]).decode()
        assert 'filename="pod_12345.pdf"' in decoded
        # The payload rides base64-encoded inside the MIME part.
        assert base64.b64encode(pod).decode() in decoded.replace("\n", "")

    def test_gmail_failure_is_reraised_as_a_runtime_error(self):
        """bot.py catches RuntimeError to tell the driver the POD didn't
        send; letting the raw HttpError through would escape that handler."""
        from googleapiclient.errors import HttpError

        service = _mock_service()
        response = MagicMock(status=500, reason="Backend Error")
        service.users().messages().send.return_value.execute.side_effect = HttpError(
            response, b'{"error": {"message": "Backend Error"}}'
        )
        with patch.object(gmail_service, "_build_gmail_client", return_value=service):
            with pytest.raises(RuntimeError, match="Gmail API failed to send"):
                gmail_service.send_email(1, "broker@example.com", "POD", "body")
