import re
import os
import logging
import shutil
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory, NamedTemporaryFile
from typing import Union, Iterable

from typeguard import typechecked

from phx_secure.gitlab import SecurePhxGitRepository
from phx_basics.file import file2list
from phx_basics.shell import shell

from phx_basics.type import PathType

_logger = logging.getLogger(__name__)

@typechecked
class PhxGitRepository(SecurePhxGitRepository):

    DELIMITER = '#'
    DEFAULT_PHX_GITLAB_SERVER = 'git@gitlab.int.phonexia.com'

    KNOWN_PHX_REPOSITORIES = {
        'bsapi':        "CORE-team/BSAPI.git",       #  34,  #
        'asr':          "ASR-team/ASR-tools.git",    #  39,  #
        'dictionaries': "ASR-team/dictionaries.git", # 228,  #
        'datasets':     "ASR-team/datasets-lfs.git", # 469,  #
        'datasets-old': "ASR-team/datasets.git",     # 323,  # #fallback option for datasets
        'glms':         "ASR-team/glms.git",         # 342,  #
        'grammars':     "ASR-team/grammars.git"
    }

    class InputMode(Enum):
        FILE = "file"
        STRING = "string"

    def __init__(self,
                 server: str = DEFAULT_PHX_GITLAB_SERVER,
                 repository: str = None,
                 repo_path: Union[str, None] = None):
        """
        @param server:     GitLab server to clone repository from
        @param repository: Which repository to search to obtain necessary files
        @param repo_path:  Instead of cloning repository into some temp, locate it in this folder and checkout necessary
                           commit to copy the files that are wanted
        """
        self._server = server

        if repo_path:
            os.makedirs(repo_path, exist_ok=True)
        self._repo_path = repo_path

        if repository not in PhxGitRepository.KNOWN_PHX_REPOSITORIES:
            raise ValueError(f"Unknown git repository id '{repository}' - use one of strings from known "
                             f"repositories: '{PhxGitRepository.KNOWN_PHX_REPOSITORIES.keys()}'")

        self._repository = PhxGitRepository.KNOWN_PHX_REPOSITORIES[repository]

    def download_files(self, mode: str, input: Union[PathType, Iterable[PathType]], output_dir, use_sub_dirs=False):
        """
        @param mode One of InputMode enum's values
        @param input Either a list of strings (git paths) or list of files with git paths (one per line)
        @param use_sub_dirs (bool) join full path from input with output dir
        @param output_dir Directory where downloaded files are stored, note that paths to file in repository are not
                         preserved inside the output directory
        """

        os.makedirs(output_dir, exist_ok=True)
        input_strings = list()
        if mode == PhxGitRepository.InputMode.FILE.value:
            for file in input:
                assert Path(file).is_file(), file
                input_strings.extend(file2list(file))
        elif mode == PhxGitRepository.InputMode.STRING.value:
            input_strings = str(input)
        else:
            raise ValueError("Unknown mode option")

        if self._repo_path:
            _logger.debug(f"Download files from repository in {self._repo_path}")
            # use existing directory
            self._download_files(input_strings, output_dir, self._repo_path, use_sub_dirs)
        else:
            _logger.debug(f"Clone repository {self._repository} into temporary directory")
            # create temporary directory for cloning the git repository
            with TemporaryDirectory() as tmpdir:
                self._download_files(input_strings, output_dir, tmpdir, use_sub_dirs)

    def _download_files(self, input_strings, output_dir, repo_path, use_sub_dirs):
        self._clone_if_needed(repo_path)
        repo_path = os.path.join(repo_path, self._repository_dir())
        os.makedirs(output_dir, exist_ok=True)
        downloaded_files = set()
        for git_path in input_strings:
            # shell commands output files
            checkout_stderr = os.path.join(repo_path, "git_checkout.stderr")
            lfs_stdout = os.path.join(repo_path, "git_lfs_pull.stdout")
            try:
                _logger.debug(f"Git-downloading '{git_path}' from repo path '{repo_path}'")
                path, commit = git_path.split(self.DELIMITER)

                # Checkout correct commit
                shell(['git', 'fetch', '--quiet'], cwd=repo_path)
                shell(['git', 'checkout', commit, '--quiet'], cwd=repo_path, stderr=checkout_stderr)

                if self._is_lfs_repository():
                    # For LFS repository pull the needed objects
                    shell([' '.join(['git', 'lfs', 'pull', f'--include="{path}"', '--exclude=""'])],
                           stdout=lfs_stdout, cwd=repo_path, shell=True)

                # Copy file
                output_path = os.path.join(output_dir, path if use_sub_dirs else os.path.basename(path))
                if output_path in downloaded_files:
                    raise ValueError(f"File with basename '{os.path.basename(path)}' would be stored multiple times in"
                                     f"'{output_dir}' - cancelling download")
                if os.path.exists(output_path):
                    shutil.rmtree(output_path, ignore_errors=True)
                downloaded_path = os.path.join(repo_path, path)
                if os.path.isdir(downloaded_path):
                    shutil.copytree(downloaded_path, output_path)
                else:
                    os.makedirs(os.path.dirname(output_path), exist_ok=True)
                    shutil.copy2(downloaded_path, output_path)
                downloaded_files.add(output_path)
            except Exception as e:
                try:
                    reference_is_not_a_tree = any(
                        [l.find("reference is not a tree") != -1 for l in file2list(checkout_stderr)])
                    if reference_is_not_a_tree and self._download_dataset_fallback(git_path, output_dir, repo_path,
                                                                                   use_sub_dirs):
                        # if fallback for datasets was succesfull - ignore former error
                        continue
                except ValueError:
                    pass
                raise RuntimeError(f"Error fetching '{git_path}' from GIT: {e}")
            finally:
                # remove temporary files (our shell() func doesn't allow output to dummy string io)
                shutil.rmtree(checkout_stderr, ignore_errors=True)
                shutil.rmtree(lfs_stdout, ignore_errors=True)

    def _is_lfs_repository(self):
        if self._repository in [self.KNOWN_PHX_REPOSITORIES['datasets']]:
            return True
        return False

    def _clone_if_needed(self, path):
        if not os.path.exists(os.path.join(path, self._repository_dir())):
            _logger.debug(f"Cloning git repository {self._repository}")
            if ":" in self._server:
                repo = f"{self._server}/{self._repository}"
            else:
                repo = f"{self._server}:{self._repository}"
            shell(['git', 'clone', repo, '--quiet'], cwd=path)

    def _repository_dir(self):
        return self._repository.split("/")[-1].replace(".git", "")

    def _download_dataset_fallback(self, git_path, output_dir, repo_path, use_sub_dirs):
        if self._repository != self.KNOWN_PHX_REPOSITORIES['datasets']:
            # other than datasets repository don't have fallback option
            return False

        self._repository = self.KNOWN_PHX_REPOSITORIES['datasets-old']
        try:
            _logger.warning(f"Fallback to old version of datasets for {git_path} - download may take a long time")
            self._download_files([git_path], output_dir, repo_path, use_sub_dirs)
        except Exception as e:
            # could not download the file from the old datasets repository
            return False
        finally:
            # don't forget to return the correct value for self._repository after fallback
            self._repository = self.KNOWN_PHX_REPOSITORIES['datasets']

        return True

    def get_git_path_commit_hash(self, file_repository_path):
        commit = PhxGitRepository.get_git_path_commit(file_repository_path)
        if self._repo_path:
            _logger.debug(f"Get last commit hash in {self._repo_path} for commit name {commit}")
            return self._get_git_path_commit_hash(commit, self._repo_path)
        else:
            _logger.debug(f"Clone repository {self._repository} into temporary directory")
            # create temporary directory for cloning the git repository
            with TemporaryDirectory() as tmpdir:
                return self._get_git_path_commit_hash(commit, tmpdir)

    def _get_git_path_commit_hash(self, commit, repo_path):
        self._clone_if_needed(repo_path)
        repo_path = os.path.join(repo_path, self._repository_dir())
        shell(['git', 'checkout', commit, '--quiet'], cwd=repo_path)
        with NamedTemporaryFile('w', dir=repo_path, delete=False) as tmpf:
            shell(['git', 'rev-parse', 'HEAD'], cwd=repo_path, stdout=tmpf.name)
            tmpf.flush()
            commit_hash = file2list(tmpf.name)[0]
        return commit_hash


    @staticmethod
    def is_git_path(path, may_have_branch_name=False):
        """
        Returns true if a path seems to be a path into gitlab repository
        """
        if may_have_branch_name:
            return re.match("^.*#[0-9a-zA-Z-_]+$", path) is not None
        else:
            return re.match("^.*#[0-9a-f]+$", path) is not None

    @staticmethod
    def join_git_path(repository_path, path):
        """
        Joins a REPOSITORY path with normal one.
        e.g.  join_git_path("some/dir#abcde", "path/to/file") returns "some/dir/path/to/file#abcde"
        """
        path_git = repository_path.split('#')[0]
        commit = repository_path.split('#')[1]
        return f"{os.path.join(path_git, path)}#{commit}"

    @staticmethod
    def get_git_path_fullpath(repository_path):
        path = repository_path
        if '#' in repository_path:
            path = repository_path.split('#')[0]

        return path

    @staticmethod
    def get_git_path_basename(repository_path):
        return os.path.basename(PhxGitRepository.get_git_path_fullpath(repository_path))

    @staticmethod
    def get_git_path_commit(repository_path):
        if '#' not in repository_path:
            raise ValueError(f"Path '{repository_path}' is not git path in format <path>#<hash_of_commit>")

        return repository_path.split('#')[1]

    @classmethod
    def get_default_phx_repository(cls, repository_name: str):
        return f"{cls.DEFAULT_PHX_GITLAB_SERVER}:{cls.KNOWN_PHX_REPOSITORIES[repository_name]}"
