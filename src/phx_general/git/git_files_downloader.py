import argparse
from general.git.phx_git_repository import PhxGitRepository


if __name__ == '__main__':
    DESCRIPTION = "This script is intended to download file from repo from input file with format: \'path#hash\'"
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("repository", help=f"One of '{PhxGitRepository.KNOWN_PHX_REPOSITORIES.keys()}'")
    parser.add_argument("mode", help="Input mode", choices=[x.value for x in PhxGitRepository.InputMode])
    parser.add_argument("input", help="Input strings or input files - git addresses like '<path_to_file>#<commit>'", nargs="+")
    parser.add_argument("output_dir", help="Path to output directory, where all files will be stored.")
    parser.add_argument("-s", "--server", help=f"Address of PHX Gitlab server", default=PhxGitRepository.DEFAULT_PHX_GITLAB_SERVER)
    parser.add_argument("-r", "--repository_dir", help=f"Folder containing the repository (to avoid cloning) e.g. /tmp/repositories", default=None)
    parser.add_argument("-f", "--full_path", help="Use full path from input to output", default=False, action='store_true')
    args = parser.parse_args()

    PhxGitRepository(repository=args.repository, server=args.server, repo_path=args.repository_dir).download_files(
        args.mode, args.input, args.output_dir, use_sub_dirs=args.full_path)
