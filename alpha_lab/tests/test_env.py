"""
tests/test_env.py — the dependency-free .env loader.

Pure parsing plus the load rules (real env wins, override flips it). No process
env is mutated except a scratch key we clean up.
"""
import os

from alpha_lab.env import load_dotenv, parse_dotenv


def test_parse_basic_and_comments():
    text = "\n".join([
        "# a comment",
        "",
        "FOO=bar",
        "  BAZ = qux  ",
        "export EXPORTED=yes",
        "QUOTED=\"hello world\"",
        "SINGLE='single quoted'",
        "INLINE=value # trailing comment",
        "HASHVALUE=abc#notacomment",
        "malformed line without equals",
    ])
    parsed = parse_dotenv(text)
    assert parsed["FOO"] == "bar"
    assert parsed["BAZ"] == "qux"
    assert parsed["EXPORTED"] == "yes"
    assert parsed["QUOTED"] == "hello world"
    assert parsed["SINGLE"] == "single quoted"
    assert parsed["INLINE"] == "value"
    assert parsed["HASHVALUE"] == "abc#notacomment"   # '#' with no leading space stays
    assert "malformed line without equals" not in parsed


def test_load_does_not_override_real_env(tmp_path):
    key = "ALPHALAB_TEST_ENV_KEY"
    os.environ[key] = "from_shell"
    try:
        env_file = tmp_path / ".env"
        env_file.write_text(f"{key}=from_file\nALPHALAB_TEST_NEW=created\n")
        applied = load_dotenv(env_file)
        # real env wins -> existing key untouched, not reported as applied
        assert os.environ[key] == "from_shell"
        assert key not in applied
        # new key gets set
        assert os.environ["ALPHALAB_TEST_NEW"] == "created"
        assert applied["ALPHALAB_TEST_NEW"] == "created"
    finally:
        os.environ.pop(key, None)
        os.environ.pop("ALPHALAB_TEST_NEW", None)


def test_load_override(tmp_path):
    key = "ALPHALAB_TEST_OVERRIDE"
    os.environ[key] = "old"
    try:
        env_file = tmp_path / ".env"
        env_file.write_text(f"{key}=new\n")
        load_dotenv(env_file, override=True)
        assert os.environ[key] == "new"
    finally:
        os.environ.pop(key, None)


def test_load_missing_file_is_noop(tmp_path):
    assert load_dotenv(tmp_path / "does_not_exist.env") == {}
