import argparse
from phx_basics.git.phx_git_repository import PhxGitRepository


if __name__ == '__main__':
    DESCRIPTION = "This script is intended to download file from repo from input file with format: \'path#hash\';\n"\
                  "e.g.: python3 git_files_downloader.py https://github.com phx-tp/phx_basics.git string \"src/phx_basics/config/easy_config.py#d360f92\" out_test -f"
    parser = argparse.ArgumentParser(description=DESCRIPTION, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("server", help=f"Address of Git server, e.g. https://github.com or git@gitlab.cloud...", type=str)
    parser.add_argument("repository", help=f"Repository path e.g. phx-tp/phx_basics.git", type=str)
    parser.add_argument("mode", help="Input mode, 'string' means list of addresses as input, 'file' means file with each address on a line",
                        choices=[x.value for x in PhxGitRepository.InputMode])
    parser.add_argument("input", help="Input strings or input files - git addresses like '<path_to_file>#<commit>'", nargs="+")
    parser.add_argument("output_dir", help="Path to output directory, where all files will be stored.")
    parser.add_argument("-r", "--repository_dir", help=f"Folder containing the repository (to avoid cloning) e.g. /tmp/repositories", default=None)
    parser.add_argument("-f", "--full_path", help="Preserve directory structure that's on the server", default=False, action='store_true')
    args = parser.parse_args()

    PhxGitRepository(repository=args.repository, server=args.server, repo_path=args.repository_dir).download_files(
        args.mode, args.input, args.output_dir, use_sub_dirs=args.full_path)
