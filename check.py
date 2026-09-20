"""`astro-tagger check`: verify the setup end to end, including every configured agent."""
import importlib
from datetime import datetime, timezone

from . import paths
from .config import load_agents, load_config
from .errors import AstroTaggerError, PlaceholderRequired
from .state import compute_state, resolve_observer


def run(args) -> int:
    bad = 0

    def line(kind, msg):
        nonlocal bad
        if kind == "FAIL":
            bad += 1
        print(f"[{kind:>4}] {msg}")

    def has(mod):
        try:
            importlib.import_module(mod)
            return True
        except Exception:
            return False

    print(f"Home: {paths.home()}")
    if has("skyfield"):
        line("OK", "skyfield")
    else:
        line("FAIL", "skyfield missing (pip install -r requirements.txt)")
    for mod, why in (("PIL", "EXIF timestamps"), ("pypdf", "PDF timestamps")):
        line("OK" if has(mod) else "WARN", mod if has(mod) else f"{mod} missing: {why} will be unavailable")

    line("OK" if paths.config_path().is_file() else "FAIL", f"config: {paths.config_path()}")
    line("OK" if paths.agents_path().is_file() else "WARN", f"agents: {paths.agents_path()}")
    line("OK" if paths.kernel_index_path().is_file() else "FAIL", f"kernel index: {paths.kernel_index_path()}")

    try:
        cfg = load_config()
        site = cfg.earth_site(None)
        line("OK", f"site: {site.lat_deg}, {site.lon_deg}, {site.h_m} m")
    except AstroTaggerError as e:
        line("FAIL", str(e))
        print(f"\n{bad} problem(s) to fix.")
        return 1

    now = datetime.now(timezone.utc)
    agent_ids = list(load_agents()) or [cfg.agent_id]
    for aid in agent_ids:
        try:
            obs = resolve_observer(aid, cfg)
            rec = compute_state(now, "modern", obs)
            r = rec["state"]["r_m"]
            line("OK", f"agent {aid}: {rec['method']} via {rec['ephemeris']} (|r| = {sum(x * x for x in r) ** 0.5:.3e} m)")
        except PlaceholderRequired:
            line("SKIP", f"agent {aid}: needs --allow-placeholder (no trajectory support)")
        except AstroTaggerError as e:
            line("FAIL", f"agent {aid}: {e}")

    print("\nAll good." if bad == 0 else f"\n{bad} problem(s) to fix.")
    return 1 if bad else 0
