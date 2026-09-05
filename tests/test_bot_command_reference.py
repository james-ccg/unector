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


@pytest.mark.parametrize("handler", ["start", "faq", "commands"])
def test_a_reply_still_fits_in_a_telegram_message(handler):
    """sendMessage refuses anything over 4096 characters, so a reply that
    grows past it does not get truncated - it does not arrive at all, and
    the command looks broken rather than long. These three are the ones
    that grow, because every new feature wants a line in them.
    """
    import ast

    tree = ast.parse(BOT)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == f"handle_{handler}":
            # Implicit concatenation is already folded by the parser, so the
            # longest constant in the function is the reply itself.
            longest = max(
                (n.value for n in ast.walk(node)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)),
                key=len,
            )
            assert len(longest) <= 4096, f"/{handler} is {len(longest)} characters"
            return
    pytest.fail(f"no handler found for /{handler}")


def test_the_reference_says_what_rights_a_group_needs():
    """Writing the group's name, description and picture, and pinning the
    load card, all need admin rights the bot cannot grant itself. A user
    whose group silently does none of it should be able to find out why
    from the bot rather than from the README."""
    reference = _reply_of("commands")
    assert "Change group info" in reference
    assert "Pin messages" in reference
