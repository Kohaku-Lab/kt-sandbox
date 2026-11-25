"""Unit tests for :mod:`kt_sandbox.manager.builder`."""

from pathlib import Path

import kt_sandbox
from kt_sandbox.manager import builder


class TestPrepareContext:
    def test_the_packaged_recipe_is_complete(self, tmp_path):
        builder.prepare_context(tmp_path)
        dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "useradd" in dockerfile and "PYTHONPATH=/opt/kt-sandbox" in dockerfile
        assert "wrap kt_sandbox.server kt-sandbox-mcp;" in dockerfile
        assert "wrap kt_sandbox kt-sandbox;" in dockerfile
        tiers = {path.stem for path in (tmp_path / "apt").glob("*.txt")}
        assert tiers == {"slim", "render", "dev", "media", "browser"}
        assert {path.stem for path in (tmp_path / "pip").glob("*.txt")} >= {
            "slim",
            "data",
        }

    def test_every_tier_ships_usage_notes(self, tmp_path):
        builder.prepare_context(tmp_path)
        tiers = {path.stem for path in (tmp_path / "apt").glob("*.txt")}
        tiers |= {path.stem for path in (tmp_path / "pip").glob("*.txt")}
        notes = {path.stem for path in (tmp_path / "notes").glob("*.md")}
        assert notes == tiers == {"slim", "data", "render", "dev", "media", "browser"}
        for note in (tmp_path / "notes").glob("*.md"):
            text = note.read_text(encoding="utf-8")
            assert text.strip() and len(text.splitlines()) <= 12, note.name
            assert not text.lstrip().startswith("#"), note.name

    def test_the_image_records_its_tiers_and_has_the_about_command(self, tmp_path):
        builder.prepare_context(tmp_path)
        dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert "COPY notes /tmp/notes" in dockerfile
        assert "/usr/local/share/kt-sandbox/tiers" in dockerfile
        assert "wrap kt_sandbox.server.about kt-sandbox-about;" in dockerfile
        assert dockerfile.index("/usr/local/share/kt-sandbox") < dockerfile.index(
            "USER sandbox"
        )

    def test_the_image_installs_only_the_runtime_requirements(self, tmp_path):
        builder.prepare_context(tmp_path)

        def requirements(name: str) -> list[str]:
            text = (tmp_path / name).read_text(encoding="utf-8")
            return [
                line.split(">")[0].split("=")[0].split("<")[0].lower()
                for line in text.splitlines()
                if line.strip() and not line.startswith("#")
            ]

        assert requirements(builder.RUNTIME_REQUIREMENTS) == [
            "mcp",
            "aiofiles",
            "jinja2",
            "kohakuvault",
            "pathspec",
            "pillow",
            "pyyaml",
        ]
        assert requirements(builder.RUNTIME_NO_DEPS) == ["kohakuterrarium"]
        dockerfile = (tmp_path / "Dockerfile").read_text(encoding="utf-8")
        assert f"pip install -r /tmp/{builder.RUNTIME_REQUIREMENTS}" in dockerfile
        assert f"pip install --no-deps -r /tmp/{builder.RUNTIME_NO_DEPS}" in dockerfile
        assert "pip install kt-sandbox" not in dockerfile

    def test_the_kohakuterrarium_in_the_image_is_one_the_host_extra_allows(self):
        pin = (builder.BUILD_DIR / builder.RUNTIME_NO_DEPS).read_text(encoding="utf-8")
        version = pin.split("kohakuterrarium==")[1].split()[0]
        major, minor, _ = (int(part) for part in version.split("."))
        assert (major, minor) >= (2, 2) and major < 3

    def test_the_installed_package_is_copied_without_bytecode(self, tmp_path):
        (builder.PACKAGE_DIR / "__pycache__").mkdir(exist_ok=True)
        builder.prepare_context(tmp_path)
        package = tmp_path / "kt_sandbox"
        assert (package / "server" / "app.py").is_file()
        assert (package / "__main__.py").is_file()
        assert (package / "server" / "__main__.py").is_file()
        assert not list(package.rglob("__pycache__"))
        assert not list(package.rglob("*.pyc"))

    def test_the_package_is_found_from_its_own_location(self):
        assert builder.PACKAGE_DIR == Path(kt_sandbox.__file__).resolve().parent

    def test_the_image_recipe_is_inside_the_package_so_a_wheel_carries_it(self):
        assert builder.BUILD_DIR.parent.name == "manager"
        assert (builder.BUILD_DIR / "Dockerfile").is_file()
        assert (builder.BUILD_DIR / builder.RUNTIME_REQUIREMENTS).is_file()
        assert (builder.BUILD_DIR / builder.RUNTIME_NO_DEPS).is_file()
        assert sorted(p.name for p in (builder.BUILD_DIR / "notes").glob("*.md"))


class TestBuildCommand:
    def test_a_plain_build(self, tmp_path):
        command = builder.build_command(tmp_path, tag="img:1")
        assert command[:3] == ["docker", "build", "-t"] and command[3] == "img:1"
        assert command[-1] == str(tmp_path)
        assert not any(arg.startswith("KT_SANDBOX_SPEC") for arg in command)

    def test_tiers_and_packages_become_build_arguments(self, tmp_path):
        command = builder.build_command(
            tmp_path,
            tag="t",
            extras=["data", "render"],
            apt=["tmux", "git"],
            pip=["duckdb"],
            base="python:3.13-slim",
        )
        assert "EXTRAS=data,render" in command
        assert "EXTRA_APT=tmux git" in command and "EXTRA_PIP=duckdb" in command
        assert "BASE=python:3.13-slim" in command

    def test_platform_or_push_switches_to_buildx(self, tmp_path):
        command = builder.build_command(
            tmp_path, tag="t", platform="linux/amd64,linux/arm64", push=True
        )
        assert command[:3] == ["docker", "buildx", "build"]
        assert command[command.index("--platform") + 1] == "linux/amd64,linux/arm64"
        assert "--push" in command

    def test_without_extras_no_empty_arguments_are_passed(self, tmp_path):
        command = builder.build_command(tmp_path, tag="t")
        assert not any(
            arg.startswith(("EXTRAS=", "EXTRA_APT=", "EXTRA_PIP=")) for arg in command
        )
