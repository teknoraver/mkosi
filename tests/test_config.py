# SPDX-License-Identifier: LGPL-2.1+

import argparse
import itertools
import operator
from pathlib import Path
from typing import Optional

import pytest

from mkosi.architecture import Architecture
from mkosi.config import Compression, OutputFormat, Verb, parse_config, parse_ini
from mkosi.distributions import Distribution
from mkosi.util import chdir


def test_compression_enum_creation() -> None:
    assert Compression("none") == Compression.none
    assert Compression("zst") == Compression.zst
    assert Compression("xz") == Compression.xz
    assert Compression("bz2") == Compression.bz2
    assert Compression("gz") == Compression.gz
    assert Compression("lz4") == Compression.lz4
    assert Compression("lzma") == Compression.lzma


def test_compression_enum_bool() -> None:
    assert bool(Compression.none) == False
    assert bool(Compression.zst)  == True
    assert bool(Compression.xz)   == True
    assert bool(Compression.bz2)  == True
    assert bool(Compression.gz)   == True
    assert bool(Compression.lz4)  == True
    assert bool(Compression.lzma) == True


def test_compression_enum_str() -> None:
    assert str(Compression.none) == "none"
    assert str(Compression.zst)  == "zst"
    assert str(Compression.xz)   == "xz"
    assert str(Compression.bz2)  == "bz2"
    assert str(Compression.gz)   == "gz"
    assert str(Compression.lz4)  == "lz4"
    assert str(Compression.lzma) == "lzma"


def test_parse_ini(tmp_path: Path) -> None:
    p = tmp_path / "ini"
    p.write_text(
        """\
        [MySection]
        Value=abc
        Other=def
        ALLCAPS=txt

        # Comment
        ; Another comment
        [EmptySection]
        [AnotherSection]
        EmptyValue=
        Multiline=abc
                    def
                    qed
                    ord
        """
    )

    g = parse_ini(p)

    assert next(g) == ("MySection", "Value", "abc")
    assert next(g) == ("MySection", "Other", "def")
    assert next(g) == ("MySection", "ALLCAPS", "txt")
    assert next(g) == ("AnotherSection", "EmptyValue", "")
    assert next(g) == ("AnotherSection", "Multiline", "abc\ndef\nqed\nord")


def test_parse_config(tmp_path: Path) -> None:
    d = tmp_path

    (d / "mkosi.conf").write_text(
        """\
        [Distribution]

        @Distribution = ubuntu
        Architecture  = arm64

        [Content]
        Packages=abc

        [Output]
        @Format = cpio
        ImageId = base
        """
    )

    with chdir(tmp_path):
        _, [config] = parse_config()

    assert config.distribution == Distribution.ubuntu
    assert config.architecture == Architecture.arm64
    assert config.packages == ["abc"]
    assert config.output_format == OutputFormat.cpio
    assert config.image_id == "base"

    with chdir(tmp_path):
        _, [config] = parse_config(["--distribution", "fedora", "--architecture", "x86-64"])

    # mkosi.conf sets a default distribution, so the CLI should take priority.
    assert config.distribution == Distribution.fedora
    # mkosi.conf sets overrides the architecture, so whatever is specified on the CLI should be ignored.
    assert config.architecture == Architecture.arm64

    d = d / "mkosi.conf.d"
    d.mkdir()

    (d / "d1.conf").write_text(
        """\
        [Distribution]
        Distribution = debian
        @Architecture = x86-64

        [Content]
        Packages = qed
                   def

        [Output]
        ImageId = 00-dropin
        ImageVersion = 0
        """
    )

    with chdir(tmp_path):
        _, [config] = parse_config()

    # Setting a value explicitly in a dropin should override the default from mkosi.conf.
    assert config.distribution == Distribution.debian
    # Setting a default in a dropin should be ignored since mkosi.conf sets the architecture explicitly.
    assert config.architecture == Architecture.arm64
    # Lists should be merged by appending the new values to the existing values.
    assert config.packages == ["abc", "qed", "def"]
    assert config.output_format == OutputFormat.cpio
    assert config.image_id == "00-dropin"
    assert config.image_version == "0"

    (tmp_path / "mkosi.version").write_text("1.2.3")

    (d / "d2.conf").write_text(
        """\
        [Content]
        Packages=
        """
    )

    with chdir(tmp_path):
        _, [config] = parse_config()

    # Test that empty string resets the list.
    assert config.packages == []
    # mkosi.version should only be used if no version is set explicitly.
    assert config.image_version == "0"

    (d / "d1.conf").unlink()

    with chdir(tmp_path):
        _, [config] = parse_config()

    # ImageVersion= is not set explicitly anymore, so now the version from mkosi.version should be used.
    assert config.image_version == "1.2.3"


def test_parse_load_verb(tmp_path: Path) -> None:
    with chdir(tmp_path):
        assert parse_config(["build"])[0].verb == Verb.build
        assert parse_config(["clean"])[0].verb == Verb.clean
        with pytest.raises(SystemExit):
            parse_config(["help"])
        assert parse_config(["genkey"])[0].verb == Verb.genkey
        assert parse_config(["bump"])[0].verb == Verb.bump
        assert parse_config(["serve"])[0].verb == Verb.serve
        assert parse_config(["build"])[0].verb == Verb.build
        assert parse_config(["shell"])[0].verb == Verb.shell
        assert parse_config(["boot"])[0].verb == Verb.boot
        assert parse_config(["qemu"])[0].verb == Verb.qemu
        with pytest.raises(SystemExit):
            parse_config(["invalid"])


def test_os_distribution(tmp_path: Path) -> None:
    with chdir(tmp_path):
        for dist in Distribution:
            _, [config] = parse_config(["-d", dist.name])
            assert config.distribution == dist

        with pytest.raises(tuple((argparse.ArgumentError, SystemExit))):
            parse_config(["-d", "invalidDistro"])
        with pytest.raises(tuple((argparse.ArgumentError, SystemExit))):
            parse_config(["-d"])

        for dist in Distribution:
            Path("mkosi.conf").write_text(f"[Distribution]\nDistribution={dist}")
            _, [config] = parse_config()
            assert config.distribution == dist


def test_parse_config_files_filter(tmp_path: Path) -> None:
    with chdir(tmp_path):
        confd = Path("mkosi.conf.d")
        confd.mkdir()

        (confd / "10-file.conf").write_text("[Content]\nPackages=yes")
        (confd / "20-file.noconf").write_text("[Content]\nPackages=nope")

        _, [config] = parse_config()
        assert config.packages == ["yes"]


def test_compression(tmp_path: Path) -> None:
    with chdir(tmp_path):
        _, [config] = parse_config(["--format", "disk", "--compress-output", "False"])
        assert config.compress_output == Compression.none


@pytest.mark.parametrize("dist1,dist2", itertools.combinations_with_replacement(Distribution, 2))
def test_match_distribution(tmp_path: Path, dist1: Distribution, dist2: Distribution) -> None:
    with chdir(tmp_path):
        parent = Path("mkosi.conf")
        parent.write_text(
            f"""\
            [Distribution]
            Distribution={dist1}
            """
        )

        Path("mkosi.conf.d").mkdir()

        child1 = Path("mkosi.conf.d/child1.conf")
        child1.write_text(
            f"""\
            [Match]
            Distribution={dist1}

            [Content]
            Packages=testpkg1
            """
        )
        child2 = Path("mkosi.conf.d/child2.conf")
        child2.write_text(
            f"""\
            [Match]
            Distribution={dist2}

            [Content]
            Packages=testpkg2
            """
        )
        child3 = Path("mkosi.conf.d/child3.conf")
        child3.write_text(
            f"""\
            [Match]
            Distribution=|{dist1}
            Distribution=|{dist2}

            [Content]
            Packages=testpkg3
            """
        )

        _, [conf] = parse_config()
        assert "testpkg1" in conf.packages
        if dist1 == dist2:
            assert "testpkg2" in conf.packages
        else:
            assert "testpkg2" not in conf.packages
        assert "testpkg3" in conf.packages


@pytest.mark.parametrize(
    "release1,release2", itertools.combinations_with_replacement([36, 37, 38], 2)
)
def test_match_release(tmp_path: Path, release1: int, release2: int) -> None:
    with chdir(tmp_path):
        parent = Path("mkosi.conf")
        parent.write_text(
            f"""\
            [Distribution]
            Distribution=fedora
            Release={release1}
            """
        )

        Path("mkosi.conf.d").mkdir()

        child1 = Path("mkosi.conf.d/child1.conf")
        child1.write_text(
            f"""\
            [Match]
            Release={release1}

            [Content]
            Packages=testpkg1
            """
        )
        child2 = Path("mkosi.conf.d/child2.conf")
        child2.write_text(
            f"""\
            [Match]
            Release={release2}

            [Content]
            Packages=testpkg2
            """
        )
        child3 = Path("mkosi.conf.d/child3.conf")
        child3.write_text(
            f"""\
            [Match]
            Release=|{release1}
            Release=|{release2}

            [Content]
            Packages=testpkg3
            """
        )

        _, [conf] = parse_config()
        assert "testpkg1" in conf.packages
        if release1 == release2:
            assert "testpkg2" in conf.packages
        else:
            assert "testpkg2" not in conf.packages
        assert "testpkg3" in conf.packages


@pytest.mark.parametrize(
    "image1,image2", itertools.combinations_with_replacement(
        ["image_a", "image_b", "image_c"], 2
    )
)
def test_match_imageid(tmp_path: Path, image1: str, image2: str) -> None:
    with chdir(tmp_path):
        parent = Path("mkosi.conf")
        parent.write_text(
            f"""\
            [Distribution]
            Distribution=fedora
            ImageId={image1}
            """
        )

        Path("mkosi.conf.d").mkdir()

        child1 = Path("mkosi.conf.d/child1.conf")
        child1.write_text(
            f"""\
            [Match]
            ImageId={image1}

            [Content]
            Packages=testpkg1
            """
        )
        child2 = Path("mkosi.conf.d/child2.conf")
        child2.write_text(
            f"""\
            [Match]
            ImageId={image2}

            [Content]
            Packages=testpkg2
            """
        )
        child3 = Path("mkosi.conf.d/child3.conf")
        child3.write_text(
            f"""\
            [Match]
            ImageId=|{image1}
            ImageId=|{image2}

            [Content]
            Packages=testpkg3
            """
        )
        child4 = Path("mkosi.conf.d/child4.conf")
        child4.write_text(
            """\
            [Match]
            ImageId=image*

            [Content]
            Packages=testpkg4
            """
        )

        _, [conf] = parse_config()
        assert "testpkg1" in conf.packages
        if image1 == image2:
            assert "testpkg2" in conf.packages
        else:
            assert "testpkg2" not in conf.packages
        assert "testpkg3" in conf.packages
        assert "testpkg4" in conf.packages


@pytest.mark.parametrize(
    "op,version", itertools.product(
        ["", "==", "<", ">", "<=", ">="],
        [122, 123, 124],
    )
)
def test_match_imageversion(tmp_path: Path, op: str, version: str) -> None:
    opfunc = {
        "==": operator.eq,
        "!=": operator.ne,
        "<": operator.lt,
        "<=": operator.le,
        ">": operator.gt,
        ">=": operator.ge,
    }.get(op, operator.eq,)

    with chdir(tmp_path):
        parent = Path("mkosi.conf")
        parent.write_text(
            """\
            [Distribution]
            ImageId=testimage
            ImageVersion=123
            """
        )

        Path("mkosi.conf.d").mkdir()
        child1 = Path("mkosi.conf.d/child1.conf")
        child1.write_text(
            f"""\
            [Match]
            ImageVersion={op}{version}

            [Content]
            Packages=testpkg1
            """
        )
        child2 = Path("mkosi.conf.d/child2.conf")
        child2.write_text(
            f"""\
            [Match]
            ImageVersion=<200
            ImageVersion={op}{version}

            [Content]
            Packages=testpkg2
            """
        )
        child3 = Path("mkosi.conf.d/child3.conf")
        child3.write_text(
            f"""\
            [Match]
            ImageVersion=>9000
            ImageVersion={op}{version}

            [Content]
            Packages=testpkg3
            """
        )

        _, [conf] = parse_config()
        assert ("testpkg1" in conf.packages) == opfunc(123, version)
        assert ("testpkg2" in conf.packages) == opfunc(123, version)
        assert "testpkg3" not in conf.packages


@pytest.mark.parametrize(
    "skel,pkgmngr", itertools.product(
        [None, Path("/foo"), Path("/bar")],
        [None, Path("/foo"), Path("/bar")],
    )
)
def test_package_manager_tree(tmp_path: Path, skel: Optional[Path], pkgmngr: Optional[Path]) -> None:
    with chdir(tmp_path):
        config = Path("mkosi.conf")
        with config.open("w") as f:
            f.write("[Content]\n")
            if skel is not None:
                f.write(f"SkeletonTrees={skel}\n")
            if pkgmngr is not None:
                f.write(f"PackageManagerTrees={pkgmngr}\n")

        _, [conf] = parse_config()

        skel_expected = [(skel, None)] if skel is not None else []
        pkgmngr_expected = [(pkgmngr, None)] if pkgmngr is not None else skel_expected

        assert conf.skeleton_trees == skel_expected
        assert conf.package_manager_trees == pkgmngr_expected
