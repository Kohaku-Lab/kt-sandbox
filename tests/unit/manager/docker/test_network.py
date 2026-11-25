"""Unit tests for the pure parts of :mod:`kt_sandbox.manager.docker.network`."""

import io
import json
import tarfile
from types import SimpleNamespace

from kt_sandbox.levels.presets import build_level
from kt_sandbox.manager.docker import network


def sandbox(name, net, allow, secret=None):
    env = [f"KT_SANDBOX_EGRESS_SECRET={secret}"] if secret else ["PATH=/bin"]
    return SimpleNamespace(
        labels={
            "kt-sandbox.name": name,
            "kt-sandbox.network": net,
            "kt-sandbox.allow": json.dumps(allow),
        },
        attrs={"Config": {"Env": env}},
    )


class TestPolicyEntries:
    def test_only_allowlist_sandboxes_with_a_credential_are_listed(self):
        found = network.policy_entries(
            [
                sandbox("a", "allowlist", ["pypi.org"], "sa"),
                sandbox("b", "none", [], None),
                sandbox("c", "open", [], None),
                sandbox("d", "allowlist", ["x.org"], None),
            ]
        )
        assert found == [{"name": "a", "secret": "sa", "allow": ["pypi.org"]}]

    def test_each_sandbox_keeps_its_own_hosts(self):
        found = network.policy_entries(
            [
                sandbox("a", "allowlist", ["pypi.org"], "sa"),
                sandbox("b", "allowlist", ["github.com", "x.org"], "sb"),
            ]
        )
        assert {e["name"]: e["allow"] for e in found} == {
            "a": ["pypi.org"],
            "b": ["github.com", "x.org"],
        }

    def test_no_sandboxes_is_an_empty_table(self):
        assert network.policy_entries([]) == []


class TestHelpers:
    def test_secrets_are_long_and_unique(self):
        secrets = {network.new_secret() for _ in range(50)}
        assert len(secrets) == 50 and all(len(s) >= 20 for s in secrets)

    def test_the_policy_file_travels_as_a_tar(self):
        data = network._tar_of("egress.json", b'{"sandboxes": []}')
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            member = archive.getmember("egress.json")
            assert archive.extractfile(member).read() == b'{"sandboxes": []}'

    def test_a_level_without_the_allowlist_needs_no_proxy_and_no_credential(self):
        assert network.prepare(None, build_level("strict"), "img", "lab") == ""
        assert network.prepare(None, build_level("open"), "img", "lab") == ""
