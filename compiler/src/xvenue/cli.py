"""Command line. ``xvenue relate <file.rdsl> <idA> <idB>``."""

from __future__ import annotations

import argparse
import sys

from xvenue.errors import RDSLError
from xvenue.parser import parse_path
from xvenue.relate import format_report, relate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="xvenue")
    sub = parser.add_subparsers(dest="cmd", required=True)
    rel = sub.add_parser("relate", help="print the relation and divergent fields for two contracts")
    rel.add_argument("file", help="RDSL file")
    rel.add_argument("id_a", help="contract id of A")
    rel.add_argument("id_b", help="contract id of B")
    args = parser.parse_args(argv)
    try:
        specs = parse_path(args.file)
    except RDSLError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        detail = exc.strerror or str(exc)
        print(f"{args.file}: {detail}", file=sys.stderr)
        return 2
    by_id = {spec.contract_id: spec for spec in specs}
    missing = [name for name in (args.id_a, args.id_b) if name not in by_id]
    if missing:
        known = ", ".join(spec.contract_id for spec in specs)
        print(f"unknown contract id: {', '.join(missing)} (file has: {known})", file=sys.stderr)
        return 1
    sys.stdout.write(format_report(relate(by_id[args.id_a], by_id[args.id_b])))
    return 0
