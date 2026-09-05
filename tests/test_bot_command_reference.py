"""
The bot's own command list has to match the bot.

There are three places a command can be written down, and they drifted:
set_my_commands() populates Telegram's "/" menu, /commands prints the full
reference, and /start prints a short summary. /readbio was in the menu and
had a working handler for two days while /commands did not mention it, so
the only people who found it were the ones who already knew it existed.

Nothing here checks wording. It checks that the three lists agree about
which commands exist, which is the part that goes wrong quietly.
"""
import pathlib
import re
from unittest.mock import AsyncMock

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
BOT = (ROOT / "bot.py").read_text(encoding="utf-8")


def _reply_of(handler: str) -> str:
    """The text a handler replies with, from its source.

    Read out of the file rather than by calling the handler, because these
    replies are built inline in an async function that wants a Message.
    """
    start = BOT.index(f'Command("{handler}")')
    end = BOT.index("@dp.", start + 1)
    return BOT[start:end]


REGISTERED = set(re.findall(r'BotCommand\(command="([a-z0-9_]+)"', BOT))
HANDLED = set(re.findall(r'Command\("([a-z0-9_]+)"\)', BOT)) | set(
    re.findall(r'_command_filter\("([a-z0-9_]+)"\)', BOT)
)
# A command opens its own line, and every line in these replies is its own
# string literal - so a real command is a slash right after an opening
# quote. Matching a bare slash instead picks up the prose ("pickup/delivery",
# "owner/dispatcher") and reports half the English in the file as commands
# nobody implemented.
_COMMAND_IN_REPLY = re.compile(r'"/([a-z0-9_]+)')

LISTED = set(_COMMAND_IN_REPLY.findall(_reply_of("commands")))
SUMMARISED = set(_COMMAND_IN_REPLY.findall(_reply_of("start")))


def test_there_are_commands_to_check():
    """A regex that quietly matched nothing would make every test below
    pass while checking nothing at all."""
    assert len(REGISTERED) >= 10
    assert len(HANDLED) >= 10
    assert len(LISTED) >= 10


@pytest.mark.parametrize("command", sorted(REGISTERED))
def test_every_command_in_telegrams_menu_has_a_handler(command):
    """A command in the "/" menu that does nothing when tapped is worse
    than one that is not offered."""
    assert command in HANDLED, command


@pytest.mark.parametrize("command", sorted(REGISTERED))
def test_every_command_in_telegrams_menu_is_in_the_reference(command):
    """This is the one that broke. /commands calls itself the full command
    list, so anything missing from it is effectively undiscoverable."""
    assert command in LISTED, command


def test_the_reference_does_not_offer_commands_that_do_not_exist():
    """The other direction: a documented command nobody implemented sends
    the reader off to try something that will be ignored."""
    invented = LISTED - HANDLED
    assert not invented, sorted(invented)


def test_the_welcome_summary_only_promises_real_commands():
    """/start is allowed to be shorter than the reference - it is a summary -
    but everything it does mention has to work."""
    invented = SUMMARISED - HANDLED
    assert not invented, sorted(invented)


@pytest.mark.asyncio
@pytest.mark.parametrize("handler", ["start", "faq", "commands"])
async def test_every_message_a_command_sends_fits(handler):
    """sendMessage refuses anything over 4096 characters, so a reply that
    grows past it does not get truncated - it does not arrive at all, and
    the command looks broken rather than long. These three are the ones that
    grow, because every new feature wants a line in them.

    Checked by running the handler rather than by reading the source, since
    /faq is long enough to be split into several messages now and it is the
    messages that have to fit, not the text they were cut from.
    """
    import bot as bot_module

    message = AsyncMock()
    await getattr(bot_module, f"handle_{handler}")(message)

    sent = [call.args[0] for call in message.reply.await_args_list]
    assert sent, f"/{handler} sent nothing"
    for part in sent:
        assert len(part) <= 4096, f"/{handler} sent {len(part)} characters"


def test_a_split_reply_never_cuts_a_question_in_half():
    """The split is between questions, so a heading always arrives with the
    answer underneath it - cutting at the limit exactly would leave somebody
    reading half an answer, then a heading with nothing after it.

    Driven with a small limit rather than the real one: the FAQ is short
    enough to fit in one message today, so testing it at 4096 would exercise
    nothing and quietly keep passing if the splitter broke.

    The limit has to stay above the longest single answer, which is what the
    first assertion pins. Below it, the fallback in the next test takes over
    and a mid-sentence break is the correct behaviour rather than a bug.
    """
    import bot as bot_module

    limit = 900
    sections = bot_module.FAQ_TEXT.split("\n\n")
    assert max(len(s) for s in sections) <= limit, "an answer outgrew this test's limit"

    chunks = bot_module.split_for_telegram(bot_module.FAQ_TEXT, limit=limit)
    assert len(chunks) > 1, "the limit was not small enough to force a split"
    for chunk in chunks:
        assert len(chunk) <= limit
    for chunk in chunks[1:]:
        assert chunk.startswith("**"), chunk[:60]
    assert "".join(chunks).replace("\n", "") == bot_module.FAQ_TEXT.replace("\n", "")


def test_a_section_longer_than_the_limit_still_gets_sent():
    """An ugly break beats no message at all. One answer growing past the
    limit on its own is a real possibility, and the fallback is what stops
    that turning into a command that silently stops replying."""
    import bot as bot_module

    chunks = bot_module.split_for_telegram("x" * 250, limit=100)
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_the_reference_says_what_rights_a_group_needs():
    """Writing the group's name, description and picture, and pinning the
    load card, all need admin rights the bot cannot grant itself. A user
    whose group silently does none of it should be able to find out why
    from the bot rather than from the README."""
    reference = _reply_of("commands")
    assert "Change group info" in reference
    assert "Pin messages" in reference
