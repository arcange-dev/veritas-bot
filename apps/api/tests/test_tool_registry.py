"""The registry is the only thing standing between a model and the filesystem."""
import pytest

from core.errors import ApprovalRequired, DomainError
from execution.fake import FakeBackend
from tools.models import ToolInvocation
from tools.registry import DispatchContext, ToolDenied, ToolRegistry


@pytest.fixture
def backend():
    return FakeBackend()


@pytest.fixture
def handle(backend):
    from execution.base import SessionSpec

    return backend.create_session(SessionSpec(run_id="r1", organization_id="o1"))


@pytest.fixture
def ctx(backend, handle):
    return DispatchContext(
        backend=backend, handle=handle,
        allowed_tools={"read_file", "write_file", "list_dir", "run_command", "edit_file"},
    )


def test_tool_outside_allowlist_is_denied(ctx):
    with pytest.raises(ToolDenied):
        ToolRegistry().dispatch("create_pull_request", {}, ctx)


def test_unknown_tool_is_denied(ctx):
    with pytest.raises(ToolDenied):
        ToolRegistry().dispatch("format_disk", {}, ctx)


def test_invalid_arguments_are_rejected_before_execution(ctx):
    with pytest.raises(DomainError) as exc:
        ToolRegistry().dispatch("read_file", {"wrong": "shape"}, ctx)
    assert exc.value.code == "invalid_tool_args"


def test_destructive_tool_requires_approval(ctx):
    with pytest.raises(ApprovalRequired):
        ToolRegistry().dispatch("run_command", {"argv": ["echo", "hi"]}, ctx)


def test_destructive_tool_runs_once_approved(ctx):
    ctx.approval_checked = {"run_command"}
    out = ToolRegistry().dispatch("run_command", {"argv": ["echo", "hello"]}, ctx)
    assert out["exit_code"] == 0
    assert "hello" in out["stdout"]


def test_write_then_read_roundtrip(ctx):
    registry = ToolRegistry()
    registry.dispatch("write_file", {"path": "src/app.py", "content": "print(1)\n"}, ctx)
    out = registry.dispatch("read_file", {"path": "src/app.py"}, ctx)
    assert out["content"] == "print(1)\n"


def test_edit_refuses_when_target_text_is_absent(ctx):
    registry = ToolRegistry()
    registry.dispatch("write_file", {"path": "a.txt", "content": "hello\n"}, ctx)
    with pytest.raises(DomainError) as exc:
        registry.dispatch("edit_file", {"path": "a.txt", "find": "nope", "replace": "x"}, ctx)
    assert exc.value.code == "edit_target_missing"


@pytest.mark.django_db
def test_every_dispatch_writes_an_audit_row(ctx):
    ToolRegistry().dispatch("list_dir", {"path": "."}, ctx)
    row = ToolInvocation.objects.get(tool_name="list_dir")
    assert row.allowed is True
    assert row.args_hash


@pytest.mark.django_db
def test_denied_dispatch_is_audited_too(ctx):
    with pytest.raises(ToolDenied):
        ToolRegistry().dispatch("run_tests", {}, ctx)
    row = ToolInvocation.objects.get(tool_name="run_tests")
    assert row.allowed is False
    assert "allowlist" in row.denied_reason


def test_secrets_in_arguments_are_redacted_in_the_audit_preview(ctx):
    from tools.registry import redact_args

    preview = redact_args({"api_key": "sk-super-secret-value", "path": "a.py"})
    assert preview["path"] == "a.py"
    assert "sk-super-secret-value" not in str(preview)
    assert preview["api_key"].startswith("[redacted")
