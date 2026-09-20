"""Command-line entry point: `astro-tagger <command>` or `python -m astro_tagger <command>`."""
import argparse
import sys

from . import __version__
from .errors import AstroTaggerError


def _run_tag(args):
    from .tag import run
    return run(args)


def _run_state(args):
    from .statelog import run
    return run(args)


def _run_kernels(args):
    from .kernels import run
    return run(args)


def _run_check(args):
    from .check import run
    return run(args)


def _common() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--policy", default="modern",
                   help="ephemeris policy: modern (default), legacy, longspan, closest, or one you defined")
    p.add_argument("--agent", help="agent id from config/agents.json; sets where the observer is")
    p.add_argument("--lat", type=float, help="override site latitude (Earth sites)")
    p.add_argument("--lon", type=float, help="override site longitude (Earth sites)")
    p.add_argument("--alt", type=float, help="override site altitude in metres (Earth sites)")
    p.add_argument("--allow-placeholder", action="store_true",
                   help="allow an Earth-site placeholder for expedition vessels (no trajectory support yet)")
    p.add_argument("--no-sanity", "--no_sanity", dest="sanity", action="store_false",
                   help="skip the plausibility check on computed positions")
    return p


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astro-tagger",
        description="Stamp files with ephemeris-anchored provenance sidecars.")
    parser.add_argument("--version", action="version", version=f"astro-tagger {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True, metavar="command")
    common = _common()

    t = sub.add_parser("tag", parents=[common], help="write .astro.json sidecars next to files")
    t.add_argument("paths", nargs="+", help="files or globs")
    t.add_argument("--utc", help="override the timestamp, e.g. 1978-06-12T15:30:00Z")
    t.add_argument("--label", action="store_true", help="also write <file>.label.txt and print it")
    t.set_defaults(func=_run_tag)

    s = sub.add_parser("state", parents=[common], help="append state records to logs/states-DATE.jsonl")
    s.add_argument("utc", nargs="?", help="UTC time (default: now)")
    s.add_argument("--mission-id", "--mission_id", dest="mission_id")
    s.add_argument("--mission-phase", "--mission_phase", dest="mission_phase")
    s.add_argument("--travel-mode", "--travel_mode", dest="travel_mode", choices=["classical", "runner"],
                   help="vessels only; overrides agents.json")
    s.add_argument("--fps", type=float, help="burst mode: records per second (needs --frames)")
    s.add_argument("--frames", type=int, help="burst mode: number of records (needs --fps)")
    s.set_defaults(func=_run_state)

    k = sub.add_parser("kernels", help="fetch and index ephemeris kernels")
    ksub = k.add_subparsers(dest="kernels_cmd", required=True, metavar="action")
    kf = ksub.add_parser("fetch", help="download kernels (default: de440s), then index them")
    kf.add_argument("names", nargs="*", help="de440s, de440, de421")
    ksub.add_parser("index", help="(re)build kernels/index.json from the .bsp files present")
    ksub.add_parser("list", help="show policies and indexed kernels")
    k.set_defaults(func=_run_kernels)

    c = sub.add_parser("check", help="verify the setup end to end")
    c.set_defaults(func=_run_check)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.cmd == "state" and bool(args.fps) != bool(args.frames):
        parser.error("burst mode needs both --fps and --frames")
    if args.cmd == "state" and args.fps is not None and args.fps <= 0:
        parser.error("--fps must be positive")
    if args.cmd == "state" and args.frames is not None and args.frames < 1:
        parser.error("--frames must be at least 1")
    if args.cmd == "tag" and args.utc:
        from .tag import parse_utc
        try:
            parse_utc(args.utc)
        except ValueError:
            parser.error(f"--utc: cannot parse '{args.utc}' (use e.g. 1978-06-12T15:30:00Z)")
    try:
        return args.func(args) or 0
    except AstroTaggerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except ModuleNotFoundError as e:
        if (e.name or "").split(".")[0] != "skyfield":
            raise
        print("error: Skyfield is not installed. Run: pip install -r requirements.txt", file=sys.stderr)
        return 1
