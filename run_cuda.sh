#!/bin/bash
#SBATCH -C V100
#SBATCH --job-name=semproxy_cuda
#SBATCH --output=logs/semproxy_cuda.log
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

set -e
module purge
module load cmake/4.1.3
module load gcc-toolchain/12.5.0
module load git
module load cuda-toolkit/12.9.1

SRC_DIR=${SLURM_SUBMIT_DIR:-$(pwd)}
WORK_DIR=${TMPDIR:-/tmp}/semproxy_cuda_${SLURM_JOB_ID:-local}

# Kokkos est un sous-module git
cd ${SRC_DIR}
git submodule update --init --recursive

# Copie du projet (sans le dossier build) pour ne pas toucher au code original
rm -rf ${WORK_DIR} && mkdir -p ${WORK_DIR}
tar -C ${SRC_DIR} --exclude=./build -cf - . | tar -C ${WORK_DIR} -xf -

# Contournement nvcc : fmin/fmax ambigus -> std::fmin/std::fmax (dans la copie seulement)
find ${WORK_DIR}/src -type f \( -name '*.h' -o -name '*.hpp' -o -name '*.cc' -o -name '*.cpp' \) \
    -exec sed -i -E 's/([^:_a-zA-Z0-9])(fmin|fmax)\(/\1std::\2(/g' {} +

mkdir -p ${WORK_DIR}/build && cd ${WORK_DIR}/build

cmake .. \
    -DUSE_KOKKOS=ON \
    -DENABLE_CUDA=ON \
    -DUSE_VECTOR=OFF \
    -DKokkos_ARCH_VOLTA70=ON

make

LIBCUDA_DIR=/usr/lib64
mkdir -p ${WORK_DIR}/cudalib
ln -sf ${LIBCUDA_DIR}/libcuda.so.1 ${WORK_DIR}/cudalib/libcuda.so.1
export LD_LIBRARY_PATH=${WORK_DIR}/cudalib:${LD_LIBRARY_PATH:-}

./bin/semproxy -ex 100
