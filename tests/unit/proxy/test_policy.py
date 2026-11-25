"""Unit tests for :mod:`kt_sandbox.proxy.policy`."""

import base64
import json
import os
import time

import pytest

from kt_sandbox.proxy.policy import (
    Denied,
    Entry,
    Policy,
    host_allowed,
    parse_basic,
    split_target,
)


def basic(name, secret):
    return "Basic " + base64.b64encode(f"{name}:{secret}".encode()).decode()


class TestHelpers:
    def test_host_matching_covers_subdomains_but_not_lookalikes(self):
        allow = ("pypi.org", "github.com")
        assert host_allowed(allow, "pypi.org") and host_allowed(allow, "PyPI.org.")
        assert host_allowed(allow, "files.pypi.org") and host_allowed(
            allow, "api.github.com"
        )
        assert not host_allowed(allow, "evilpypi.org")
        assert not host_allowed(allow, "pypi.org.evil.com")
        assert not host_allowed((), "pypi.org")

    def test_basic_credentials(self):
        assert parse_basic(basic("bot", "s3:cret")) == ("bot", "s3:cret")
        for bad in (
            None,
            "",
            "Bearer x",
            "Basic !!!",
            "Basic " + base64.b64encode(b"nocolon").decode(),
        ):
            assert parse_basic(bad) is None

    def test_targets(self):
        assert split_target("pypi.org:443") == ("pypi.org", 443)
        assert split_target("pypi.org:80") == ("pypi.org", 80)
        assert split_target("pypi.org") == ("pypi.org", 443)
        assert split_target("[2001:db8::1]:443") == ("2001:db8::1", 443)


class TestAuthenticate:
    def policy(self):
        policy = Policy()
        policy.set_entries(
            [
                Entry("bot", "s3cret", ("pypi.org",)),
                Entry("dev", "other", ("github.com",)),
            ]
        )
        return policy

    def test_the_right_credential_selects_its_entry(self):
        assert self.policy().authenticate(basic("bot", "s3cret")).allow == ("pypi.org",)

    @pytest.mark.parametrize(
        "header",
        [
            None,
            "Basic nope",
            basic("bot", "wrong"),
            basic("ghost", "s3cret"),
            basic("bot", "other"),
        ],
    )
    def test_everything_else_is_407(self, header):
        with pytest.raises(Denied) as denied:
            self.policy().authenticate(header)
        assert denied.value.status == 407

    def test_the_table_reloads_when_the_file_changes(self, tmp_path):
        path = tmp_path / "egress.json"
        policy = Policy(path)
        with pytest.raises(Denied):
            policy.authenticate(basic("bot", "s3cret"))
        path.write_text(
            json.dumps(
                {
                    "sandboxes": [
                        {"name": "bot", "secret": "s3cret", "allow": ["pypi.org"]}
                    ]
                }
            )
        )
        assert policy.authenticate(basic("bot", "s3cret")).name == "bot"
        path.write_text(json.dumps({"sandboxes": []}))
        path.touch()

        os.utime(path, ns=(time.time_ns() + 10**9, time.time_ns() + 10**9))
        with pytest.raises(Denied):
            policy.authenticate(basic("bot", "s3cret"))

    def test_a_broken_file_keeps_the_last_good_table(self, tmp_path):
        path = tmp_path / "egress.json"
        path.write_text(
            json.dumps(
                {"sandboxes": [{"name": "bot", "secret": "s", "allow": ["a.org"]}]}
            )
        )
        policy = Policy(path)
        policy.authenticate(basic("bot", "s"))
        path.write_text("{not json")

        os.utime(path, ns=(time.time_ns() + 10**9,) * 2)
        assert policy.authenticate(basic("bot", "s")).name == "bot"


class TestResolve:
    entry = Entry("bot", "s", ("localhost", "example.org"))

    async def test_a_port_outside_the_list_is_refused_with_the_list(self):
        with pytest.raises(Denied, match="ports 80, 443") as denied:
            await Policy().resolve(self.entry, "example.org", 22)
        assert denied.value.status == 403

    async def test_a_host_outside_the_allowlist_is_refused_with_the_list(self):
        with pytest.raises(
            Denied, match="not in this sandbox's allowlist: localhost, example.org"
        ):
            await Policy().resolve(self.entry, "evil.com", 443)

    async def test_an_allowed_host_that_resolves_to_a_private_address_is_refused(self):
        with pytest.raises(Denied, match="non-public address") as denied:
            await Policy().resolve(self.entry, "localhost", 443)
        assert denied.value.status == 403

    async def test_the_private_block_can_be_lifted_for_tests(self):
        addresses = await Policy(allow_private=True).resolve(
            self.entry, "localhost", 443
        )
        assert addresses and set(addresses) <= {"127.0.0.1", "::1"}

    async def test_an_unresolvable_host_is_502(self):
        entry = Entry("bot", "s", ("no-such-host.invalid",))
        with pytest.raises(Denied) as denied:
            await Policy().resolve(entry, "no-such-host.invalid", 443)
        assert denied.value.status == 502
