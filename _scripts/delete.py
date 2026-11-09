#!/usr/bin/env python3
"""
Delete all Cordra digital objects matching a query.

Port of cordra-config/scripts/delete-dos.py (cordra_client based). Connection
settings come from _scripts/.env (see .env_example).

Usage:
  python delete.py -q 'type:Sample'
  python delete.py -q 'type:Sample' -y --batch-size 100
  python delete.py -q 'type:Sample' --protocol doip
"""

import argparse
import sys

from cordra_client import Cordra, CordraConfigError, CordraError
from lib import libcordra_utils
from lib.libreporting import ConsoleReporter, HarvestAbort, emit_critical, reporter_or_null


def main(config, query, batch_size, include_versions=False, no_confirmation=False, protocol=None, reporter=None):
    rep = reporter_or_null(reporter)
    protocol = libcordra_utils.resolve_protocol(config, protocol)
    print('Query: ' + query)

    try:
        cordra = Cordra(**libcordra_utils.cordra_kwargs(config, protocol=protocol))
    except CordraConfigError as exc:
        emit_critical(rep, str(exc), category="cordra_connect")

    number_of_results = cordra.query_count(query, include_versions)
    print('Number of results: ' + str(number_of_results), flush=True)

    if not no_confirmation:
        confirmation = input('Are you sure you want to delete ' + str(number_of_results) + ' objects? (y/n) ')
        if confirmation.lower() != 'y':
            print('Aborting', flush=True)
            sys.exit(0)

    failed_ids = set()
    i = 0
    while True:
        print(f"  - deleting objects {batch_size*i}-{batch_size*i+batch_size}", flush=True)
        object_ids = cordra.query(
            query=query,
            page_num=0,
            page_size=batch_size,
            ids=True,
            include_versions=include_versions,
        )
        to_delete = [obj_id for obj_id in object_ids if obj_id not in failed_ids]

        if not to_delete:
            if object_ids:
                rep.emit(
                    "error",
                    f"Stopping: {len(failed_ids)} object(s) could not be deleted",
                    category="batch_error",
                )
            break

        for obj_id in to_delete:
            try:
                cordra.delete(obj_id)
            except CordraError as exc:
                failed_ids.add(obj_id)
                rep.emit(
                    "error",
                    f"Failed to delete object: {exc}",
                    category="batch_error",
                    record_id=obj_id,
                )

        if len(object_ids) < batch_size:
            break
        else:
            i += 1

    if failed_ids:
        rep.emit(
            "info",
            f"Completed with {len(failed_ids)} failed delete(s)",
        )

    print("Done...\n", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Delete all Cordra digital objects matching a query.")
    parser.add_argument('-q', '--query', dest='query', action='store', help='Query string to filter digital objects to be deleted', required=True)
    parser.add_argument('-i', '--include-versions', dest='include_versions', action='store_true', help='Include versions in the query')
    parser.add_argument('-y', '--skip-confirmation', dest='no_confirmation', action='store_true', help="do not ask for confirmation")
    parser.add_argument('--protocol', choices=['doip', 'rest'], default=None, help="Cordra protocol (default: CORDRA_PROTOCOL from .env, else rest).")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Override batch size (default: CORDRA_DEFAULT_BATCH_SIZE from .env, else 250).",
    )
    args = parser.parse_args()

    config = libcordra_utils.load_env_config()
    print(f"Cordra instance: {config['url']}", flush=True)

    batch_size = libcordra_utils.resolve_batch_size(config, args.batch_size)
    reporter = ConsoleReporter()
    try:
        main(config, args.query, batch_size, args.include_versions, args.no_confirmation, protocol=args.protocol, reporter=reporter)
    except HarvestAbort:
        sys.exit(1)
