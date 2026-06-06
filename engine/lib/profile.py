"""profile — the RUNTIME diagnostician.

`hunt` finds the bug in the source; `profile` finds it while the code runs. It
wraps a command (or attaches to a PID), samples the whole process tree, and —
unlike a passive sampler such as rescope — it *diagnoses*:

  * memory leak    : RSS trend fitted by least-squares; flagged on a sustained,
                     still-climbing slope (MB/min + R²), not a one-off delta.
  * fd / handle leak: open-descriptor count trending up over the run.
  * thread leak    : thread count growing without bound.
  * cpu bottleneck : one process pinned ~1 core while the rest sit idle
                     (a parallelization opportunity) vs healthy saturation.
  * gpu pressure   : utilization peak + VRAM growth (NVIDIA via nvidia-smi,
                     Apple Silicon via ioreg PerformanceStatistics).
  * orphan leak    : child processes still alive AFTER the command exits — a
                     post-run reconciliation no live sampler performs.

Output is a graded verdict (CLEAN / WARN / PROBLEM) with the offending pid and the
evidence, as md + json, mirroring `audit`. psutil powers full sampling; without it
the profiler degrades to a ps-based RSS/CPU view and says so.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import time

try:
    from . import common
except ImportError:
    import common

try:
    import psutil
except ImportError:  # degrades to ps-based sampling
    psutil = None


# ── least squares (no numpy dependency) ──────────────────────────────────────
def _trend(ts: list[float], ys: list[float]) -> tuple[float, float]:
    """Return (slope per unit t, R²) for ys ~ ts via ordinary least squares."""
    n = len(ts)
    if n < 3:
        return 0.0, 0.0
    mt = sum(ts) / n
    my = sum(ys) / n
    var = sum((t - mt) ** 2 for t in ts)
    if var == 0:
        return 0.0, 0.0
    slope = sum((t - mt) * (y - my) for t, y in zip(ts, ys)) / var
    ss_tot = sum((y - my) ** 2 for y in ys)
    if ss_tot == 0:
        return slope, 1.0
    ss_res = sum((y - (my + slope * (t - mt))) ** 2 for t, y in zip(ts, ys))
    return slope, max(0.0, 1.0 - ss_res / ss_tot)


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else 0.0


# ── GPU sampling (best-effort, degrades to None) ─────────────────────────────
def _gpu_available() -> str | None:
    if shutil.which("nvidia-smi"):
        return "nvidia"
    if shutil.which("ioreg"):  # Apple Silicon / macOS integrated GPU
        return "ioreg"
    return None


def _gpu_sample(kind: str | None) -> dict | None:
    if kind == "nvidia":
        cp = common.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            timeout=5,
        )
        if cp.returncode == 0 and cp.stdout.strip():
            first = cp.stdout.strip().splitlines()[0].split(",")
            try:
                return {
                    "util": float(first[0]),
                    "mem_mb": float(first[1]),
                    "mem_total_mb": float(first[2]),
                }
            except (ValueError, IndexError):
                return None
    elif kind == "ioreg":
        cp = common.run(["ioreg", "-r", "-c", "IOAccelerator", "-w", "0"], timeout=5)
        if cp.returncode == 0:
            import re

            util = re.search(r'"Device Utilization %"=(\d+)', cp.stdout)
            mem = re.search(r'"In use system memory"=(\d+)', cp.stdout)
            if util or mem:
                return {
                    "util": float(util.group(1)) if util else None,
                    "mem_mb": (float(mem.group(1)) / 1e6) if mem else None,
                    "mem_total_mb": None,
                }
    return None


# ── process-tree sampler ─────────────────────────────────────────────────────
class _Sampler:
    """Holds primed psutil.Process handles so cpu_percent deltas are correct
    across samples (cpu_percent(None) is meaningless on a fresh handle)."""

    def __init__(self, sample_fds: bool = True):
        self._cache: dict = {}
        self.sample_fds = sample_fds
        self.seen: set[int] = set()

    def _proc(self, pid: int):
        p = self._cache.get(pid)
        if p is None:
            p = psutil.Process(pid)
            with contextlib.suppress(psutil.Error):
                p.cpu_percent(None)  # prime; first reading is always 0
            self._cache[pid] = p
        return p

    def sample(self, root: "psutil.Process") -> dict:
        try:
            procs = [root] + root.children(recursive=True)
        except psutil.Error:
            procs = []
        agg = {
            "rss": 0,
            "cpu": 0.0,
            "threads": 0,
            "fds": 0,
            "nproc": 0,
            "zombies": 0,
            "max_proc_cpu": 0.0,
        }
        do_fd = self.sample_fds and len(procs) <= 64
        for raw in procs:
            try:
                p = self._proc(raw.pid)
                self.seen.add(raw.pid)
                with p.oneshot():
                    agg["rss"] += p.memory_info().rss
                    c = p.cpu_percent(None)
                    agg["cpu"] += c
                    agg["max_proc_cpu"] = max(agg["max_proc_cpu"], c)
                    agg["threads"] += p.num_threads()
                    if do_fd:
                        with contextlib.suppress(
                            psutil.AccessDenied, NotImplementedError, OSError
                        ):
                            agg["fds"] += p.num_fds()
                    if p.status() == psutil.STATUS_ZOMBIE:
                        agg["zombies"] += 1
                    agg["nproc"] += 1
            except psutil.Error:
                continue
        return agg


def _ps_sample(pids: list[int]) -> dict:
    """psutil-free fallback: RSS + %CPU via ps. No fd/thread/zombie detail."""
    if not pids:
        return {
            "rss": 0,
            "cpu": 0.0,
            "threads": 0,
            "fds": 0,
            "nproc": 0,
            "zombies": 0,
            "max_proc_cpu": 0.0,
        }
    cp = common.run(["ps", "-o", "rss=,pcpu=", "-p", ",".join(map(str, pids))])
    rss = cpu = mx = 0.0
    n = 0
    for line in cp.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            try:
                rss += float(parts[0]) * 1024
                c = float(parts[1].replace(",", "."))
                cpu += c
                mx = max(mx, c)
                n += 1
            except ValueError:
                continue
    return {
        "rss": rss,
        "cpu": cpu,
        "threads": 0,
        "fds": 0,
        "nproc": n,
        "zombies": 0,
        "max_proc_cpu": mx,
    }


def _child_pids(pid: int) -> list[int]:
    """Recursive descendant PIDs via pgrep -P (psutil-free path)."""
    out, frontier = [], [pid]
    seen = {pid}
    while frontier:
        cur = frontier.pop()
        cp = common.run(["pgrep", "-P", str(cur)])
        for line in cp.stdout.split():
            try:
                kid = int(line)
            except ValueError:
                continue
            if kid not in seen:
                seen.add(kid)
                out.append(kid)
                frontier.append(kid)
    return out


# ── drivers ──────────────────────────────────────────────────────────────────
def profile_command(
    cmd_argv, *, interval: float = 0.5, max_seconds: int = 900, sample_fds: bool = True
) -> dict:
    """Run cmd_argv, sample its process tree until it exits, then reconcile orphans."""
    t0 = time.time()
    gpu_kind = _gpu_available()
    proc = subprocess.Popen(cmd_argv)
    samples, gpu_series = [], []
    use_ps = psutil is None
    sampler = _Sampler(sample_fds) if not use_ps else None
    root = psutil.Process(proc.pid) if not use_ps else None
    seen_ps: set[int] = {proc.pid}

    while proc.poll() is None and (time.time() - t0) < max_seconds:
        if use_ps:
            pids = [proc.pid] + _child_pids(proc.pid)
            seen_ps.update(pids)
            s = _ps_sample(pids)
        else:
            s = sampler.sample(root)
        s["t"] = round(time.time() - t0, 2)
        samples.append(s)
        if gpu_kind:
            g = _gpu_sample(gpu_kind)
            if g:
                g["t"] = s["t"]
                gpu_series.append(g)
        time.sleep(interval)

    rc = proc.poll()
    if rc is None:  # hit max_seconds — stop the child we started
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        rc = proc.poll()

    time.sleep(0.3)  # let the shell reap direct children
    seen = sampler.seen if not use_ps else seen_ps
    orphans = _find_orphans(seen, proc.pid)
    wall = round(time.time() - t0, 2)
    return analyze(
        samples,
        orphans,
        rc,
        gpu_series=gpu_series,
        wall=wall,
        cmd=" ".join(map(str, cmd_argv)),
        degraded=use_ps,
        gpu_kind=gpu_kind,
    )


def profile_pid(
    pid: int, *, duration: int = 20, interval: float = 0.5, sample_fds: bool = True
) -> dict:
    """Attach to a running PID's tree and sample it for `duration` seconds."""
    t0 = time.time()
    gpu_kind = _gpu_available()
    use_ps = psutil is None
    samples, gpu_series = [], []
    if not use_ps:
        try:
            root = psutil.Process(pid)
        except psutil.Error as e:
            return {"error": f"pid {pid}: {e}"}
        sampler = _Sampler(sample_fds)
    while (time.time() - t0) < duration:
        if use_ps:
            s = _ps_sample([pid] + _child_pids(pid))
        else:
            if not root.is_running():
                break
            s = sampler.sample(root)
        s["t"] = round(time.time() - t0, 2)
        samples.append(s)
        if gpu_kind:
            g = _gpu_sample(gpu_kind)
            if g:
                g["t"] = s["t"]
                gpu_series.append(g)
        time.sleep(interval)
    wall = round(time.time() - t0, 2)
    return analyze(
        samples,
        [],
        None,
        gpu_series=gpu_series,
        wall=wall,
        cmd=f"pid {pid}",
        degraded=use_ps,
        gpu_kind=gpu_kind,
    )


def _find_orphans(seen_pids: set[int], root_pid: int) -> list[dict]:
    """Descendants seen during the run that are STILL alive after the root exited."""
    orphans = []
    for pid in seen_pids:
        if pid == root_pid:
            continue
        try:
            if psutil and psutil.pid_exists(pid):
                p = psutil.Process(pid)
                if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                    orphans.append(
                        {
                            "pid": pid,
                            "name": p.name(),
                            "cmdline": " ".join(p.cmdline())[:120],
                        }
                    )
            elif psutil is None:
                # ps-based liveness check
                cp = common.run(["ps", "-o", "comm=", "-p", str(pid)])
                if cp.returncode == 0 and cp.stdout.strip():
                    orphans.append(
                        {"pid": pid, "name": cp.stdout.strip()[:60], "cmdline": ""}
                    )
        except Exception:
            continue
    return orphans


# ── diagnosis ────────────────────────────────────────────────────────────────
def analyze(
    samples,
    orphans,
    returncode,
    *,
    gpu_series=None,
    wall=None,
    cmd="",
    degraded=False,
    gpu_kind=None,
    leak_mb_min: float = 4.0,
) -> dict:
    gpu_series = gpu_series or []
    findings = []
    ncpu = os.cpu_count() or 1
    # Drop degenerate samples (process exiting/exited: rss=0 / no procs). A trailing
    # teardown sample read at rss=0 would otherwise crush the growth ratio and mask a
    # real leak, so the timeline only includes points where the tree was alive.
    samples = [s for s in samples if s.get("nproc", 0) > 0 and s.get("rss", 0) > 0]
    ts = [s["t"] for s in samples]
    rss = [s["rss"] for s in samples]

    if len(samples) >= 4:
        q = max(1, len(rss) // 4)
        # memory leak: sustained, still-climbing RSS slope
        slope_mb_s, r2 = _trend(ts, [r / 1e6 for r in rss])
        mb_min = slope_mb_s * 60
        first, last = _mean(rss[:q]), _mean(rss[-q:])
        growth = (last / first) if first else 1.0
        if mb_min > leak_mb_min and r2 > 0.7 and growth > 1.15:
            findings.append(
                {
                    "type": "memory-leak",
                    "severity": "high",
                    "mb_per_min": round(mb_min, 1),
                    "r2": round(r2, 2),
                    "growth_x": round(growth, 2),
                    "peak_mb": round(max(rss) / 1e6, 1),
                    "evidence": f"RSS rising {mb_min:.1f} MB/min (R²={r2:.2f}, {growth:.1f}× "
                    "over the run, still climbing at the end) — not plateauing, so a leak.",
                    "fix": "Find the unbounded retainer (cache without eviction, growing list, "
                    "unclosed handles); profile allocations with tracemalloc/memray.",
                }
            )
        # fd / handle leak
        fds = [s["fds"] for s in samples]
        if any(fds):
            fslope, fr2 = _trend(ts, fds)
            if fslope * 60 > 30 and fr2 > 0.7 and max(fds) > _mean(fds[:q]) * 1.3:
                findings.append(
                    {
                        "type": "fd-leak",
                        "severity": "high",
                        "fds_per_min": round(fslope * 60, 1),
                        "r2": round(fr2, 2),
                        "peak_fds": int(max(fds)),
                        "evidence": f"Open file descriptors rising {fslope * 60:.0f}/min "
                        f"(R²={fr2:.2f}) — handles opened but never closed.",
                        "fix": "Close files/sockets (use `with`); check connection pools and watchers.",
                    }
                )
        # thread leak
        ths = [s["threads"] for s in samples]
        if any(ths):
            tslope, tr2 = _trend(ts, ths)
            if tslope * 60 > 8 and tr2 > 0.7 and max(ths) > _mean(ths[:q]) * 1.5:
                findings.append(
                    {
                        "type": "thread-leak",
                        "severity": "medium",
                        "threads_per_min": round(tslope * 60, 1),
                        "peak_threads": int(max(ths)),
                        "evidence": f"Thread count climbing {tslope * 60:.0f}/min — threads spawned "
                        "but not joined (a pool that never bounds, perhaps).",
                        "fix": "Bound the pool / join workers; reuse an executor instead of per-task threads.",
                    }
                )

    # cpu bottleneck classification
    if samples and (wall or 0) > 2:
        max_single = max(s["max_proc_cpu"] for s in samples)
        avg_total = _mean([s["cpu"] for s in samples])
        if max_single >= 85 and avg_total < 150:
            findings.append(
                {
                    "type": "cpu-single-core-bottleneck",
                    "severity": "medium",
                    "max_proc_cpu": round(max_single),
                    "avg_total_cpu": round(avg_total),
                    "cores": ncpu,
                    "evidence": f"One process pinned ~{max_single:.0f}% (≈1 core) while total stayed "
                    f"{avg_total:.0f}% of {ncpu * 100}% — {ncpu - 1} cores idle. Serial bottleneck.",
                    "fix": "Parallelize the hot loop (process pool / multiprocessing); the work is CPU-bound "
                    "and single-threaded.",
                }
            )
        elif avg_total > ncpu * 100 * 0.85:
            findings.append(
                {
                    "type": "cpu-saturated",
                    "severity": "low",
                    "avg_total_cpu": round(avg_total),
                    "cores": ncpu,
                    "evidence": f"Sustained {avg_total:.0f}% ≈ all {ncpu} cores — cpu-bound (expected if "
                    "compute-heavy; otherwise a busy-wait).",
                    "fix": "If unexpected, check for a busy-wait/spin loop; otherwise it is genuinely compute-bound.",
                }
            )

    # gpu pressure / vram leak
    gpu_summary = None
    if gpu_series:
        gts = [g["t"] for g in gpu_series]
        utils = [g["util"] for g in gpu_series if g.get("util") is not None]
        mems = [g["mem_mb"] for g in gpu_series if g.get("mem_mb") is not None]
        gpu_summary = {
            "util_peak": round(max(utils)) if utils else None,
            "mem_peak_mb": round(max(mems), 1) if mems else None,
            "samples": len(gpu_series),
        }
        if len(mems) >= 4:
            gslope, gr2 = _trend(gts[: len(mems)], mems)
            if (
                gslope * 60 > 20
                and gr2 > 0.7
                and max(mems) > _mean(mems[: max(1, len(mems) // 4)]) * 1.2
            ):
                findings.append(
                    {
                        "type": "gpu-memory-leak",
                        "severity": "high",
                        "vram_mb_per_min": round(gslope * 60, 1),
                        "peak_mb": round(max(mems), 1),
                        "evidence": f"VRAM rising {gslope * 60:.0f} MB/min (R²={gr2:.2f}) — GPU memory "
                        "not released (tensors kept alive, no cache clear).",
                        "fix": "Free tensors / empty the allocator cache between batches; detach graphs.",
                    }
                )

    # orphan / zombie leak
    if orphans:
        findings.append(
            {
                "type": "orphan-processes",
                "severity": "high",
                "count": len(orphans),
                "procs": orphans[:10],
                "evidence": f"{len(orphans)} child process(es) still alive after the command exited — "
                "orphaned/leaked processes (no cleanup on shutdown).",
                "fix": "Terminate children on exit (process group kill / atexit / context manager).",
            }
        )
    zomb_peak = max((s["zombies"] for s in samples), default=0)
    if zomb_peak:
        findings.append(
            {
                "type": "zombie-processes",
                "severity": "medium",
                "peak": zomb_peak,
                "evidence": f"Up to {zomb_peak} zombie (defunct) process(es) — children exited but were "
                "never reaped (missing wait()).",
                "fix": "Reap children (wait()/waitpid) or set SIGCHLD handling; use a process manager.",
            }
        )

    sev_rank = {"high": 3, "medium": 2, "low": 1}
    worst = max((sev_rank.get(f["severity"], 0) for f in findings), default=0)
    verdict = "PROBLEM" if worst >= 3 else "WARN" if worst >= 1 else "CLEAN"

    return {
        "cmd": cmd,
        "verdict": verdict,
        "returncode": returncode,
        "wall_s": wall,
        "samples": len(samples),
        "degraded": degraded,
        "summary": {
            "peak_rss_mb": round(max(rss) / 1e6, 1) if rss else 0,
            "start_rss_mb": round(rss[0] / 1e6, 1) if rss else 0,
            "end_rss_mb": round(rss[-1] / 1e6, 1) if rss else 0,
            "avg_total_cpu_pct": round(_mean([s["cpu"] for s in samples]))
            if samples
            else 0,
            "max_proc_cpu_pct": round(
                max((s["max_proc_cpu"] for s in samples), default=0)
            ),
            "peak_threads": max((s["threads"] for s in samples), default=0),
            "peak_fds": max((s["fds"] for s in samples), default=0),
            "peak_procs": max((s["nproc"] for s in samples), default=0),
            "cores": ncpu,
            "gpu": gpu_summary,
            "gpu_source": gpu_kind,
        },
        "findings": sorted(findings, key=lambda f: -sev_rank.get(f["severity"], 0)),
    }


def markdown(r: dict) -> str:
    if "error" in r:
        return f"# Debugmaster Profile\n\nError: {r['error']}\n"
    s = r["summary"]
    L = [
        f"# Debugmaster Profile — `{r['cmd']}`",
        "",
        f"## Verdict: **{r['verdict']}**  ·  {r['wall_s']}s · {r['samples']} samples"
        + (
            " · ⚠️ psutil not installed (limited: RSS/CPU only)" if r["degraded"] else ""
        ),
        "",
        f"- RSS: {s['start_rss_mb']} → {s['end_rss_mb']} MB (peak {s['peak_rss_mb']})",
        f"- CPU: avg {s['avg_total_cpu_pct']}% · max single proc {s['max_proc_cpu_pct']}% "
        f"of {s['cores'] * 100}% ({s['cores']} cores)",
        f"- threads peak {s['peak_threads']} · fds peak {s['peak_fds']} · procs peak {s['peak_procs']}",
    ]
    if s.get("gpu"):
        g = s["gpu"]
        L.append(
            f"- gpu ({s['gpu_source']}): util peak {g.get('util_peak')}% · "
            f"vram peak {g.get('mem_peak_mb')} MB"
        )
    L += ["", "## Findings", ""]
    if not r["findings"]:
        L.append("- none — no leak/bottleneck/orphan detected.")
    for f in r["findings"]:
        L.append(f"- **{f['severity'].upper()} · {f['type']}** — {f['evidence']}")
        if f.get("fix"):
            L.append(f"  - fix: {f['fix']}")
        if f.get("procs"):
            for p in f["procs"]:
                L.append(f"  - pid {p['pid']} `{p['name']}` {p.get('cmdline', '')}")
    L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import json
    import sys

    if "--" in sys.argv:
        i = sys.argv.index("--")
        print(json.dumps(profile_command(sys.argv[i + 1 :]), indent=2))
    elif len(sys.argv) > 1:
        print(json.dumps(profile_pid(int(sys.argv[1])), indent=2))
    else:
        print("usage: profile.py -- <command> | profile.py <pid>")
