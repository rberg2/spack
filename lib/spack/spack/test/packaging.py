# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

"""
This test checks the binary packaging infrastructure
"""
import os
import stat
import sys
import shutil
import pytest
import argparse

from llnl.util.filesystem import mkdirp

import spack.repo
import spack.store
import spack.binary_distribution as bindist
import spack.cmd.buildcache as buildcache
import spack.util.gpg
from spack.spec import Spec
from spack.paths import mock_gpg_keys_path
from spack.fetch_strategy import URLFetchStrategy, FetchStrategyComposite
from spack.relocate import needs_binary_relocation, needs_text_relocation
from spack.relocate import strings_contains_installroot
from spack.relocate import get_patchelf, relocate_text, relocate_links
from spack.relocate import substitute_rpath, get_relative_rpaths
from spack.relocate import macho_replace_paths, macho_make_paths_relative
from spack.relocate import modify_macho_object, macho_get_paths


def fake_fetchify(url, pkg):
    """Fake the URL for a package so it downloads from a file."""
    fetcher = FetchStrategyComposite()
    fetcher.append(URLFetchStrategy(url))
    pkg.fetcher = fetcher


@pytest.mark.usefixtures('install_mockery', 'mock_gnupghome')
def test_buildcache(mock_archive, tmpdir):
    # tweak patchelf to only do a download
    spec = Spec("patchelf")
    spec.concretize()
    pkg = spack.repo.get(spec)
    fake_fetchify(pkg.fetcher, pkg)
    mkdirp(os.path.join(pkg.prefix, "bin"))
    patchelfscr = os.path.join(pkg.prefix, "bin", "patchelf")
    f = open(patchelfscr, 'w')
    body = """#!/bin/bash
echo $PATH"""
    f.write(body)
    f.close()
    st = os.stat(patchelfscr)
    os.chmod(patchelfscr, st.st_mode | stat.S_IEXEC)

    # Install the test package
    spec = Spec('trivial-install-test-package')
    spec.concretize()
    assert spec.concrete
    pkg = spec.package
    fake_fetchify(mock_archive.url, pkg)
    pkg.do_install()
    pkghash = '/' + spec.dag_hash(7)

    # Put some non-relocatable file in there
    filename = os.path.join(spec.prefix, "dummy.txt")
    with open(filename, "w") as script:
        script.write(spec.prefix)

    # Create an absolute symlink
    linkname = os.path.join(spec.prefix, "link_to_dummy.txt")
    os.symlink(filename, linkname)

    # Create the build cache  and
    # put it directly into the mirror
    mirror_path = os.path.join(str(tmpdir), 'test-mirror')
    spack.mirror.create(mirror_path, specs=[])

    # register mirror with spack config
    mirrors = {'spack-mirror-test': 'file://' + mirror_path}
    spack.config.set('mirrors', mirrors)

    stage = spack.stage.Stage(
        mirrors['spack-mirror-test'], name="build_cache", keep=True)
    stage.create()

    # setup argument parser
    parser = argparse.ArgumentParser()
    buildcache.setup_parser(parser)

    # Create a private key to sign package with if gpg2 available
    if spack.util.gpg.Gpg.gpg():
        spack.util.gpg.Gpg.create(name='test key 1', expires='0',
                                  email='spack@googlegroups.com',
                                  comment='Spack test key')
        # Create build cache with signing
        args = parser.parse_args(['create', '-d', mirror_path, str(spec)])
        buildcache.buildcache(parser, args)

        # Uninstall the package
        pkg.do_uninstall(force=True)

        # test overwrite install
        args = parser.parse_args(['install', '-f', str(pkghash)])
        buildcache.buildcache(parser, args)

        files = os.listdir(spec.prefix)

        # create build cache with relative path and signing
        args = parser.parse_args(
            ['create', '-d', mirror_path, '-f', '-r', str(spec)])
        buildcache.buildcache(parser, args)

        # Uninstall the package
        pkg.do_uninstall(force=True)

        # install build cache with verification
        args = parser.parse_args(['install', str(spec)])
        buildcache.install_tarball(spec, args)

        # test overwrite install
        args = parser.parse_args(['install', '-f', str(pkghash)])
        buildcache.buildcache(parser, args)

    else:
        # create build cache without signing
        args = parser.parse_args(
            ['create', '-d', mirror_path, '-f', '-u', str(spec)])
        buildcache.buildcache(parser, args)

        # Uninstall the package
        pkg.do_uninstall(force=True)

        # install build cache without verification
        args = parser.parse_args(['install', '-u', str(spec)])
        buildcache.install_tarball(spec, args)

        files = os.listdir(spec.prefix)
        assert 'link_to_dummy.txt' in files
        assert 'dummy.txt' in files
        # test overwrite install without verification
        args = parser.parse_args(['install', '-f', '-u', str(pkghash)])
        buildcache.buildcache(parser, args)

        # create build cache with relative path
        args = parser.parse_args(
            ['create', '-d', mirror_path, '-f', '-r', '-u', str(pkghash)])
        buildcache.buildcache(parser, args)

        # Uninstall the package
        pkg.do_uninstall(force=True)

        # install build cache
        args = parser.parse_args(['install', '-u', str(spec)])
        buildcache.install_tarball(spec, args)

        # test overwrite install
        args = parser.parse_args(['install', '-f', '-u', str(pkghash)])
        buildcache.buildcache(parser, args)

        files = os.listdir(spec.prefix)
        assert 'link_to_dummy.txt' in files
        assert 'dummy.txt' in files
        assert os.path.realpath(
            os.path.join(spec.prefix, 'link_to_dummy.txt')
        ) == os.path.realpath(os.path.join(spec.prefix, 'dummy.txt'))

    # Validate the relocation information
    buildinfo = bindist.read_buildinfo_file(spec.prefix)
    assert(buildinfo['relocate_textfiles'] == ['dummy.txt'])
    assert(buildinfo['relocate_links'] == ['link_to_dummy.txt'])

    args = parser.parse_args(['list'])
    buildcache.buildcache(parser, args)

    args = parser.parse_args(['list', '-f'])
    buildcache.buildcache(parser, args)

    args = parser.parse_args(['list', 'trivial'])
    buildcache.buildcache(parser, args)

    # Copy a key to the mirror to have something to download
    shutil.copyfile(mock_gpg_keys_path + '/external.key',
                    mirror_path + '/external.key')

    args = parser.parse_args(['keys'])
    buildcache.buildcache(parser, args)

    args = parser.parse_args(['keys', '-f'])
    buildcache.buildcache(parser, args)

    # unregister mirror with spack config
    mirrors = {}
    spack.config.set('mirrors', mirrors)
    shutil.rmtree(mirror_path)
    stage.destroy()

    # Remove cached binary specs since we deleted the mirror
    bindist._cached_specs = set()


def test_relocate_text(tmpdir):
    with tmpdir.as_cwd():
        # Validate the text path replacement
        old_dir = '/home/spack/opt/spack'
        filename = 'dummy.txt'
        with open(filename, "w") as script:
            script.write(old_dir)
            script.close()
        filenames = [filename]
        new_dir = '/opt/rh/devtoolset/'
        relocate_text(filenames, oldpath=old_dir, newpath=new_dir,
                      oldprefix=old_dir, newprefix=new_dir)
        with open(filename, "r")as script:
            for line in script:
                assert(new_dir in line)
        assert(strings_contains_installroot(filename, old_dir) is False)


def test_relocate_links(tmpdir):
    with tmpdir.as_cwd():
        old_dir = '/home/spack/opt/spack'
        filename = 'link.ln'
        old_src = os.path.join(old_dir, filename)
        os.symlink(old_src, filename)
        filenames = [filename]
        new_dir = '/opt/rh/devtoolset'
        relocate_links(filenames, old_dir, new_dir)
        assert os.path.realpath(filename) == os.path.join(new_dir, filename)


def test_needs_relocation():

    assert needs_binary_relocation('application', 'x-sharedlib')
    assert needs_binary_relocation('application', 'x-executable')
    assert not needs_binary_relocation('application', 'x-octet-stream')
    assert not needs_binary_relocation('text', 'x-')

    assert needs_text_relocation('text', 'x-')
    assert not needs_text_relocation('symbolic link to', 'x-')

    assert needs_binary_relocation('application', 'x-mach-binary')


def test_macho_paths():

    out = macho_make_paths_relative('/Users/Shares/spack/pkgC/lib/libC.dylib',
                                    '/Users/Shared/spack',
                                    ('/Users/Shared/spack/pkgA/lib',
                                     '/Users/Shared/spack/pkgB/lib',
                                     '/usr/local/lib'),
                                    ('/Users/Shared/spack/pkgA/libA.dylib',
                                     '/Users/Shared/spack/pkgB/libB.dylib',
                                     '/usr/local/lib/libloco.dylib'),
                                    '/Users/Shared/spack/pkgC/lib/libC.dylib')
    assert out == (['@loader_path/../../../../Shared/spack/pkgA/lib',
                    '@loader_path/../../../../Shared/spack/pkgB/lib',
                    '/usr/local/lib'],
                   ['@loader_path/../../../../Shared/spack/pkgA/libA.dylib',
                    '@loader_path/../../../../Shared/spack/pkgB/libB.dylib',
                    '/usr/local/lib/libloco.dylib'],
                   '@rpath/libC.dylib')

    out = macho_make_paths_relative('/Users/Shared/spack/pkgC/bin/exeC',
                                    '/Users/Shared/spack',
                                    ('/Users/Shared/spack/pkgA/lib',
                                     '/Users/Shared/spack/pkgB/lib',
                                     '/usr/local/lib'),
                                    ('/Users/Shared/spack/pkgA/libA.dylib',
                                     '/Users/Shared/spack/pkgB/libB.dylib',
                                     '/usr/local/lib/libloco.dylib'), None)

    assert out == (['@loader_path/../../pkgA/lib',
                    '@loader_path/../../pkgB/lib',
                    '/usr/local/lib'],
                   ['@loader_path/../../pkgA/libA.dylib',
                    '@loader_path/../../pkgB/libB.dylib',
                    '/usr/local/lib/libloco.dylib'], None)

    out = macho_replace_paths('/Users/Shared/spack',
                              '/Applications/spack',
                              ('/Users/Shared/spack/pkgA/lib',
                               '/Users/Shared/spack/pkgB/lib',
                               '/usr/local/lib'),
                              ('/Users/Shared/spack/pkgA/libA.dylib',
                               '/Users/Shared/spack/pkgB/libB.dylib',
                               '/usr/local/lib/libloco.dylib'),
                              '/Users/Shared/spack/pkgC/lib/libC.dylib')
    assert out == (['/Applications/spack/pkgA/lib',
                    '/Applications/spack/pkgB/lib',
                    '/usr/local/lib'],
                   ['/Applications/spack/pkgA/libA.dylib',
                    '/Applications/spack/pkgB/libB.dylib',
                    '/usr/local/lib/libloco.dylib'],
                   '/Applications/spack/pkgC/lib/libC.dylib')

    out = macho_replace_paths('/Users/Shared/spack',
                              '/Applications/spack',
                              ('/Users/Shared/spack/pkgA/lib',
                               '/Users/Shared/spack/pkgB/lib',
                               '/usr/local/lib'),
                              ('/Users/Shared/spack/pkgA/libA.dylib',
                               '/Users/Shared/spack/pkgB/libB.dylib',
                               '/usr/local/lib/libloco.dylib'),
                              None)
    assert out == (['/Applications/spack/pkgA/lib',
                    '/Applications/spack/pkgB/lib',
                    '/usr/local/lib'],
                   ['/Applications/spack/pkgA/libA.dylib',
                    '/Applications/spack/pkgB/libB.dylib',
                    '/usr/local/lib/libloco.dylib'],
                   None)


def test_elf_paths():
    out = get_relative_rpaths(
        '/usr/bin/test', '/usr',
        ('/usr/lib', '/usr/lib64', '/opt/local/lib'))
    assert out == ['$ORIGIN/../lib', '$ORIGIN/../lib64', '/opt/local/lib']

    out = substitute_rpath(
        ('/usr/lib', '/usr/lib64', '/opt/local/lib'), '/usr', '/opt')
    assert out == ['/opt/lib', '/opt/lib64', '/opt/local/lib']


@pytest.mark.skipif(sys.platform != 'darwin',
                    reason="only works with Mach-o objects")
def test_relocate_macho(tmpdir):
    with tmpdir.as_cwd():

        get_patchelf()  # this does nothing on Darwin

        rpaths, deps, idpath = macho_get_paths('/bin/bash')
        nrpaths, ndeps, nid = macho_make_paths_relative('/bin/bash', '/usr',
                                                        rpaths, deps, idpath)
        shutil.copyfile('/bin/bash', 'bash')
        modify_macho_object('bash',
                            rpaths, deps, idpath,
                            nrpaths, ndeps, nid)

        rpaths, deps, idpath = macho_get_paths('/bin/bash')
        nrpaths, ndeps, nid = macho_replace_paths('/usr', '/opt',
                                                  rpaths, deps, idpath)
        shutil.copyfile('/bin/bash', 'bash')
        modify_macho_object('bash',
                            rpaths, deps, idpath,
                            nrpaths, ndeps, nid)

        path = '/usr/lib/libncurses.5.4.dylib'
        rpaths, deps, idpath = macho_get_paths(path)
        nrpaths, ndeps, nid = macho_make_paths_relative(path, '/usr',
                                                        rpaths, deps, idpath)
        shutil.copyfile(
            '/usr/lib/libncurses.5.4.dylib', 'libncurses.5.4.dylib')
        modify_macho_object('libncurses.5.4.dylib',
                            rpaths, deps, idpath,
                            nrpaths, ndeps, nid)

        rpaths, deps, idpath = macho_get_paths(path)
        nrpaths, ndeps, nid = macho_replace_paths('/usr', '/opt',
                                                  rpaths, deps, idpath)
        shutil.copyfile(
            '/usr/lib/libncurses.5.4.dylib', 'libncurses.5.4.dylib')
        modify_macho_object(
            'libncurses.5.4.dylib',
            rpaths, deps, idpath,
            nrpaths, ndeps, nid)
