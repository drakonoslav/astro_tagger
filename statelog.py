"""`astro-tagger state`: append state records to logs/states-YYYY-MM-DD.jsonl."""
import json
import sys
from datetime import datetime, timedelta, timezone

from . import paths
from .config import load_config
from .errors import NoCoverageError
from .state import compute_state, resolve_observer
from .tag import parse_utc


def append_jsonl(path, obj: dict) -> None:
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")


def run(args) -> int:
    cfg = load_config(cli_site={"lat_deg": args.lat, "lon_deg": args.lon, "alt_m": args.alt})
    obs = resolve_observer(args.agent, cfg, travel_mode=args.travel_mode)
    start = parse_utc(args.utc) if args.utc else datetime.now(timezone.utc)
    n = args.frames or 1
    step = timedelta(seconds=1.0 / args.fps) if args.fps else timedelta(0)

    logs = paths.logs_dir()
    logs.mkdir(parents=True, exist_ok=True)

    last, last_path = None, None
    try:
        for i in range(n):
            dt = start + i * step
            rec = compute_state(dt, args.policy, obs, sanity=args.sanity,
                                allow_placeholder=args.allow_placeholder,
                                mission_id=args.mission_id, mission_phase=args.mission_phase)
            last_path = logs / f"states-{dt.date().isoformat()}.jsonl"
            append_jsonl(last_path, rec)
            last = rec
    except NoCoverageError as e:
        print(f"error: {e}", file=sys.stderr)
        print("       Try --policy longspan, or fetch another kernel: astro-tagger kernels fetch de440", file=sys.stderr)
        return 1

    what = f"{n} records" if n > 1 else "state"
    print(f"Appended {what} -> {last_path}")
    print(f"UTC:      {last['time']['utc']}")
    print(f"Agent:    {last['agent']}")
    print(f"Method:   {last['method']}" + ("  [PLACEHOLDER]" if last["observer_is_placeholder"] else ""))
    print(f"Frames:   {', '.join(last['frames_present'])}")
    print(f"Ephem:    {last['ephemeris']}")
    print(f"Policy:   {args.policy}")
    print(f"SHA256:   {last['ephemeris_sha256'][:16]}...")
    return 0
