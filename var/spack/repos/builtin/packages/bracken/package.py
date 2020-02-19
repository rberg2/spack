# Copyright 2013-2020 Lawrence Livermore National Security, LLC and other
# Spack Project Developers. See the top-level COPYRIGHT file for details.
#
# SPDX-License-Identifier: (Apache-2.0 OR MIT)

from spack import *
import os


class Bracken(Package):
    """Bracken (Bayesian Reestimation of Abundance with KrakEN) is a highly
    accurate statistical method that computes the abundance of species in DNA
    sequences from a metagenomics sample."""

    homepage = "https://ccb.jhu.edu/software/bracken"
    url      = "https://github.com/jenniferlu717/Bracken/archive/v2.5.3.tar.gz"

    version('2.5.3', sha256='a0bb8f3bcbf8e91f32a1f7bc194e85519b2263743b1fc10917b6f29a68e93f8e')
    version('1.0.0', sha256='8ee736535ad994588339d94d0db4c0b1ba554a619f5f96332ee09f2aabdfe176',
            url='https://github.com/jenniferlu717/Bracken/archive/1.0.0.tar.gz')

    depends_on('perl', type=('build', 'link', 'run'))
    depends_on('python@2.7:', type=('build', 'link', 'run'))
    depends_on('perl-exporter-tiny')
    depends_on('perl-list-moreutils')
    depends_on('perl-parallel-forkmanager')

    @when('@:1')
    def install(self, spec, prefix):
        mkdirp(prefix.bin)
        install_tree('sample_data', prefix.sample_data)

        filter_file(
            r'#!/bin/env perl',
            '#!/usr/bin/env perl',
            'count-kmer-abundances.pl'
        )

        filter_file(
            r'#!/usr/bin/python',
            '#!/usr/bin/env {0}'.format(
                os.path.basename(self.spec['python'].command.path)),
            'est_abundance.py'
        )

        filter_file(
            r'#!/usr/bin/python',
            '#!/usr/bin/env {0}'.format(
                os.path.basename(self.spec['python'].command.path)),
            'generate_kmer_distribution.py'
        )

        files = (
            'count-kmer-abundances.pl',
            'est_abundance.py',
            'generate_kmer_distribution.py',
        )

        chmod = which('chmod')
        for name in files:
            install(name, prefix.bin)
            chmod('+x', join_path(self.prefix.bin, name))

    @when('@:2.5')
    def install(self, spec, prefix):
        chmod = which('chmod')
        chmod('+x', './install_bracken.sh')
        installer = Executable('./install_bracken.sh')
        installer(self.stage.source_path)
        mkdirp(prefix.bin)
        mkdirp(prefix.bin.src)
        install_tree('sample_data', prefix.sample_data)

        files = (
            'bracken',
            'bracken-build'
        )

        srcfiles = (
            'kreport2mpa.py',
            'generate_kmer_distribution.py',
            'est_abundance.py',
            'kmer2read_distr'
        )

        for name in files:
            install(name, prefix.bin)
            chmod('+x', join_path(self.prefix.bin, name))

        for name in srcfiles:
            install("src/" + name, prefix.bin.src)
            chmod('+x', join_path(self.prefix.bin.src, name))
