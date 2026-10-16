
import argparse
import csv
import glob
import json
import math
import os
import sys
from collections import OrderedDict

import numpy as np

BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e1"
NEUTRAL = "#8a8985"

def load_runs(folder):
    runs = []
    for path in sorted(glob.glob(os.path.join(folder, "*.json"))):
        try:
            m = json.load(open(path))
        except ValueError:
            print(f"ignoré (JSON illisible) : {path}", file=sys.stderr)
            continue
        parts = str(m.get("label", "")).split(":")
        if len(parts) != 3:
            continue  # pas un run de bench.sh
        m["scen"], m["cfg"], m["rep"] = parts
        sync_path = path[:-5] + ".sync"
        try:
            m["sync_s"] = float(open(sync_path).read())
        except (OSError, ValueError):
            m["sync_s"] = 0.0
        m["t_eff_s"] = m["t_run_s"] + m["sync_s"]
        m["t_calc_s"] = m["t_run_s"] - m["t_snapshots_s"] - m["t_sismos_s"]
        m["data_MB"] = m["total_bytes"] / 1e6
        runs.append(m)
    return runs


def stat(rows, key):
    v = np.array([r[key] for r in rows], dtype=float)
    return float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0


def group(runs):
    g = OrderedDict()
    for r in runs:
        g.setdefault((r["scen"], r["cfg"]), []).append(r)
    return g


def build_summary(runs):
    groups = group(runs)
    
    base_rows = {}
    for (scen, cfg), rows in groups.items():
        r0 = rows[0]
        if r0["snapshots"] == 0 and r0["sismos"] == 0:
            base_rows.setdefault((r0["ex"], r0["ey"], r0["ez"]), []).extend(rows)
    base = {k: stat(v, "t_eff_s") for k, v in base_rows.items()}

    summary = []
    for (scen, cfg), rows in groups.items():
        r0 = rows[0]
        mesh = (r0["ex"], r0["ey"], r0["ez"])
        s = OrderedDict(scenario=scen, config=cfg, n=len(rows),
                        ex=r0["ex"], ey=r0["ey"], ez=r0["ez"], nodes=r0["nodes"],
                        snap_interval=r0["snap_interval"], receivers=r0["receivers"] if r0["sismos"] else 0,
                        backend=r0["backend"])
        for key, name in [("t_run_s", "t_run"), ("t_calc_s", "t_calc"),
                          ("t_snapshots_s", "t_snap"), ("t_sismos_s", "t_sismo"),
                          ("sync_s", "sync"), ("t_eff_s", "t_eff")]:
            m, sd = stat(rows, key)
            s[name], s[name + "_std"] = m, sd
        s["cv_pct"] = 100 * s["t_eff_std"] / s["t_eff"] if s["t_eff"] else 0.0
        s["snapshot_files"] = int(round(stat(rows, "snapshot_files")[0]))
        s["data_MB"] = stat(rows, "data_MB")[0]
        s["snapshot_MBps"] = stat(rows, "snapshot_MBps")[0]
        io_time = s["t_snap"] + s["t_sismo"] + s["sync"]
        s["eff_MBps"] = s["data_MB"] / io_time if (io_time > 0 and s["data_MB"] > 0) else 0.0
        if mesh in base and base[mesh][0] > 0:
            b, bsd = base[mesh]
            s["overhead_pct"] = 100 * (s["t_eff"] - b) / b
            s["overhead_err"] = 100 * s["t_eff_std"] / b
        else:
            s["overhead_pct"] = s["overhead_err"] = float("nan")
        s["peak_rss_MiB"] = stat(rows, "peak_rss_MiB")[0]
        summary.append(s)

    # ordre d'affichage : scénarios dans l'ordre habituel, lignes triées par
    # paramètre qui varie (le tri est stable : le reste garde l'ordre du bench)
    order = {"mode": 0, "interval": 1, "rcv": 2, "mesh": 3, "dest": 4}
    summary.sort(key=lambda s: (order.get(s["scenario"], 9),
                                s["nodes"] if s["scenario"] == "mesh" else 0,
                                s["snap_interval"] if s["scenario"] == "interval" else 0,
                                s["receivers"] if s["scenario"] == "rcv" else 0,
                                1 if (s["snap_interval"] or s["receivers"]) and s["scenario"] == "mesh" else 0,
                                (1 if s["snap_interval"] else 0) + (2 if s["receivers"] else 0)
                                if s["scenario"] == "mode" else 0))
    return summary

def write_csv(summary, path):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0].keys()))
        w.writeheader()
        for s in summary:
            w.writerow({k: (f"{v:.6g}" if isinstance(v, float) else v) for k, v in s.items()})


def describe(s):
    parts = []
    if s["snap_interval"]:
        parts.append(f"snap/{s['snap_interval']}")
    if s["receivers"]:
        parts.append(f"{s['receivers']} rcv")
    return " + ".join(parts) if parts else "sans sortie"


def write_md(summary, path, folder):
    L = []
    L.append("# Résultats du benchmark\n")
    L.append(f"Dossier : `{folder}`  \n")
    env = os.path.join(folder, "bench_env.txt")
    if os.path.exists(env):
        L.append("Conditions de mesure :\n\n```")
        L.append(open(env).read().rstrip())
        L.append("```\n")
    L.append("Temps en secondes (moyenne ± écart-type sur *n* répétitions). "
             "`calcul` = tout sauf l'écriture des sorties ; `sync` = vidage du cache "
             "vers le disque après le run ; `t_eff` = `t_run` + `sync` ; "
             "surcoût = écart de `t_eff` avec le run sans sortie du même maillage.\n")
    scen_names = OrderedDict()
    for s in summary:
        scen_names.setdefault(s["scenario"], []).append(s)
    for scen, rows in scen_names.items():
        L.append(f"\n## Scénario « {scen} »\n")
        L.append("| config | contenu | maillage | n | calcul | snapshots | sismos | sync | **t_eff** | surcoût | données (Mo) | débit eff. (Mo/s) | bruit |")
        L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for s in rows:
            if math.isnan(s["overhead_pct"]):
                ov = "—"
            elif s["n"] > 1 and abs(s["overhead_pct"]) < s["overhead_err"]:
                ov = f"{s['overhead_pct']:+.1f} % (≈ bruit)"
            else:
                ov = f"{s['overhead_pct']:+.1f} %"
            noisy = "⚠ bruité" if (s["n"] > 1 and s["cv_pct"] > 10) else ""
            L.append(
                f"| {s['config']} | {describe(s)} | {s['ex']}×{s['ey']}×{s['ez']} | {s['n']} "
                f"| {s['t_calc']:.2f} | {s['t_snap']:.2f} | {s['t_sismo']:.2f} | {s['sync']:.2f} "
                f"| **{s['t_eff']:.2f} ± {s['t_eff_std']:.2f}** | {ov} "
                f"| {s['data_MB']:.1f} | {s['eff_MBps']:.0f} | {noisy} |")
    L.append("\n*⚠ bruité : écart-type > 10 % de la moyenne. « ≈ bruit » : le surcoût est plus petit que l'écart-type, il n'est pas significatif (un surcoût négatif en est le signe) ; augmente REPS ou la durée simulée.*\n")
    open(path, "w").write("\n".join(L) + "\n")

def setup_matplotlib(show):
    import matplotlib
    if not show:
        matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": GRID, "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
        "text.color": INK, "axes.titlecolor": INK, "axes.titlesize": 11, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.labelsize": 9, "xtick.labelsize": 8.5, "ytick.labelsize": 8.5,
        "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True, "axes.axisbelow": True,
        "grid.color": GRID, "grid.linewidth": 0.8, "font.size": 9,
        "legend.frameon": False, "legend.fontsize": 8.5, "lines.linewidth": 2.0,
    })
    return plt


def only(summary, scen):
    return [s for s in summary if s["scenario"] == scen]


def fmt_ov(v):
    if math.isnan(v):
        return ""
    return f"{v:+.1f} %" if abs(v) < 10 else f"{v:+.0f} %"


def fmt_t(v):
    if v < 0.1:
        return f"{v:.3f} s"
    return f"{v:.2f} s" if v < 10 else f"{v:.1f} s"


def fmt_nodes(n):
    return f"{n / 1e6:.2f} M" if n >= 1e5 else f"{n / 1e3:.0f} k"


def log_if_wide(ax, values, axis="y"):
    """Echelle log seulement si les valeurs couvrent plus d'une décade
    (sinon matplotlib n'affiche aucune graduation)."""
    from matplotlib.ticker import LogLocator, ScalarFormatter
    v = [x for x in values if x > 0]
    if v and max(v) / min(v) > 10:
        (ax.set_yscale if axis == "y" else ax.set_xscale)("log")
        axis_obj = ax.yaxis if axis == "y" else ax.xaxis
        axis_obj.set_major_locator(LogLocator(base=10, subs=(1, 2, 5)))  # 1, 2, 5, 10, 20, ...
        axis_obj.set_major_formatter(ScalarFormatter())
        axis_obj.set_minor_locator(LogLocator(base=10, subs=(), numticks=0))


def fmt_size(mb):
    return f"{mb / 1000:.2f} Go" if mb >= 100 else f"{mb:.1f} Mo"


def fig_mode(plt, summary, out):
    rows = only(summary, "mode")
    if not rows:
        return
    fig, ax = plt.subplots(figsize=(7.2, 4.4))
    x = np.arange(len(rows))
    layers = [("calcul (+ extraction récepteurs)", "t_calc", BLUE),
              ("écriture snapshots", "t_snap", ORANGE),
              ("écriture sismos", "t_sismo", AQUA),
              ("vidage disque (sync)", "sync", YELLOW)]
    bottom = np.zeros(len(rows))
    for name, key, col in layers:
        v = np.array([r[key] for r in rows])
        ax.bar(x, v, 0.58, bottom=bottom, color=col, edgecolor=SURFACE, linewidth=1.5, label=name)
        bottom += v
    top = max(bottom)
    for i, r in enumerate(rows):
        is_ref = not r["snap_interval"] and not r["receivers"]
        ax.text(i, bottom[i] + top * 0.015, f"{fmt_t(r['t_eff'])}\n{'référence' if is_ref else fmt_ov(r['overhead_pct'])}",
                ha="center", va="bottom", fontsize=8.5, color=INK)
    ax.set_xticks(x)
    ax.set_xticklabels([f"{r['config']}\n{describe(r)}" for r in rows])
    ax.set_ylabel("temps du workflow (s)")
    ax.set_ylim(0, top * 1.22)
    ax.grid(axis="x", visible=False)
    ax.set_title("Coût de chaque type de sortie")
    ax.legend(loc="upper left", ncol=2, bbox_to_anchor=(0, -0.16))
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_interval(plt, summary, out):
    rows = sorted([r for r in only(summary, "interval") if r["snap_interval"] > 0],
                  key=lambda r: r["snap_interval"])
    if not rows:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.0))
    xs = [r["snap_interval"] for r in rows]
    ov = [r["overhead_pct"] for r in rows]
    a1.errorbar(xs, ov, yerr=[r["overhead_err"] for r in rows], color=BLUE, marker="o",
                markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5, capsize=3, elinewidth=1)
    for x_, y_ in zip(xs, ov):
        a1.annotate(fmt_ov(y_), (x_, y_), textcoords="offset points", xytext=(9, 4),
                    ha="left", fontsize=8.5)
    a1.set_xscale("log")
    a1.margins(x=0.12)
    a1.set_xticks(xs)
    a1.set_xticklabels([str(x) for x in xs])
    a1.minorticks_off()
    a1.set_xlabel("intervalle entre deux snapshots (itérations)")
    a1.set_ylabel("surcoût vs sans sortie (%)")
    a1.set_title("Surcoût en temps")
    a1.margins(y=0.18)

    xi = np.arange(len(rows))
    big = max(r["data_MB"] for r in rows) >= 100
    gb = [r["data_MB"] / (1000 if big else 1) for r in rows]
    a2.bar(xi, gb, 0.58, color=ORANGE, edgecolor=SURFACE, linewidth=1.5)
    for i, (g, r) in enumerate(zip(gb, rows)):
        a2.text(i, g, f"{fmt_size(r['data_MB'])}\n{r['snapshot_files']} fichiers", ha="center", va="bottom", fontsize=8)
    a2.set_xticks(xi)
    a2.set_xticklabels([str(x) for x in xs])
    a2.set_xlabel("intervalle entre deux snapshots (itérations)")
    a2.set_ylabel("données écrites (Go)" if big else "données écrites (Mo)")
    a2.set_title("Volume de données")
    a2.set_ylim(0, max(gb) * 1.25)
    a2.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_rcv(plt, summary, out):
    rows = sorted([r for r in only(summary, "rcv") if r["receivers"] > 0], key=lambda r: r["receivers"])
    if not rows:
        return
    xs = [r["receivers"] for r in rows]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.0))
    ts = [max(r["t_sismo"], 1e-6) for r in rows]
    a1.plot(xs, ts, color=AQUA, marker="o", markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
    for x_, y_ in zip(xs, ts):
        a1.annotate(f"{y_:.3g} s", (x_, y_), textcoords="offset points", xytext=(9, 4), ha="left", fontsize=8.5)
    a1.set_xscale("log"); log_if_wide(a1, ts)
    a1.set_xticks(xs); a1.set_xticklabels([str(x) for x in xs]); a1.minorticks_off()
    a1.set_xlabel("nombre de récepteurs"); a1.set_ylabel("écriture des sismos (s)")
    a1.set_title("Temps d'écriture des sismos")
    a1.margins(x=0.12, y=0.25)

    ov = [r["overhead_pct"] for r in rows]
    a2.errorbar(xs, ov, yerr=[r["overhead_err"] for r in rows], color=BLUE, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, capsize=3, elinewidth=1)
    for x_, y_ in zip(xs, ov):
        a2.annotate(fmt_ov(y_), (x_, y_), textcoords="offset points", xytext=(9, 4), ha="left", fontsize=8.5)
    a2.margins(x=0.12)
    a2.set_xscale("log"); a2.set_xticks(xs); a2.set_xticklabels([str(x) for x in xs]); a2.minorticks_off()
    a2.set_xlabel("nombre de récepteurs"); a2.set_ylabel("surcoût total vs sans sortie (%)")
    a2.set_title("Surcoût du workflow (extraction + écriture)")
    a2.margins(y=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_mesh(plt, summary, out):
    rows = only(summary, "mesh")
    plain = sorted([r for r in rows if not r["snap_interval"] and not r["receivers"]], key=lambda r: r["nodes"])
    withs = sorted([r for r in rows if r["snap_interval"] or r["receivers"]], key=lambda r: r["nodes"])
    if not plain:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.6, 4.0))
    a1.plot([r["nodes"] for r in plain], [r["t_eff"] for r in plain], color=BLUE, marker="o", markersize=6,
            markeredgecolor=SURFACE, markeredgewidth=1.5, label="sans sortie")
    if withs:
        lab = "avec " + describe(withs[0])
        a1.plot([r["nodes"] for r in withs], [r["t_eff"] for r in withs], color=ORANGE, marker="o", markersize=6,
                markeredgecolor=SURFACE, markeredgewidth=1.5, label=lab)
        a2.plot([r["nodes"] for r in withs], [r["overhead_pct"] for r in withs], color=ORANGE, marker="o",
                markersize=6, markeredgecolor=SURFACE, markeredgewidth=1.5)
        for r in withs:
            a2.annotate(fmt_ov(r["overhead_pct"]), (r["nodes"], r["overhead_pct"]), textcoords="offset points",
                        xytext=(0, 9), ha="center", fontsize=8.5)
    for r in plain:
        a1.annotate(f"{r['ex']}×{r['ey']}×{r['ez']}", (r["nodes"], r["t_eff"]), textcoords="offset points",
                    xytext=(4, -15), ha="left", fontsize=7.5, color=INK2)
    a1.set_xscale("log"); log_if_wide(a1, [r["t_eff"] for r in plain])
    nodes_all = sorted({r["nodes"] for r in rows})
    for ax_ in (a1, a2):
        ax_.set_xticks(nodes_all)
        ax_.set_xticklabels([fmt_nodes(n) for n in nodes_all])
        ax_.minorticks_off()
        ax_.margins(x=0.12)
    a1.set_xlabel("nombre de noeuds du maillage"); a1.set_ylabel("temps du workflow (s)")
    a1.set_title("Passage à l'échelle"); a1.legend(loc="upper left")
    a2.set_xscale("log")
    a2.set_xticks(nodes_all); a2.set_xticklabels([fmt_nodes(n) for n in nodes_all]); a2.minorticks_off()
    a2.set_xlabel("nombre de noeuds du maillage"); a2.set_ylabel("surcoût vs sans sortie (%)")
    a2.set_title("Surcoût des sorties selon la taille"); a2.margins(y=0.25)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


def fig_dest(plt, summary, out):
    rows = only(summary, "dest")
    if len(rows) < 2:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.0, 4.0))
    x = np.arange(len(rows))
    snap = np.array([r["t_snap"] + r["t_sismo"] for r in rows])
    sync = np.array([r["sync"] for r in rows])
    a1.bar(x, snap, 0.5, color=ORANGE, edgecolor=SURFACE, linewidth=1.5, label="écriture (dans le code)")
    a1.bar(x, sync, 0.5, bottom=snap, color=YELLOW, edgecolor=SURFACE, linewidth=1.5, label="vidage disque (sync)")
    for i, r in enumerate(rows):
        a1.text(i, snap[i] + sync[i], fmt_t(snap[i] + sync[i]), ha="center", va="bottom", fontsize=8.5)
    a1.set_xticks(x); a1.set_xticklabels([f"{r['config']}" for r in rows])
    a1.set_ylabel("temps d'I/O (s)"); a1.set_title("Temps consacré aux sorties")
    a1.set_ylim(0, (snap + sync).max() * 1.25); a1.grid(axis="x", visible=False)
    a1.legend(loc="upper left")
    mb = [r["eff_MBps"] for r in rows]
    a2.bar(x, mb, 0.5, color=BLUE, edgecolor=SURFACE, linewidth=1.5)
    for i, v in enumerate(mb):
        a2.text(i, v, f"{v:.0f} Mo/s", ha="center", va="bottom", fontsize=8.5)
    a2.set_xticks(x); a2.set_xticklabels([f"{r['config']}" for r in rows])
    a2.set_ylabel("débit effectif (Mo/s)"); a2.set_title("Débit d'écriture effectif")
    a2.set_ylim(0, max(mb) * 1.25 if max(mb) > 0 else 1); a2.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)


# ----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", help="dossier de résultats de bench.sh")
    ap.add_argument("--out", help="dossier de sortie (défaut : <folder>/report)")
    ap.add_argument("--show", action="store_true", help="afficher les figures à l'écran")
    a = ap.parse_args()

    if not os.path.isdir(a.folder):
        sys.exit(f"Dossier introuvable : {a.folder}")
    runs = load_runs(a.folder)
    if not runs:
        sys.exit(f"Aucun run de bench.sh dans {a.folder} (fichiers .json avec un label scenario:config:rK)")
    failed = os.path.join(a.folder, "failed.txt")
    if os.path.exists(failed):
        print("ATTENTION, des runs ont échoué :\n" + open(failed).read(), file=sys.stderr)

    out = a.out or os.path.join(a.folder, "report")
    os.makedirs(out, exist_ok=True)
    summary = build_summary(runs)
    write_csv(summary, os.path.join(out, "bench_summary.csv"))
    write_md(summary, os.path.join(out, "bench_summary.md"), a.folder)

    plt = setup_matplotlib(a.show)
    fig_mode(plt, summary, os.path.join(out, "fig_mode.png"))
    fig_interval(plt, summary, os.path.join(out, "fig_interval.png"))
    fig_rcv(plt, summary, os.path.join(out, "fig_rcv.png"))
    fig_mesh(plt, summary, os.path.join(out, "fig_mesh.png"))
    fig_dest(plt, summary, os.path.join(out, "fig_dest.png"))
    if a.show:
        plt.show()

    print(f"{len(runs)} runs, {len(summary)} configurations -> {out}")
    for f in sorted(os.listdir(out)):
        print("  ", f)


if __name__ == "__main__":
    main()
