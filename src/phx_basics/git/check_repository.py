import os
import argparse
import logging
from git import Repo


def report_error(msg, permissive):
    if permissive:
        logging.warning(msg)
    else:
        raise RuntimeError(msg)


def get_repository_hash(repository, permissive):
    r = Repo(repository)
    logging.info(f"Checking repository ${repository}")
    if r.is_dirty():
        report_error(f"Repository ${repository} is not clean!!! Commit your changes before running this script", permissive)

    if r.untracked_files:
        report_error(f"Repository ${repository} has untracked files!!! Commit your changes before running this script", permissive)

    return r.head.ref.log_entry(-1).newhexsha


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--input", help="Path to repository which should be checked", required=True)
    parser.add_argument("-o", "--output_hash", help="Path to file where repository's hash is written in case it's clean", default=None)
    parser.add_argument("-p", "--permissive", help="Useful for tests - do not throw error and end immediately, but just print warning", action='store_true')
    args = parser.parse_args()

    repo_hash = get_repository_hash(args.input, permissive=args.permissive)
    if not args.output_hash:
        exit(0)

    if os.path.exists(args.output_hash):
        os.remove(args.output_hash)
    with open(args.output_hash, 'w') as out:
        out.write(repo_hash)
