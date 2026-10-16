#!/bin/bash
#SBATCH -C sirocco
#SBATCH --job-name=semproxy_bench
#SBATCH --output=logs/semproxy_bench_%j.log
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
# Noeud exclusif : sinon d'autres jobs perturbent les mesures (temps, I/O).
# Si la file d'attente est trop longue, supprime cette ligne (et dis-le dans le rapport).
#SBATCH --exclusive

set -e

REPS=${REPS:-3}
TIMEMAX=${TIMEMAX:-1.5}
QUICK=${QUICK:-0}

SRC_DIR=${SLURM_SUBMIT_DIR:-$(pwd)}
JOB=${SLURM_JOB_ID:-local}
RES_DIR=${RES_DIR:-${SRC_DIR}/bench_results/${JOB}}
LOCAL_OUT=${TMPDIR:-/tmp}/bench_out_${JOB}      # disque local du noeud
SHARED_OUT=${SRC_DIR}/bench_out_${JOB}          # système de fichiers partagé

# -----------------------------------------------------------------------------
# Binaire : compilation (comme run_cuda.sh) sauf si BENCH_BIN est fourni
# -----------------------------------------------------------------------------
if [ -n "${BENCH_BIN:-}" ]; then
    BIN=${BENCH_BIN}
else
    module purge
    module load cmake/4.1.3
    module load gcc-toolchain/12.5.0
    module load git
    module load cuda-toolkit/12.9.1

    WORK_DIR=${TMPDIR:-/tmp}/semproxy_bench_${JOB}
    cd ${SRC_DIR}
    git submodule update --init --recursive

    rm -rf ${WORK_DIR} && mkdir -p ${WORK_DIR}
    tar -C ${SRC_DIR} --exclude=./build --exclude=./bench_results \
        --exclude=./snapshots --exclude=./sismos --exclude=./logs --exclude="./bench_out_*" \
        -cf - . | tar -C ${WORK_DIR} -xf -

    # Contournement nvcc : fmin/fmax ambigus (dans la copie seulement)
    find ${WORK_DIR}/src -type f \( -name '*.h' -o -name '*.hpp' -o -name '*.cc' -o -name '*.cpp' \) \
        -exec sed -i -E 's/([^:_a-zA-Z0-9])(fmin|fmax)\(/\1std::\2(/g' {} +

    mkdir -p ${WORK_DIR}/build && cd ${WORK_DIR}/build
    cmake .. -DUSE_KOKKOS=ON -DENABLE_CUDA=ON -DUSE_VECTOR=OFF -DKokkos_ARCH_VOLTA70=ON
    make

    LIBCUDA_DIR=/usr/lib64
    mkdir -p ${WORK_DIR}/cudalib
    ln -sf ${LIBCUDA_DIR}/libcuda.so.1 ${WORK_DIR}/cudalib/libcuda.so.1
    export LD_LIBRARY_PATH=${WORK_DIR}/cudalib:${LD_LIBRARY_PATH:-}
    BIN=${WORK_DIR}/build/bin/semproxy
fi

mkdir -p "${RES_DIR}" "${LOCAL_OUT}" "${SHARED_OUT}"

# -----------------------------------------------------------------------------
# Conditions de l'expérience (à citer dans le rapport)
# -----------------------------------------------------------------------------
{
    echo "date        : $(date -Is)"
    echo "hostname    : $(hostname)"
    echo "job         : ${JOB}"
    echo "reps        : ${REPS}   timemax : ${TIMEMAX}   quick : ${QUICK}"
    echo "binaire     : ${BIN}"
    echo "commit      : $(git -C ${SRC_DIR} rev-parse --short HEAD 2>/dev/null || echo ?)"
    echo "cpu         : $(grep -m1 'model name' /proc/cpuinfo 2>/dev/null | cut -d: -f2)"
    echo "gpu         : $(nvidia-smi -L 2>/dev/null | head -1 || echo ?)"
    echo "--- stockage local  (${LOCAL_OUT})";  df -PT "${LOCAL_OUT}"  2>/dev/null | tail -1
    echo "--- stockage partagé (${SHARED_OUT})"; df -PT "${SHARED_OUT}" 2>/dev/null | tail -1
} > "${RES_DIR}/bench_env.txt" 2>&1 || true

# -----------------------------------------------------------------------------
# Les configurations. Une ligne = un cas ; modifie le tableau à ta convenance.
#   scénario  nom  ex ey ez  intervalle_snap(0=sans)  nb_récepteurs(0=sans)  destination
#   (nom: sans ':' ni espace)   destination: local | shared
# Les cas sans sortie (snap=0 et récepteurs=0) servent de référence pour un
# maillage donné : le surcoût d'un cas se calcule par rapport à eux.
# -----------------------------------------------------------------------------
cases() {
  if [ "${QUICK}" = "1" ]; then
cat <<'EOF'
mode      none      12 12 12   0   0  local
mode      snap10    12 12 12  10   0  local
mode      sismo3    12 12 12   0   3  local
mode      both      12 12 12  10   3  local
interval  i5        12 12 12   5   0  local
interval  i20       12 12 12  20   0  local
rcv       r1        12 12 12   0   1  local
rcv       r30       12 12 12   0  30  local
mesh      n8_none    8  8  8   0   0  local
mesh      n8_snap    8  8  8  10   0  local
mesh      n14_none  14 14 14   0   0  local
mesh      n14_snap  14 14 14  10   0  local
dest      local5    12 12 12   5   0  local
dest      shared5   12 12 12   5   0  shared
EOF
  else
cat <<'EOF'
mode      none      100 50 50    0     0  local
mode      snap50    100 50 50   50     0  local
mode      sismo10   100 50 50    0    10  local
mode      both      100 50 50   50    10  local
interval  i10       100 50 50   10     0  local
interval  i25       100 50 50   25     0  local
interval  i50       100 50 50   50     0  local
interval  i100      100 50 50  100     0  local
interval  i250      100 50 50  250     0  local
interval  i500      100 50 50  500     0  local
rcv       r1        100 50 50    0     1  local
rcv       r10       100 50 50    0    10  local
rcv       r100      100 50 50    0   100  local
rcv       r1000     100 50 50    0  1000  local
mesh      n40_none   40 40 40    0     0  local
mesh      n40_snap   40 40 40   50     0  local
mesh      n60_none   60 60 60    0     0  local
mesh      n60_snap   60 60 60   50     0  local
mesh      n80_none   80 80 80    0     0  local
mesh      n80_snap   80 80 80   50     0  local
mesh      n100_none 100 100 100  0     0  local
mesh      n100_snap 100 100 100 50     0  local
dest      local10   100 50 50   10     0  local
dest      shared10  100 50 50   10     0  shared
EOF
  fi
}

# Fichier de récepteurs reproductible : N points pseudo-aléatoires (graine fixe)
# à l'intérieur du domaine 2000 m, loin des bords.
make_rcv() {
    local n=$1 f="${RES_DIR}/rcv_$1.txt"
    if [ ! -f "$f" ]; then
        awk -v n="$n" 'BEGIN{srand(42);
            for(i=0;i<n;i++) printf "%.1f %.1f %.1f\n",
                100+rand()*1800, 100+rand()*1800, 100+rand()*1800}' > "$f"
    fi
    echo "$f"
}

# Un run = une exécution mesurée + le temps du `sync` qui suit (les données
# écrites restent sinon dans le cache mémoire : sans sync on mesure une copie
# en RAM, pas l'écriture sur disque).
run_case() {
    local scen=$1 cfg=$2 ex=$3 ey=$4 ez=$5 snap=$6 nrcv=$7 dest=$8 rep=$9
    local id="${scen}__${cfg}__r${rep}"
    local out
    if [ "${dest}" = "shared" ]; then out="${SHARED_OUT}/${id}"; else out="${LOCAL_OUT}/${id}"; fi
    rm -rf "${out}"; mkdir -p "${out}"

    local args=(--ex ${ex} --ey ${ey} --ez ${ez} --timemax ${TIMEMAX}
                --metrics-file "${RES_DIR}/${id}.json"
                --metrics-csv "${RES_DIR}/all.csv"
                --run-label "${scen}:${cfg}:r${rep}")
    if [ "${snap}" -gt 0 ]; then
        args+=(--snapshots --snap-interval ${snap} --snap-folder "${out}/snap")
    fi
    if [ "${nrcv}" -gt 0 ]; then
        args+=(--receivers-file "$(make_rcv ${nrcv})" --sismo-folder "${out}/sismo")
    fi

    sync                                   # état disque propre avant le run
    if ! "${BIN}" "${args[@]}" > "${RES_DIR}/${id}.log" 2>&1; then
        echo "ECHEC : ${id} (voir ${RES_DIR}/${id}.log)" | tee -a "${RES_DIR}/failed.txt"
    fi
    local t0 t1
    t0=$(date +%s.%N); sync; t1=$(date +%s.%N)
    awk -v a="${t0}" -v b="${t1}" 'BEGIN{printf "%.6f\n", b-a}' > "${RES_DIR}/${id}.sync"

    rm -rf "${out}"
}

# -----------------------------------------------------------------------------
# Exécution
# -----------------------------------------------------------------------------
mapfile -t CASES < <(cases)
TOTAL=$(( ${#CASES[@]} * REPS ))
echo "Benchmark : ${#CASES[@]} configurations x ${REPS} répétitions = ${TOTAL} runs"
echo "Résultats : ${RES_DIR}"

# Run de chauffe (init GPU, JIT, cache) : non enregistré
echo "Chauffe..."
"${BIN}" --ex 20 --ey 20 --ez 20 --timemax 0.05 > /dev/null 2>&1 || true

k=0
for rep in $(seq 1 ${REPS}); do
    for line in "${CASES[@]}"; do
        k=$((k+1))
        set -- ${line}
        echo "[${k}/${TOTAL}] $(date +%H:%M:%S)  $1 / $2  (rep ${rep})"
        run_case "$@" "${rep}"
    done
done

rmdir "${LOCAL_OUT}" "${SHARED_OUT}" 2>/dev/null || true
echo "Terminé : $(ls ${RES_DIR}/*.json 2>/dev/null | wc -l) runs dans ${RES_DIR}"
echo "Rapport : python3 bench/bench_report.py ${RES_DIR}"
