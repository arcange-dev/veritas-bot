"""The GitHub integration must read the SAME names the settings and render.yaml define.

An earlier version read GITHUB_WEBHOOK_SECRET / GITHUB_APP_PRIVATE_KEY while the settings defined
GITHUB_APP_WEBHOOK_SECRET / GITHUB_APP_PRIVATE_KEY_PATH, so production would have answered 503
forever with every variable set correctly. The other tests set the names the code reads, which hid it.
"""
import importlib
import os
import subprocess
import sys

CODE = (
    "import django; django.setup();"
    "from integrations import github;"
    "print(github.is_configured(), bool(github.webhook_secret()), github.app_slug(), github.app_private_key().count(chr(10)))"
)


def run(env_extra: dict[str, str]) -> list[str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GITHUB_")}
    env.update({"DJANGO_SETTINGS_MODULE": "config.settings.test", **env_extra})
    out = subprocess.run([sys.executable, "-c", CODE], env=env, capture_output=True, text=True, check=True).stdout
    return out.split()


def test_the_documented_env_names_configure_the_integration():
    got = run({"GITHUB_APP_ID": "1", "GITHUB_APP_SLUG": "veritas-bot", "GITHUB_APP_WEBHOOK_SECRET": "s3cret",
               "GITHUB_APP_PRIVATE_KEY": "-----BEGIN-----\\nABC\\n-----END-----"})
    assert got == ["True", "True", "veritas-bot", "2"]


def test_a_private_key_file_path_still_works_for_local_development(tmp_path):
    key = tmp_path / "k.pem"; key.write_text("-----BEGIN-----\nABC\n-----END-----\n")
    got = run({"GITHUB_APP_ID": "1", "GITHUB_APP_WEBHOOK_SECRET": "s", "GITHUB_APP_PRIVATE_KEY_PATH": str(key)})
    assert got[0] == "True"


def test_nothing_set_means_not_configured_and_does_not_crash():
    assert run({}) == ["False", "False", "0"]       # empty slug prints nothing, so three tokens remain


def test_a_missing_key_file_reads_as_not_configured_not_an_error():
    assert run({"GITHUB_APP_ID": "1", "GITHUB_APP_PRIVATE_KEY_PATH": "/nonexistent/key.pem"})[0] == "False"


def test_the_blueprint_declares_every_variable_the_integration_reads():
    text = open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "render.yaml"), encoding="utf-8").read()
    for name in ("GITHUB_APP_ID", "GITHUB_APP_SLUG", "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_WEBHOOK_SECRET"):
        assert f"key: {name}" in text, f"render.yaml does not declare {name}"
