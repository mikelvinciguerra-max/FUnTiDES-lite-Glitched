#!/bin/bash
#SBATCH -C sirocco
#SBATCH --job-name=semproxy_cuda
#SBATCH --output=logs/semproxy_cuda.log
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

EX=${EX:-100}
EY=${EY:-50}
EZ=${EZ:-50}
TIMEMAX=${TIMEMAX:-1.5}
SNAP_INTERVAL=${SNAP_INTERVAL:-50}  

set -e
module purge
module load cmake/4.1.3
module load gcc-toolchain/12.5.0
module load git
module load cuda-toolkit/12.9.1

SRC_DIR=${SLURM_SUBMIT_DIR:-$(pwd)}
JOB=${SLURM_JOB_ID:-local}
WORK_DIR=${TMPDIR:-/tmp}/semproxy_cuda_${JOB}

cd ${SRC_DIR}
git submodule update --init --recursive

rm -rf ${WORK_DIR} && mkdir -p ${WORK_DIR}
tar -C ${SRC_DIR} \
    --exclude=./build --exclude=./snapshots --exclude=./sismos \
    --exclude=./metrics --exclude=./logs --exclude=./bench_results \
    --exclude='./bench_out_*' \
    -cf - . | tar -C ${WORK_DIR} -xf -

find ${WORK_DIR}/src -type f \( -name '*.h' -o -name '*.hpp' -o -name '*.cc' -o -name '*.cpp' \) \
    -exec sed -i -E 's/([^:_a-zA-Z0-9])(fmin|fmax)\(/\1std::\2(/g' {} +

mkdir -p ${WORK_DIR}/build && cd ${WORK_DIR}/build

GPU_NAME=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -n 1 || true)
GPU_CC=$(nvidia-smi --query-gpu=compute_cap --format=csv,noheader 2>/dev/null | head -n 1 | tr -d ' ' || true)
if [ -z "${KOKKOS_ARCH:-}" ]; then
    case "${GPU_CC}" in
        6.0) KOKKOS_ARCH=PASCAL60 ;;
        6.1) KOKKOS_ARCH=PASCAL61 ;;
        7.0) KOKKOS_ARCH=VOLTA70 ;;
        7.5) KOKKOS_ARCH=TURING75 ;;
        8.0) KOKKOS_ARCH=AMPERE80 ;;
        8.6) KOKKOS_ARCH=AMPERE86 ;;
        8.9) KOKKOS_ARCH=ADA89 ;;
        9.0) KOKKOS_ARCH=HOPPER90 ;;
        *)   KOKKOS_ARCH=VOLTA70
             echo "ATTENTION : GPU non détecté (compute_cap='${GPU_CC}'), VOLTA70 par défaut" ;;
    esac
fi
echo "Noeud : $(hostname)   GPU : ${GPU_NAME:-aucun}   -> -DKokkos_ARCH_${KOKKOS_ARCH}=ON"

cmake .. \
    -DUSE_KOKKOS=ON \
    -DENABLE_CUDA=ON \
    -DUSE_VECTOR=OFF \
    -DKokkos_ARCH_${KOKKOS_ARCH}=ON

make

LIBCUDA_DIR=/usr/lib64
mkdir -p ${WORK_DIR}/cudalib
ln -sf ${LIBCUDA_DIR}/libcuda.so.1 ${WORK_DIR}/cudalib/libcuda.so.1
export LD_LIBRARY_PATH=${WORK_DIR}/cudalib:${LD_LIBRARY_PATH:-}

SNAP_DIR=${SRC_DIR}/snapshots
SISMO_DIR=${SRC_DIR}/sismos
METRICS_DIR=${SRC_DIR}/metrics
mkdir -p ${SNAP_DIR} ${SISMO_DIR} ${METRICS_DIR}


RCV_FILE=${SRC_DIR}/rcv.txt
if [ ! -f "${RCV_FILE}" ]; then
    RCV_FILE=${METRICS_DIR}/rcv_defaut_${JOB}.txt
    printf '1410 1010 1010\n1010 1410 1010\n600 600 600\n' > ${RCV_FILE}
    echo "ATTENTION : ${SRC_DIR}/rcv.txt introuvable, récepteurs par défaut : ${RCV_FILE}"
fi

./bin/semproxy \
    --ex ${EX} --ey ${EY} --ez ${EZ} --timemax ${TIMEMAX} \
    --snapshots --snap-interval ${SNAP_INTERVAL} --snap-folder ${SNAP_DIR} \
    --receivers-file ${RCV_FILE} --sismo-folder ${SISMO_DIR} \
    --metrics-file ${METRICS_DIR}/run_${JOB}.json \
    --metrics-csv ${METRICS_DIR}/all.csv \
    --run-label run_cuda

echo "Snapshots : ${SNAP_DIR}"
echo "Sismos    : ${SISMO_DIR}"
echo "Métriques : ${METRICS_DIR}/run_${JOB}.json (et all.csv)"
