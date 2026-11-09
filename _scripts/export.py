#!/usr/bin/env python3
"""
Export Cordra search hits as Digital Objects (full=True).

Port of cordra-config/scripts/meta-export.py (cordra_client based). Connection
settings come from _scripts/.env (see .env_example).

Usage:
  python export.py -q 'type:Vocabulary' -o output/vocabularies.json
"""

import argparse
import json
import math
import os
import sys

from cordra_client import Cordra, CordraConfigError
from lib import libcordra_utils
from lib.libreporting import ConsoleReporter, HarvestAbort, emit_critical


def main(config, query, output, batch_size, protocol=None, reporter=None):
    protocol = libcordra_utils.resolve_protocol(config, protocol)
    try:
        cordra = Cordra(**libcordra_utils.cordra_kwargs(config, protocol=protocol))
    except CordraConfigError as exc:
        emit_critical(reporter, str(exc), category="cordra_connect")

    number_of_hits = cordra.query_count(query)
    pages = math.ceil(number_of_hits / batch_size)

    print(f"Fetching {number_of_hits} Digital Objects...", flush=True)
    hits = []
    for page in range(pages):
        response = cordra.query(query, page_num=page, page_size=batch_size, full=True)
        hits.extend(response)
        print(f"  - Page {page + 1} of {pages}: {len(hits)} hits", flush=True)

    out_dir = os.path.dirname(output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(output, 'w', encoding='utf-8') as f:
        json.dump(hits, f, indent=4, ensure_ascii=False)
    print(f"Wrote the results to {output}", flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Export Cordra search hits as Digital Objects (attributes.content / elements).",
    )
    parser.add_argument('-q', '--query', dest='query', action='store', help='Query to export', required=True)
    parser.add_argument('-o', '--output', dest='output', action='store', help='Output file', required=True)
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
        main(config, args.query, args.output, batch_size, protocol=args.protocol, reporter=reporter)
    except HarvestAbort:
        sys.exit(1)
