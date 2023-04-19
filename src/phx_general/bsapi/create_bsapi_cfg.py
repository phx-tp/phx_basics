#!/usr/bin/env python
# -*- coding: UTF-8 -*-
import logging
import os
import re
import shutil
from tempfile import TemporaryDirectory
from typing import Iterable

import jinja2
import argparse

from phx_general.git.phx_git_repository import PhxGitRepository
from phx_general.file import list2file, file2dict, mkpdirp


class Technologies:
    """
    Class defining BSAPI technologies
    """
    STT = "stt"
    STT_ONLINE = "stt_online"
    KWS = "kws"
    KWS_ONLINE = "kws_online"
    G2P = "g2p"
    PHNREC = "phnrec"

    templates = {
        STT:         "apps/stt/templates/stt_6.bs.jinja2#master",
        STT_ONLINE:  "apps/stt/templates/stt_online_6.bs.jinja2#master",
        KWS:         "apps/kws/templates/kws_6.bs.jinja2#master",
        KWS_ONLINE:  "apps/kws/templates/kws_online_6.bs.jinja2#master",
        G2P:         "apps/kws/templates/g2p.bs.jinja2#master",
        PHNREC:      "apps/kws/templates/phnrec_6.bs.jinja2#master",
    }

    @staticmethod
    def get_values():
        return [v for (k, v) in Technologies.__dict__.items() if k == k.upper()]


class ConfigGenerator:
    def __init__(self, technology, label, version, output_path, params_files=None, params=None, novad=False,
                 nocalib=False, g2p_dont_report_errors_immediately=False, template_file=None, unknown_words_model=False,
                 classes=False, grammar=False, phx_gitlab_server=PhxGitRepository.DEFAULT_PHX_GITLAB_SERVER):
        """
        Creates *.bs configuration file out of template jinja file downloaded directly from BSAPI repository
        @param technology One of values in Technologies - decides what template to use
        @param label Descriptive label of model (e.g. 'cs_cz, en_us' or 'opt' for temporary cfgs in pipelines)
        @param version string of version for model
        @param output_path Name of output *.bs file
        @param params_files Files with parameters/variables for jinja templates in format "key"="value" e.g. lm_scale=2
        @param params Dictionary with parameters for jinja templates, overrides param_files
        @param novad Disables vad - valid only for offline STT
        @param nocalib Disables calibration - valid only for offline KWS
        @param template_file If specified, template is not downloaded from GIT, the one provided gets used directly
        @param phx_gitlab_server Use this server to download data from gitlab
        """
        assert technology in Technologies.get_values()
        self.technology = technology
        with TemporaryDirectory() as tmpdir:
            template_name = re.sub("#.*", "", os.path.basename(Technologies.templates[self.technology]))
            if template_file:
                shutil.copy(template_file, os.path.join(tmpdir, template_name))
            else:
                PhxGitRepository(server=phx_gitlab_server, repository='bsapi')\
                    .download_files('string', [Technologies.templates[self.technology]], tmpdir)
            template = jinja2.Environment(autoescape=False, loader=jinja2.FileSystemLoader(tmpdir))\
                .get_template(template_name)
            self.variables2render = {"label": label, "version": version}
            if params_files:
                for pf in params_files:
                    parameters = file2dict(pf, sep="=")
                    if not self.variables2render.keys().isdisjoint(parameters.keys()):
                        logging.warning(f"The loaded parameters {pf} override these values: "
                                        f"{set(self.variables2render.keys()).intersection(parameters.keys())}")
                    self.variables2render.update(parameters)
            if params:
                if not self.variables2render.keys().isdisjoint(params.keys()):
                    logging.warning(f"The loaded parameters '{params}' override these values: "
                                    f"{set(self.variables2render.keys()).intersection(parameters.keys())}")
                self.variables2render.update(params)
            self.set_variable2render(novad, "novad", {Technologies.STT})
            self.set_variable2render(nocalib, "nocalib", {Technologies.KWS})
            self.set_variable2render(unknown_words_model, "unknown_words_model",
                                     {Technologies.STT, Technologies.STT_ONLINE})
            self.set_variable2render(classes, "class_adaptation", {Technologies.STT, Technologies.STT_ONLINE})
            self.set_variable2render(grammar, "numeric_grammar", {Technologies.STT, Technologies.STT_ONLINE})
            cfg = template.render(self.variables2render).split(os.linesep)
            if g2p_dont_report_errors_immediately:
                if self.technology != Technologies.G2P:
                    raise ValueError(f"'g2p_ignore_untranslatable' option is available only for G2P instead of "
                                     f"'{self.technology}'")
                cfg = [line.replace("report_errors_immediately=true", "report_errors_immediately=false")
                       for line in cfg]
            mkpdirp(output_path)
            list2file(output_path, cfg)

    def set_variable2render(self, local_variable, rendering_variable, allowed_technologies):
        assert isinstance(allowed_technologies, Iterable)
        if local_variable:
            if self.technology not in allowed_technologies:
                raise ValueError(f"Can't set '{rendering_variable}' variable in '{self.technology}'. This parameter is "
                                 f"supported only in {allowed_technologies}")
            if rendering_variable in self.variables2render:
                logging.warning(f"Variable '{rendering_variable}' is already present. Resetting to 'True'")
            self.variables2render[rendering_variable] = True


def main():
    description = "This script is intended to generating BSAPI 5G configurations."
    parser = argparse.ArgumentParser(description=description, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("technology", help="Phonexia technology", choices=Technologies.get_values())
    parser.add_argument("label",
                        help="ISO abreviation of language in lowercase and generation separated by '_' eg.: cs_cz_5")
    parser.add_argument("output_config_path", help="Path to output configuration file")
    parser.add_argument("--version", help="Version of model.", default='x.x.x')
    parser.add_argument("--params", help="File containing parameters of BSAPI config. In format 'key'='value'",
                        default=None, nargs="+")
    parser.add_argument("--novad",
                        help=f"Setup sourcing VAD segmentation from files. Usable only for technology "
                             f"'{Technologies.STT}'",
                        action="store_true", default=False)
    parser.add_argument("--nocalib",
                        help=f"Don't use calibration vector in KWS. Usable only for technology '{Technologies.KWS}'",
                        action="store_true", default=False)
    parser.add_argument("--classes",
                        help=f"Use classes in STT. Usable only for technologies '{Technologies.STT, Technologies.STT_ONLINE}'",
                        action="store_true", default=False)
    parser.add_argument("--grammar",
                        help=f"Use numeric grammar in STT. Usable only for technologies '{Technologies.STT, Technologies.STT_ONLINE}'",
                        action="store_true", default=False)
    parser.add_argument("--g2p_dont_report_errors_immediately",
                        help=f"Set report_errors_immediately=false. Usable only for technology '{Technologies.G2P}'",
                        action="store_true", default=False)
    parser.add_argument("--template_cfg", help="File containing config template in jinja2 format.", default=None)
    parser.add_argument("--unknown_words_model",
                        help=f"Use unknown words model configuration. Usable only for technology '{Technologies.STT}'",
                        action="store_true", default=False)
    args = parser.parse_args()
    ConfigGenerator(args.technology, args.label, args.version, args.output_config_path, args.params,
                    novad=args.novad,
                    nocalib=args.nocalib,
                    g2p_dont_report_errors_immediately=args.g2p_dont_report_errors_immediately,
                    template_file=args.template_cfg,
                    unknown_words_model=args.unknown_words_model,
                    classes=args.classes, grammar=args.grammar)


if __name__ == '__main__':
    main()

