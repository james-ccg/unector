"""
The one command that starts everything.

Five processes have to come up in the right order and, far more importantly,
go down together. Three failures cost real time before this existed, and
each has a test here because each looks like something else when it happens:

* An orphan holds a port or the tunnel subdomain, so the next run comes up
  on a random address while MINIAPP_URL, the bot's links and Google's
  redirect URIs all still point at the old one. It reads as "the tunnel is
  broken".
* The tunnel starts before the API is listening and answers 503 forever. It
  reads as "localtunnel is down".
* A tool is found as its extension-less Unix shim rather than its .cmd, and
  Windows refuses it with "not a valid Win32 application". It reads as a
  corrupt install.

Nothing here starts a real process. What is checked is the decisions - the
order, the lookups, the cleanup - because the parts that go wrong are the
ones that are invisible when they do.
"""
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import dev  # noqa: E402

SOURCE = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")


class TestFindingTools:
    def test_a_windows_shim_is_asked_for_by_extension(self, monkeypatch):
        """shutil.which returns whichever of npm and npm.cmd PATHEXT favours,
        and Git Bash changes PATHEXT. Getting the shell script is how you end
        up with WinError 193, which reads like a corrupt binary."""
        monkeypatch.setattr(dev, "IS_WINDOWS", True)
        asked = []

        def fake_which(name):
            asked.append(name)
            return r"C:\tools\npm.cmd" if name == "npm.cmd" else None

        monkeypatch.setattr(dev.shutil, "which", fake_which)
        assert dev.which("npm") == r"C:\tools\npm.cmd"
        assert asked[0] == "npm.cmd", "the .cmd has to be asked for first"

    def test_off_windows_the_plain_name_is_right(self, monkeypatch):
        monkeypatch.setattr(dev, "IS_WINDOWS", False)
        monkeypatch.setattr(dev.shutil, "which", lambda name: f"/usr/bin/{name}")
        assert dev.which("npm") == "/usr/bin/npm"

    def test_a_cmd_is_run_through_the_interpreter(self, monkeypatch):
        """A .cmd is a script, not an executable - CreateProcess needs cmd.exe
        to run it."""
        monkeypatch.setattr(dev, "IS_WINDOWS", True)
        wrapped = dev.runnable([r"C:\tools\npm.cmd", "run", "dev"])
        assert wrapped[0].lower().endswith("cmd.exe")
        assert wrapped[1] == "/c"
        assert wrapped[2:] == [r"C:\tools\npm.cmd", "run", "dev"]

    def test_a_real_executable_is_left_alone(self, monkeypatch):
        monkeypatch.setattr(dev, "IS_WINDOWS", True)
        args = [r"C:\py\python.exe", "bot.py"]
        assert dev.runnable(args) == args

    def test_the_interpreter_is_taken_from_an_absolute_path(self):
        """So a cmd.exe left in the working directory cannot stand in for the
        real one. Same reason taskkill is resolved absolutely."""
        assert 'os.environ.get("SystemRoot"' in SOURCE
        assert "System32" in SOURCE


class TestTheTunnelAgreesWithTheRestOfTheApp:
    @pytest.mark.parametrize("url,expected", [
        ("https://unector.loca.lt", "unector"),
        ("https://unector.loca.lt/", "unector"),
        ("https://something-else.loca.lt", "something-else"),
    ])
    def test_the_subdomain_comes_from_miniapp_url(self, url, expected):
        """Not hardcoded. The bot's dashboard links, Google's redirect URIs
        and Telegram's Mini App URL are all built from MINIAPP_URL, so a
        tunnel on a different address is a tunnel nothing points at."""
        assert dev._subdomain({"MINIAPP_URL": url}) == expected

    @pytest.mark.parametrize("url", ["", "https://unector.com", "not a url"])
    def test_anything_that_is_not_a_tunnel_address_gets_no_subdomain(self, url):
        """A real domain needs no tunnel, and claiming one named after it
        would be claiming somebody else's."""
        assert dev._subdomain({"MINIAPP_URL": url}) is None


class TestOrder:
    def test_the_tunnel_waits_for_the_api(self):
        """It attaches to the API's port. Started first it answers 503 until
        somebody notices, which reads as the tunnel being broken."""
        body = SOURCE[SOURCE.index("def main("):]
        assert body.index("wait_for_api()") < body.index('Service("tunnel"')

    def test_the_api_is_first(self):
        body = SOURCE[SOURCE.index("def main("):]
        assert body.index('Service("api"') < body.index('Service("web"')

    def test_giving_up_on_the_api_stops_the_run(self):
        """Starting the rest around an API that never came up produces four
        services all failing for one reason, reported four different ways."""
        assert "if not wait_for_api():\n            return 1" in SOURCE


class TestNothingSurvives:
    def test_children_go_into_a_job_that_kills_on_close(self):
        """The guarantee: killing the launcher outright, with no chance to
        run cleanup, still takes everything with it."""
        assert "JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000" in SOURCE
        assert "AssignProcessToJobObject" in SOURCE

    def test_the_job_handle_is_closed_in_a_finally(self):
        """Closing it is what triggers the kill, so it cannot sit on a happy
        path."""
        finally_block = SOURCE[SOURCE.index("    finally:"):]
        assert "CloseHandle(job)" in finally_block

    def test_leftovers_are_cleared_before_starting(self):
        assert "clear_leftovers()" in SOURCE
        body = SOURCE[SOURCE.index("def main("):]
        assert body.index("clear_leftovers()") < body.index('Service("api"')

    def test_killing_takes_the_whole_tree(self):
        """Without /T the grandchildren survive and keep holding whatever the
        parent was holding - which is the entire problem."""
        assert '"/F", "/T", "/PID"' in SOURCE


class TestSayingWhatIsWrong:
    def test_a_service_that_cannot_work_is_not_started(self):
        """Stripe forwarding with an expired login looks exactly like a
        working one until a payment goes missing."""
        assert 'if can["stripe"] and stripe_cli:' in SOURCE
        assert 'if can["bot"]:' in SOURCE

    def test_the_stripe_complaint_is_readable(self):
        """Its errors are a sentence then a JSON body, so the first line
        containing "error" is `"error": {` - punctuation presented as a
        diagnosis."""
        reason = dev._stripe_reason(
            'Authorization failed, status=401, body={\n'
            '  "error": {\n'
            '    "message": "Expired API Key provided: sk_test_xxxx",\n'
            '    "type": "invalid_request_error"\n  }\n}'
        )
        assert reason == "Expired API Key provided: sk_test_xxxx"

    def test_an_empty_complaint_still_says_something(self):
        assert dev._stripe_reason("") == "not signed in"
        assert dev._stripe_reason(None) == "not signed in"

    def test_the_summary_line_is_used_when_there_is_no_body(self):
        assert dev._stripe_reason("Authorization failed, status=401") == (
            "Authorization failed, status=401"
        )


class TestItIsReachable:
    def test_npm_run_dev_starts_it(self):
        import json

        scripts = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["scripts"]
        assert scripts["dev"] == "python scripts/dev.py"
