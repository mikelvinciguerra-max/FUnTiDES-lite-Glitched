#!/bin/bash
#SBATCH -C sirocco
#SBATCH --job-name=semproxy_cuda
#SBATCH --output=logs/semproxy_cuda.log
#SBATCH --time=00:30:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G

module purge
module load cmake/4.1.3
module load gcc
module load git
module load cuda-toolkit/13.0.2

SRC_DIR=${SLURM_SUBMIT_DIR:-$(pwd)}
BUILD_DIR=${SRC_DIR}/build

# Kokkos est un sous-module git
cd ${SRC_DIR}
git submodule update --init --recursive

rm -rf ${BUILD_DIR} && mkdir -p ${BUILD_DIR} && cd ${BUILD_DIR}

cmake .. \
    -DUSE_KOKKOS=ON \
    -DENABLE_CUDA=ON \
    -DUSE_VECTOR=OFF

make

./src/main/semproxy -ex 100
