import json
import pathlib
import tomllib
from unittest.mock import MagicMock, patch

import pytest

from netbox_mcp_server.netbox_client import NetBoxRestClient
from netbox_mcp_server.netbox_write_client import (
    SCRIPT_DOCS_URL,
    SCRIPT_FILENAME,
    DryRunError,
    DryRunUnavailableError,
    NetBoxWriteClient,
    packaged_script_path,
)

SCRIPT_URL = (
    "http://netbox.example.com/api/extras/scripts/netbox_mcp_server_extended.MCPWriteValidator/"
)
JOB_URL = "http://netbox.example.com/api/core/jobs/7/"

NON_JSON = object()


@pytest.fixture
def client():
    return NetBoxRestClient(url="http://netbox.example.com", token="test-token")


@pytest.fixture
def write_client(client):
    return NetBoxWriteClient(client, dry_run_timeout=2.0, poll_interval=0.01)


def make_response(status_code=200, json_data=None, text=""):
    response = MagicMock()
    response.status_code = status_code
    response.is_success = 200 <= status_code < 300
    response.text = text
    if json_data is NON_JSON:
        response.json.side_effect = ValueError("not JSON")
    else:
        response.json.return_value = json_data if json_data is not None else {}
    response.raise_for_status = MagicMock()
    return response


def job_response(mock_post, *, valid=True, errors=None, detail="", status="completed", nonce=None):
    """Build a terminal job response echoing the nonce the client POSTed."""
    sent_nonce = mock_post.call_args.kwargs["json"]["data"]["nonce"]
    output = json.dumps(
        {
            "mcp_dry_run": {
                "valid": valid,
                "errors": errors or [],
                "detail": detail,
                "nonce": nonce if nonce is not None else sent_nonce,
            }
        }
    )
    return make_response(200, {"status": {"value": status}, "data": {"output": output, "log": []}})


class TestRealWrites:
    def test_real_create_posts_directly(self, client, write_client):
        resp = make_response(201, {"id": 1, "name": "test-site"})
        with patch.object(client.session, "post", return_value=resp) as mock_post:
            result = write_client.create(
                "dcim/sites", "dcim.site", {"name": "test-site"}, dry_run=False
            )
        mock_post.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/", json={"name": "test-site"}
        )
        assert result == {"id": 1, "name": "test-site"}

    def test_real_update_patches_correct_url(self, client, write_client):
        resp = make_response(200, {"id": 5, "name": "updated"})
        with patch.object(client.session, "patch", return_value=resp) as mock_patch:
            result = write_client.update(
                "dcim/sites", "dcim.site", 5, {"name": "updated"}, dry_run=False
            )
        mock_patch.assert_called_once_with(
            "http://netbox.example.com/api/dcim/sites/5/", json={"name": "updated"}
        )
        assert result == {"id": 5, "name": "updated"}

    def test_real_delete_returns_true_on_204(self, client, write_client):
        resp = make_response(204)
        with patch.object(client.session, "delete", return_value=resp) as mock_delete:
            result = write_client.delete("dcim/sites", "dcim.site", 7, dry_run=False)
        mock_delete.assert_called_once_with("http://netbox.example.com/api/dcim/sites/7/")
        assert result is True


class TestDryRunFlow:
    def test_valid_create_returns_verdict(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(mock_post, detail="Would create")
            result = write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

        assert result["valid"] is True
        assert result["operation"] == "create"
        assert result["object_type"] == "dcim.site"
        assert "dry_run=False" in result["_dry_run"]
        body = mock_post.call_args.kwargs["json"]
        assert mock_post.call_args.args[0] == SCRIPT_URL
        assert body["commit"] is False
        assert body["data"]["operation"] == "create"
        assert body["data"]["object_type"] == "dcim.site"
        assert json.loads(body["data"]["payload"]) == {"name": "x"}
        mock_get.assert_called_with(JOB_URL)

    def test_invalid_payload_returns_errors(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(
                mock_post, valid=False, errors=["slug: This field is required."]
            )
            result = write_client.create("dcim/sites", "dcim.site", {}, dry_run=True)

        assert result["valid"] is False
        assert result["errors"] == ["slug: This field is required."]
        assert "FAILED" in result["_dry_run"]

    def test_verdict_repeats_object_id_for_update_and_delete(self, client, write_client):
        """README tells the user to confirm the object_id before committing."""
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(
                mock_post, detail="Would delete dcim.site id=5 (hq)"
            )
            deleted = write_client.delete("dcim/sites", "dcim.site", 5, dry_run=True)
            updated = write_client.update("dcim/sites", "dcim.site", 5, {"name": "y"}, dry_run=True)

        assert deleted["object_id"] == 5
        assert deleted["detail"] == "Would delete dcim.site id=5 (hq)"
        assert updated["object_id"] == 5

    def test_create_verdict_has_no_object_id(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(mock_post)
            result = write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

        assert "object_id" not in result

    def test_invalid_verdict_keeps_detail_and_object_id(self, client, write_client):
        """An invalid delete must still say which object it refused."""
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(
                mock_post,
                valid=False,
                errors=["Deletion blocked by dependent objects"],
                detail="Would delete dcim.site id=5 (hq)",
            )
            result = write_client.delete("dcim/sites", "dcim.site", 5, dry_run=True)

        assert result["valid"] is False
        assert result["object_id"] == 5
        assert result["detail"] == "Would delete dcim.site id=5 (hq)"
        assert result["errors"] == ["Deletion blocked by dependent objects"]

    def test_update_dry_run_sends_object_id(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(mock_post)
            write_client.update("dcim/sites", "dcim.site", 5, {"name": "y"}, dry_run=True)

        data = mock_post.call_args.kwargs["json"]["data"]
        assert data["operation"] == "update"
        assert data["object_id"] == 5

    def test_delete_dry_run_sends_no_payload(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(mock_post)
            result = write_client.delete("dcim/sites", "dcim.site", 7, dry_run=True)

        data = mock_post.call_args.kwargs["json"]["data"]
        assert data["operation"] == "delete"
        assert data["object_id"] == 7
        assert "payload" not in data
        assert result["valid"] is True

    def test_verdict_accepted_on_failed_job_status(self, client, write_client):
        # Some NetBox releases mark failed validations as 'failed' even with
        # commit=false; a parseable verdict must still be honored.
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(
                mock_post, valid=False, errors=["bad"], status="failed"
            )
            result = write_client.create("dcim/sites", "dcim.site", {}, dry_run=True)

        assert result["valid"] is False
        assert result["errors"] == ["bad"]

    def test_nonce_mismatch_raises(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        with (
            patch.object(client.session, "post", return_value=post_resp) as mock_post,
            patch.object(client.session, "get") as mock_get,
        ):
            mock_get.side_effect = lambda url: job_response(mock_post, nonce="someone-elses")
            with pytest.raises(DryRunError, match="does not match this request"):
                write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_job_without_verdict_raises_with_log_tail(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        job = make_response(
            200,
            {
                "status": {"value": "errored"},
                # Mixed log-entry shapes must not crash the tail builder.
                "data": {"output": None, "log": [{"message": "boom"}, ["warning", "odd"]]},
            },
        )
        with (
            patch.object(client.session, "post", return_value=post_resp),
            patch.object(client.session, "get", return_value=job),
            pytest.raises(DryRunError, match="no usable verdict") as exc,
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)
        assert "boom" in str(exc.value)


class TestDryRunUnavailable:
    def test_packaged_script_path_points_at_a_real_file(self):
        """The 404 message must name a file the user actually has."""
        path = packaged_script_path()
        assert path != SCRIPT_DOCS_URL, "validator script not found in package or checkout"
        assert "class MCPWriteValidator" in pathlib.Path(path).read_text()

    def test_build_ships_the_validator_script(self):
        """Guard the packaging: dry runs fail closed without this file (#39)."""
        pyproject = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
        config = tomllib.loads(pyproject.read_text())
        wheel = config["tool"]["hatch"]["build"]["targets"]["wheel"]
        included = wheel["force-include"]
        assert f"netbox_scripts/{SCRIPT_FILENAME}" in included
        assert included[f"netbox_scripts/{SCRIPT_FILENAME}"].startswith("netbox_mcp_server/")
        sdist = config["tool"]["hatch"]["build"]["targets"]["sdist"]
        assert "netbox_scripts" in sdist["include"]

    def test_missing_script_names_the_local_copy(self, client, write_client):
        resp = make_response(404, text="Not found.")
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunUnavailableError, match="SCRIPTS_ROOT") as excinfo,
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)
        assert packaged_script_path() in str(excinfo.value)

    def test_missing_script_404(self, client, write_client):
        resp = make_response(404, text="Not found.")
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunUnavailableError, match=r"extras\.run_script"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_post_403_names_run_permission(self, client, write_client):
        resp = make_response(403, text="You do not have permission.")
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunUnavailableError, match=r"extras\.run_script"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    @pytest.mark.parametrize("status_code", [503, 400])
    def test_no_rq_worker(self, client, write_client, status_code):
        resp = make_response(
            status_code, text="Unable to process request: RQ worker process not running."
        )
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunUnavailableError, match="RQ worker"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_poll_403_names_job_permission(self, client, write_client):
        post_resp = make_response(200, {"result": {"id": 7}})
        poll_resp = make_response(403, text="forbidden")
        with (
            patch.object(client.session, "post", return_value=post_resp),
            patch.object(client.session, "get", return_value=poll_resp),
            pytest.raises(DryRunUnavailableError, match=r"core\.view_job"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_timeout_when_job_never_finishes(self, client):
        write_client = NetBoxWriteClient(client, dry_run_timeout=0.05, poll_interval=0.01)
        post_resp = make_response(200, {"result": {"id": 7}})
        running = make_response(200, {"status": {"value": "running"}, "data": None})
        with (
            patch.object(client.session, "post", return_value=post_resp),
            patch.object(client.session, "get", return_value=running),
            pytest.raises(DryRunUnavailableError, match="did not finish"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_non_json_script_response_raises(self, client, write_client):
        resp = make_response(200, NON_JSON, text="<html>proxy page</html>")
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunError, match="non-JSON"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_missing_job_in_response_raises(self, client, write_client):
        resp = make_response(200, {"result": None})
        with (
            patch.object(client.session, "post", return_value=resp),
            pytest.raises(DryRunError, match="no job"),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)

    def test_dry_run_never_falls_back_to_real_write(self, client, write_client):
        resp = make_response(404, text="Not found.")
        with (
            patch.object(client.session, "post", return_value=resp) as mock_post,
            patch.object(client.session, "patch") as mock_patch,
            patch.object(client.session, "delete") as mock_delete,
            pytest.raises(DryRunUnavailableError),
        ):
            write_client.create("dcim/sites", "dcim.site", {"name": "x"}, dry_run=True)
        # The only POST is the script execution; no write endpoint was touched.
        assert mock_post.call_count == 1
        assert mock_post.call_args.args[0] == SCRIPT_URL
        mock_patch.assert_not_called()
        mock_delete.assert_not_called()
