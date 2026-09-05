"""
The company's logo, on a truck's group.

The picture on a truck's group is the carrier's, not the driver's - a
dispatcher looking at forty groups should see who they work for in every
one of them. It is stored against ("owner", company_id), keyed by the
company rather than by a person, which is what makes it the company's mark
and not somebody's profile picture.

Two Telegram details are what most of these tests are about: setChatPhoto
refuses a file_id and wants a real multipart upload, and reading a photo
back takes getChat, then getFile, then the file endpoint.
"""
import base64
from unittest.mock import MagicMock, patch

import pytest

from db import models, repository
from db.database import get_session
from services import group_profile

IMAGE_BYTES = b"\x89PNG\r\n\x1a\nfake-image-bytes"
LOGO_DATA_URL = "data:image/png;base64," + base64.b64encode(IMAGE_BYTES).decode("ascii")


@pytest.fixture
def company_and_driver(request):
    tag = f"LOGO{abs(hash(request.node.name)) % 100000}"
    with get_session() as session:
        company = models.Company(
            mc_number=f"MC-{tag}",
            company_name="Logo Test Carrier",
            telegram_group_prefix=tag,
        )
        session.add(company)
        session.commit()
        driver = models.Driver(company_id=company.id, driver_bot_id="D900")
        session.add(driver)
        session.commit()
        return company.id, driver.id


class TestDecoding:
    def test_a_stored_logo_comes_back_as_bytes_and_a_type(self):
        decoded = group_profile.decode_logo(LOGO_DATA_URL)
        assert decoded is not None
        raw, mime = decoded
        assert raw == IMAGE_BYTES
        assert mime == "image/png"

    @pytest.mark.parametrize("value", [
        None,
        "",
        "https://example.com/logo.png",
        "data:text/plain;base64,aGVsbG8=",
        "data:image/png;base64,not valid base64!!",
        "data:image/png;base64,",
    ])
    def test_anything_that_is_not_an_image_data_uri_is_refused(self, value):
        """The column is written by our own upload path, so a value that
        does not match is a sign something else wrote it - not a case to
        guess at."""
        assert group_profile.decode_logo(value) is None


class TestPublishing:
    def test_a_driver_with_no_group_is_not_written_to(self, company_and_driver):
        company_id, driver_id = company_and_driver
        repository.set_account_avatar("owner", company_id, LOGO_DATA_URL)
        result = group_profile.publish_logo(company_id, driver_id)
        assert result == {"written": False, "reason": "no group linked"}

    def test_a_company_with_no_logo_leaves_the_group_picture_alone(self, company_and_driver):
        """Deleting whatever the group already has, because we have nothing
        to put there, would be pure loss."""
        company_id, driver_id = company_and_driver
        with get_session() as session:
            session.get(models.Driver, driver_id).telegram_group_id = -100901001
            session.commit()

        with patch("services.group_profile.requests.post") as post:
            result = group_profile.publish_logo(company_id, driver_id)

        assert result == {"written": False, "reason": "no logo set"}
        post.assert_not_called()

    def test_the_logo_is_uploaded_as_a_file_not_a_file_id(self, company_and_driver):
        """setChatPhoto refuses a file_id - it wants multipart/form-data -
        so the bytes go up every time."""
        company_id, driver_id = company_and_driver
        with get_session() as session:
            session.get(models.Driver, driver_id).telegram_group_id = -100901002
            session.commit()
        repository.set_account_avatar("owner", company_id, LOGO_DATA_URL)

        with patch("services.group_profile.requests.post") as post:
            post.return_value.ok = True
            result = group_profile.publish_logo(company_id, driver_id)

        assert result["written"] is True
        assert post.call_args.args[0].endswith("/setChatPhoto")
        assert post.call_args.kwargs["data"]["chat_id"] == "-100901002"
        name, raw, mime = post.call_args.kwargs["files"]["photo"]
        assert name == "logo.png"
        assert raw == IMAGE_BYTES
        assert mime == "image/png"

    def test_a_group_that_refuses_the_picture_does_not_raise(self, company_and_driver):
        """The confirmation already succeeded by the time this runs."""
        company_id, driver_id = company_and_driver
        with get_session() as session:
            session.get(models.Driver, driver_id).telegram_group_id = -100901003
            session.commit()
        repository.set_account_avatar("owner", company_id, LOGO_DATA_URL)

        with patch("services.group_profile.requests.post") as post:
            post.return_value.ok = False
            post.return_value.status_code = 400
            post.return_value.text = "Bad Request: not enough rights"
            result = group_profile.publish_logo(company_id, driver_id)

        assert result["written"] is False
        assert "400" in result["reason"]


class TestAdopting:
    def _telegram(self, photo=True, raw=b"jpeg-bytes"):
        """getChat, then getFile, then the file endpoint."""
        def fake_get(url, **kwargs):
            response = MagicMock()
            response.ok = True
            if "/getChat" in url:
                result = {"photo": {"big_file_id": "BIG", "small_file_id": "SMALL"}} if photo else {}
                response.json.return_value = {"result": result}
            elif "/getFile" in url:
                response.json.return_value = {"result": {"file_path": "photos/file_1.jpg"}}
            else:
                response.content = raw
            return response
        return fake_get

    def test_a_group_photo_becomes_the_logo_when_there_is_none(self, company_and_driver):
        company_id, _ = company_and_driver
        with patch("services.group_profile.requests.get", side_effect=self._telegram()):
            result = group_profile.adopt_group_logo(company_id, -100901004)

        assert result["adopted"] is True
        stored = repository.get_account_avatar("owner", company_id)
        assert stored.startswith("data:image/jpeg;base64,")
        assert base64.b64decode(stored.split(",", 1)[1]) == b"jpeg-bytes"

    def test_a_logo_somebody_chose_is_never_overwritten(self, company_and_driver):
        """A carrier who uploaded their own mark has said what they want,
        and one truck's group picture is not a better source than that."""
        company_id, _ = company_and_driver
        repository.set_account_avatar("owner", company_id, LOGO_DATA_URL)

        with patch("services.group_profile.requests.get") as get:
            result = group_profile.adopt_group_logo(company_id, -100901005)

        assert result == {"adopted": False, "reason": "already set"}
        get.assert_not_called()
        assert repository.get_account_avatar("owner", company_id) == LOGO_DATA_URL

    def test_a_group_with_no_picture_is_not_an_error(self, company_and_driver):
        company_id, _ = company_and_driver
        with patch("services.group_profile.requests.get", side_effect=self._telegram(photo=False)):
            result = group_profile.adopt_group_logo(company_id, -100901006)

        assert result == {"adopted": False, "reason": "no group photo"}
        assert repository.get_account_avatar("owner", company_id) is None

    def test_an_implausibly_large_photo_is_left_alone(self, company_and_driver):
        """The download is read into memory whole, so there is a ceiling on
        it - a chat photo is 640x640 at the largest, so this never fires in
        practice and exists to stop a surprise becoming a memory problem."""
        company_id, _ = company_and_driver
        huge = b"x" * (group_profile.LOGO_DOWNLOAD_LIMIT_BYTES + 1)
        with patch("services.group_profile.requests.get", side_effect=self._telegram(raw=huge)):
            result = group_profile.adopt_group_logo(company_id, -100901007)

        assert result == {"adopted": False, "reason": "photo too large"}
        assert repository.get_account_avatar("owner", company_id) is None

    def test_telegram_being_unreachable_is_not_an_error(self, company_and_driver):
        company_id, _ = company_and_driver
        with patch("services.group_profile.requests.get", side_effect=OSError("connection reset")):
            result = group_profile.adopt_group_logo(company_id, -100901008)

        assert result["adopted"] is False
        assert result["reason"] == "OSError"
