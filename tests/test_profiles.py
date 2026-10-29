import pytest

from mail_mcp.errors import MailMCPError
from mail_mcp.profiles import DANGER_TOOLS, get_profile


def test_reader_has_no_write_tools():
    p = get_profile("reader")
    reg = set(p.registered())
    assert "send_message" not in reg
    assert "delete_message" not in reg
    assert "get_message" in reg


def test_full_has_write_but_not_delete():
    reg = set(get_profile("full").registered())
    assert "send_message" in reg
    assert not (set(DANGER_TOOLS) & reg)


def test_danger_requires_enable_flag():
    p = get_profile("danger")
    assert "delete_message" not in p.registered(enable_delete=False)
    assert "delete_message" in p.registered(enable_delete=True)


def test_unknown_profile_raises():
    with pytest.raises(MailMCPError):
        get_profile("god")
