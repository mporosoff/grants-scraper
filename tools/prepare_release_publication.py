"""Prepare and review an immutable publication before changing serving state."""
import argparse

from tools.publish_release_candidate import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'receipt', 'reports', 'artifact-run'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    prepare(args.bundle, args.receipt, args.reports, args.artifact_run)


if __name__ == '__main__':
    main()
