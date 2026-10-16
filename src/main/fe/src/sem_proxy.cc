//************************************************************************
//   proxy application v.0.0.1
//
//  .cpp: the main interface of  proxy application
//
//************************************************************************

#include "sem_proxy.h"

#include <cartesian_struct_builder.h>
#include <cartesian_unstruct_builder.h>
#include <sem_solver_acoustic.h>
#include <source_and_receiver_utils.h>
#include <unistd.h>

#include <algorithm>
#include <chrono>
#include <cxxopts.hpp>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <variant>

#include "run_metrics.h"

using namespace SourceAndReceiverUtils;

SEMproxy::SEMproxy(const SemProxyOptions& opt)
{
  t_ctor_start_ = std::chrono::steady_clock::now();
  metrics_file_ = opt.metrics_file;
  metrics_csv_ = opt.metrics_csv;
  run_label_ = opt.run_label;
  opt_implem_ = opt.implem;
  opt_method_ = opt.method;
  opt_mesh_ = opt.mesh;

  const int order = opt.order;
  nb_elements_[0] = opt.ex;
  nb_elements_[1] = opt.ey;
  nb_elements_[2] = opt.ez;
  nb_nodes_[0] = opt.ex * order + 1;
  nb_nodes_[1] = opt.ey * order + 1;
  nb_nodes_[2] = opt.ez * order + 1;

  const float spongex = opt.boundaries_size;
  const float spongey = opt.boundaries_size;
  const float spongez = opt.boundaries_size;
  const std::array<float, 3> sponge_size = {spongex, spongey, spongez};
  src_coord_[0] = opt.srcx;
  src_coord_[1] = opt.srcy;
  src_coord_[2] = opt.srcz;

  domain_size_[0] = opt.lx;
  domain_size_[1] = opt.ly;
  domain_size_[2] = opt.lz;

  loadReceivers(opt);

  bool isModelOnNodes = opt.isModelOnNodes;
  isElastic_ = opt.isElastic;
  cout << boolalpha;
  bool isElastic = isElastic_;

  const SolverFactory::methodType methodType = getMethod(opt.method);
  const SolverFactory::implemType implemType = getImplem(opt.implem);
  const SolverFactory::meshType meshType = getMesh(opt.mesh);
  const SolverFactory::modelLocationType modelLocation =
      isModelOnNodes ? SolverFactory::modelLocationType::OnNodes
                     : SolverFactory::modelLocationType::OnElements;
  const SolverFactory::physicType physicType = SolverFactory::physicType::Acoustic;

  float lx = domain_size_[0];
  float ly = domain_size_[1];
  float lz = domain_size_[2];
  int ex = nb_elements_[0];
  int ey = nb_elements_[1];
  int ez = nb_elements_[2];

  if (meshType == SolverFactory::Struct)
  {
    switch (order)
    {
      case 1: {
        model::CartesianStructBuilder<float, int, 1> builder(
            ex, lx, ey, ly, ez, lz, isModelOnNodes);
        m_mesh = builder.getModel();
        break;
      }
      case 2: {
        model::CartesianStructBuilder<float, int, 2> builder(
            ex, lx, ey, ly, ez, lz, isModelOnNodes);
        m_mesh = builder.getModel();
        break;
      }
      case 3: {
        model::CartesianStructBuilder<float, int, 3> builder(
            ex, lx, ey, ly, ez, lz, isModelOnNodes);
        m_mesh = builder.getModel();
        break;
      }
      default:
        throw std::runtime_error(
            "Order other than 1 2 3 is not supported ()");
    }
  }
  else if (meshType == SolverFactory::Unstruct)
  {
    model::CartesianParams<float, int> param(order, ex, ey, ez, lx, ly, lz,
                                             isModelOnNodes);
    model::CartesianUnstructBuilder<float, int> builder(param);
    m_mesh = builder.getModel();
  }
  else
  {
    throw std::runtime_error("Incorrect mesh type ( ctor.)");
  }

  // time parameters
  if (opt.autodt)
  {
    float cfl_factor = (order == 2) ? 0.5 : 0.7;
    dt_ = find_cfl_dt(cfl_factor);
  }
  else
  {
    dt_ = opt.dt;
  }
  timemax_ = opt.timemax;
  num_sample_ = timemax_ / dt_;

  m_solver = SolverFactory::createSolver(methodType, implemType, meshType,
                                         modelLocation, physicType, order);
  m_solver->computeFEInit(*m_mesh, sponge_size, opt.surface_sponge,
                          opt.taper_delta);

  initFiniteElem();

  initSnapshots(opt);

  std::cout << "Number of node is " << m_mesh->getNumberOfNodes() << std::endl;
  std::cout << "Number of element is " << m_mesh->getNumberOfElements()
            << std::endl;
  std::cout << "Launching the Method " << opt.method << ", the implementation "
            << opt.implem << " and the mesh is " << opt.mesh << std::endl;
  std::cout << "Model is on " << (isModelOnNodes ? "nodes" : "elements")
            << std::endl;
  std::cout << "Physics type is " << (isElastic ? "elastic" : "acoustic")
            << std::endl;
  std::cout << "Order of approximation will be " << order << std::endl;
  std::cout << "Time step is " << dt_ << "s" << std::endl;
  std::cout << "Simulated time is " << timemax_ << "s" << std::endl;

  t_init_s_ = std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                            t_ctor_start_)
                  .count();

}

void SEMproxy::run()
{
  time_point<system_clock> startComputeTime, startOutputTime, totalComputeTime,
      totalOutputTime;

  SEMsolverDataAcoustic solverData(i1, i2, myRHSTerm, pnGlobal, rhsElement,
                                   rhsWeights);
  const auto runStart = std::chrono::steady_clock::now();

  for (int indexTimeSample = 0; indexTimeSample < num_sample_;
       indexTimeSample++)
  {
    startComputeTime = system_clock::now();
    m_solver->computeOneStep(dt_, indexTimeSample, solverData);
#ifdef USE_KOKKOS
    Kokkos::fence();  // kernels are asynchronous: wait, so that the compute
                      // time is not charged to the next output
#endif
    totalComputeTime += system_clock::now() - startComputeTime;
    t_compute_s_ += std::chrono::duration<double>(
                        system_clock::now() - startComputeTime)
                        .count();

    startOutputTime = system_clock::now();

    if (indexTimeSample % 50 == 0)
    {
      m_solver->outputSolutionValues(indexTimeSample, i1, rhsElement[0],
                                     pnGlobal, "pnGlobal");
    }

    if (is_snapshots_ && indexTimeSample % snap_time_interval_ == 0)
    {
      saveSnapshot(indexTimeSample);
    }

    // Save pressure at receiver
    const int order = m_mesh->getOrder();

    const auto startReceivers = std::chrono::steady_clock::now();
    for (int r = 0; r < static_cast<int>(rcv_coords_.size()); r++)
    {
      float varnp1 = 0.0;
      for (int i = 0; i < order + 1; i++)
      {
        for (int j = 0; j < order + 1; j++)
        {
          for (int k = 0; k < order + 1; k++)
          {
            int nodeIdx = m_mesh->globalNodeIndex(rhsElementRcv[r], i, j, k);
            int globalNodeOnElement =
                i + j * (order + 1) + k * (order + 1) * (order + 1);
            varnp1 +=
                pnGlobal(nodeIdx, i2) * rhsWeightsRcv(r, globalNodeOnElement);
          }
        }
      }

      pnAtReceiver(r, indexTimeSample) = varnp1;
    }
    t_receivers_s_ += std::chrono::duration<double>(
                          std::chrono::steady_clock::now() - startReceivers)
                          .count();

    swap(i1, i2);

    auto tmp = solverData.m_i1;
    solverData.m_i1 = solverData.m_i2;
    solverData.m_i2 = tmp;

    totalOutputTime += system_clock::now() - startOutputTime;
  }

  if (is_sismos_) saveSismos();

  t_run_s_ = std::chrono::duration<double>(std::chrono::steady_clock::now() -
                                           runStart)
                 .count();

  float kerneltime_ms = time_point_cast<microseconds>(totalComputeTime)
                            .time_since_epoch()
                            .count();
  float outputtime_ms =
      time_point_cast<microseconds>(totalOutputTime).time_since_epoch().count();

  cout << "------------------------------------------------ " << endl;
  cout << "\n---- Elapsed Kernel Time : " << kerneltime_ms / 1E6 << " seconds."
       << endl;
  cout << "---- Elapsed Output Time : " << outputtime_ms / 1E6 << " seconds."
       << endl;
  if (is_sismos_)
  {
    cout << "---- Sismograms         : " << rcv_coords_.size()
         << " receivers, " << rcv_coords_.size() * num_sample_ * sizeof(float)
         << " bytes, " << sismo_write_seconds_ << " seconds." << endl;
  }
  if (is_snapshots_)
  {
    cout << "---- Snapshots           : " << snap_count_ << " files, "
         << snap_bytes_ << " bytes, " << snap_write_seconds_ << " seconds."
         << endl;
  }
  cout << "------------------------------------------------ " << endl;

  writeMetrics();
}

// Initialize arrays
void SEMproxy::init_arrays()
{
  cout << "Allocate host memory for source and pressure values ..." << endl;

  rhsElement = allocateVector<vectorInt>(myNumberOfRHS, "rhsElement");
  rhsWeights = allocateArray2D<arrayReal>(
      myNumberOfRHS, m_mesh->getNumberOfPointsPerElement(), "RHSWeight");
  myRHSTerm = allocateArray2D<arrayReal>(myNumberOfRHS, num_sample_, "RHSTerm");
  pnGlobal =
      allocateArray2D<arrayReal>(m_mesh->getNumberOfNodes(), 2, "pnGlobal");
  const int nbReceivers = static_cast<int>(rcv_coords_.size());
  pnAtReceiver =
      allocateArray2D<arrayReal>(nbReceivers, num_sample_, "pnAtReceiver");
  // Receivers
  rhsElementRcv = allocateVector<vectorInt>(nbReceivers, "rhsElementRcv");
  rhsWeightsRcv = allocateArray2D<arrayReal>(
      nbReceivers, m_mesh->getNumberOfPointsPerElement(), "RHSWeightRcv");
}

// Initialize sources
void SEMproxy::init_source()
{
  arrayReal myRHSLocation = allocateArray2D<arrayReal>(1, 3, "RHSLocation");
  // std::cout << "All source are currently are coded on element 50." <<
  // std::endl;
  std::cout << "All source are currently are coded on middle element."
            << std::endl;
  int ex = nb_elements_[0];
  int ey = nb_elements_[1];
  int ez = nb_elements_[2];

  int lx = domain_size_[0];
  int ly = domain_size_[1];
  int lz = domain_size_[2];

  // Get source element index

  int source_index = floor((src_coord_[0] * ex) / lx) +
                     floor((src_coord_[1] * ey) / ly) * ex +
                     floor((src_coord_[2] * ez) / lz) * ey * ex;

  for (int i = 0; i < 1; i++)
  {
    rhsElement[i] = source_index;
  }

  // Get coordinates of the corners of the sourc element
  float cornerCoords[8][3];
  int I = 0;
  int nodes_corner[2] = {0, m_mesh->getOrder()};
  for (int k : nodes_corner)
  {
    for (int j : nodes_corner)
    {
      for (int i : nodes_corner)
      {
        int nodeIdx = m_mesh->globalNodeIndex(rhsElement[0], i, j, k);
        cornerCoords[I][0] = m_mesh->nodeCoord(nodeIdx, 0);
        cornerCoords[I][2] = m_mesh->nodeCoord(nodeIdx, 2);
        cornerCoords[I][1] = m_mesh->nodeCoord(nodeIdx, 1);
        I++;
      }
    }
  }

  // initialize source term
  vector<float> sourceTerm =
      myUtils.computeSourceTerm(num_sample_, dt_, f0, sourceOrder);
  for (int j = 0; j < num_sample_; j++)
  {
    myRHSTerm(0, j) = sourceTerm[j];
    if (j % 100 == 0)
      cout << "Sample " << j << "\t: sourceTerm = " << sourceTerm[j] << endl;
  }

  // get element number of source term
  myElementSource = rhsElement[0];
  cout << "Element number for the source location: " << myElementSource << endl
       << endl;

  int order = m_mesh->getOrder();

  switch (order)
  {
    case 1:
      SourceAndReceiverUtils::ComputeRHSWeights<1>(cornerCoords, src_coord_,
                                                   rhsWeights);
      break;
    case 2:
      SourceAndReceiverUtils::ComputeRHSWeights<2>(cornerCoords, src_coord_,
                                                   rhsWeights);
      break;
    case 3:
      SourceAndReceiverUtils::ComputeRHSWeights<3>(cornerCoords, src_coord_,
                                                   rhsWeights);
      break;
    default:
      throw std::runtime_error("Unsupported order: " + std::to_string(order));
  }

  // Receivers computation (one element + one set of weights per receiver)
  for (int r = 0; r < static_cast<int>(rcv_coords_.size()); r++)
  {
    const std::array<float, 3>& rcv = rcv_coords_[r];

    int receiver_index = std::min<int>(floor((rcv[0] * ex) / lx), ex - 1) +
                         std::min<int>(floor((rcv[1] * ey) / ly), ey - 1) * ex +
                         std::min<int>(floor((rcv[2] * ez) / lz), ez - 1) * ey *
                             ex;
    rhsElementRcv[r] = receiver_index;

    // Get coordinates of the corners of the receiver element
    float cornerCoordsRcv[8][3];
    I = 0;
    for (int k : nodes_corner)
    {
      for (int j : nodes_corner)
      {
        for (int i : nodes_corner)
        {
          int nodeIdx = m_mesh->globalNodeIndex(rhsElementRcv[r], i, j, k);
          cornerCoordsRcv[I][0] = m_mesh->nodeCoord(nodeIdx, 0);
          cornerCoordsRcv[I][2] = m_mesh->nodeCoord(nodeIdx, 2);
          cornerCoordsRcv[I][1] = m_mesh->nodeCoord(nodeIdx, 1);
          I++;
        }
      }
    }

    switch (order)
    {
      case 1:
        SourceAndReceiverUtils::ComputeRHSWeights<1>(cornerCoordsRcv, rcv,
                                                     rhsWeightsRcv, r);
        break;
      case 2:
        SourceAndReceiverUtils::ComputeRHSWeights<2>(cornerCoordsRcv, rcv,
                                                     rhsWeightsRcv, r);
        break;
      case 3:
        SourceAndReceiverUtils::ComputeRHSWeights<3>(cornerCoordsRcv, rcv,
                                                     rhsWeightsRcv, r);
        break;
      default:
        throw std::runtime_error("Unsupported order: " +
                                 std::to_string(order));
    }
  }
}

// Read the receivers: from --receivers-file (one "x y z" per line, '#' starts
// a comment, commas allowed), or the single receiver --rcvx/--rcvy/--rcvz.
void SEMproxy::loadReceivers(const SemProxyOptions& opt)
{
  is_sismos_ = opt.sismos || !opt.receivers_file.empty();
  sismo_folder_ = opt.sismo_folder;
  rcv_coords_.clear();

  if (opt.receivers_file.empty())
  {
    rcv_coords_.push_back({opt.rcvx, opt.rcvy, opt.rcvz});
  }
  else
  {
    std::ifstream f(opt.receivers_file);
    if (!f)
      throw std::runtime_error("Cannot open receivers file: " +
                               opt.receivers_file);
    std::string line;
    int lineNumber = 0;
    while (std::getline(f, line))
    {
      lineNumber++;
      const auto hash = line.find('#');
      if (hash != std::string::npos) line.erase(hash);
      std::replace(line.begin(), line.end(), ',', ' ');
      std::istringstream iss(line);
      float x, y, z;
      if (!(iss >> x))
        continue;  // blank or comment-only line
      if (!(iss >> y >> z))
        throw std::runtime_error(opt.receivers_file + ":" +
                                 std::to_string(lineNumber) +
                                 ": expected 'x y z'");
      rcv_coords_.push_back({x, y, z});
    }
    if (rcv_coords_.empty())
      throw std::runtime_error("No receiver found in " + opt.receivers_file);
  }

  // every receiver must lie inside the domain
  for (size_t r = 0; r < rcv_coords_.size(); r++)
  {
    const auto& c = rcv_coords_[r];
    if (c[0] < 0 || c[0] > opt.lx || c[1] < 0 || c[1] > opt.ly || c[2] < 0 ||
        c[2] > opt.lz)
      throw std::runtime_error("Receiver " + std::to_string(r) + " (" +
                               std::to_string(c[0]) + ", " +
                               std::to_string(c[1]) + ", " +
                               std::to_string(c[2]) + ") is outside the domain");
  }

  std::cout << rcv_coords_.size() << " receiver(s)"
            << (is_sismos_ ? ", sismograms will be saved in '" +
                                  sismo_folder_ + "'"
                            : ", sismograms not saved (use --sismos)")
            << std::endl;
}

// Write all the sismograms at the end of the simulation:
//   sismos.bin        : nbReceivers x num_sample_ float32, receiver-major
//                        (row r = sismogram of receiver r, no compression)
//   sismos_meta.json  : shape, dt, receiver coordinates
void SEMproxy::saveSismos()
{
  const auto start = std::chrono::steady_clock::now();
  namespace fs = std::filesystem;
  fs::create_directories(sismo_folder_);

  const int nbReceivers = static_cast<int>(rcv_coords_.size());

#ifdef USE_KOKKOS
  Kokkos::fence();
#endif

  {
    std::ofstream f(sismo_folder_ + "/sismos.bin", std::ios::binary);
    if (!f) throw std::runtime_error("Cannot write sismos.bin");
    std::vector<float> row(num_sample_);
    for (int r = 0; r < nbReceivers; r++)
    {
      for (int t = 0; t < num_sample_; t++) row[t] = pnAtReceiver(r, t);
      f.write(reinterpret_cast<const char*>(row.data()),
              row.size() * sizeof(float));
    }
  }

  {
    std::ofstream f(sismo_folder_ + "/sismos_meta.json");
    if (!f) throw std::runtime_error("Cannot write sismos_meta.json");
    f << "{\n"
      << "  \"dtype\": \"float32\",\n"
      << "  \"file\": \"sismos.bin\",\n"
      << "  \"shape\": [" << nbReceivers << ", " << num_sample_ << "],\n"
      << "  \"layout\": \"receiver-major: row r = sismogram of receiver r\",\n"
      << "  \"dt\": " << dt_ << ",\n"
      << "  \"receivers\": [";
    for (int r = 0; r < nbReceivers; r++)
    {
      f << (r ? ", " : "") << "[" << rcv_coords_[r][0] << ", "
        << rcv_coords_[r][1] << ", " << rcv_coords_[r][2] << "]";
    }
    f << "]\n}\n";
  }

  sismo_write_seconds_ +=
      std::chrono::duration<double>(std::chrono::steady_clock::now() - start)
          .count();
}

// Collect the timings, data sizes and run parameters, and write them as JSON
// (--metrics-file) and/or as one CSV row (--metrics-csv). No-op if neither is
// given. Never stops the program: a failure only prints a warning.
void SEMproxy::writeMetrics()
{
  if (metrics_file_.empty() && metrics_csv_.empty()) return;

  const double mega = 1e6;
  const double tSnap = snap_write_seconds_;
  const double tSismo = is_sismos_ ? sismo_write_seconds_ : 0.0;
  const double tIo = tSnap + tSismo;
  const unsigned long long nodesBytes =
      is_snapshots_
          ? static_cast<unsigned long long>(m_mesh->getNumberOfNodes()) * 3 *
                sizeof(float)
          : 0ULL;
  const unsigned long long sismoBytes =
      is_sismos_ ? static_cast<unsigned long long>(rcv_coords_.size()) *
                       num_sample_ * sizeof(float)
                 : 0ULL;
  const unsigned long long totalBytes = snap_bytes_ + nodesBytes + sismoBytes;

  RunMetrics m;

  // identification
  m.addStr("label", run_label_);
  char host[256] = "unknown";
  gethostname(host, sizeof(host) - 1);
  m.addStr("hostname", host);
  const char* jobId = std::getenv("SLURM_JOB_ID");
  m.addStr("slurm_job_id", jobId ? jobId : "");
#ifdef USE_KOKKOS
  m.addStr("backend", Kokkos::DefaultExecutionSpace::name());
  m.addInt("host_threads", Kokkos::DefaultHostExecutionSpace().concurrency());
#else
  m.addStr("backend", "std::vector");
  m.addInt("host_threads", 1);
#endif

  // parameters of the run
  m.addStr("method", opt_method_);
  m.addStr("implem", opt_implem_);
  m.addStr("mesh", opt_mesh_);
  m.addInt("order", m_mesh->getOrder());
  m.addInt("ex", nb_elements_[0]);
  m.addInt("ey", nb_elements_[1]);
  m.addInt("ez", nb_elements_[2]);
  m.addInt("nodes", m_mesh->getNumberOfNodes());
  m.addInt("elements", m_mesh->getNumberOfElements());
  m.addNum("dt", dt_);
  m.addNum("timemax", timemax_);
  m.addInt("iterations", num_sample_);
  m.addInt("snapshots", is_snapshots_ ? 1 : 0);
  m.addInt("snap_interval", is_snapshots_ ? snap_time_interval_ : 0);
  m.addInt("sismos", is_sismos_ ? 1 : 0);
  m.addInt("receivers", static_cast<long long>(rcv_coords_.size()));

  // timings (seconds)
  m.addNum("t_init_s", t_init_s_);
  m.addNum("t_run_s", t_run_s_);
  m.addNum("t_total_s", t_init_s_ + t_run_s_);
  m.addNum("t_compute_s", t_compute_s_);
  m.addNum("t_compute_per_step_ms",
           num_sample_ > 0 ? 1e3 * t_compute_s_ / num_sample_ : 0.0);
  m.addNum("t_snapshots_s", tSnap);
  m.addNum("t_sismos_s", tSismo);
  m.addNum("t_receivers_s", t_receivers_s_);
  m.addNum("t_io_s", tIo);
  m.addNum("t_other_s",
           t_run_s_ - t_compute_s_ - tIo - t_receivers_s_);  // stdout, swap...
  m.addNum("io_fraction", t_run_s_ > 0 ? tIo / t_run_s_ : 0.0);

  // data written
  m.addInt("snapshot_files", snap_count_);
  m.addInt("snapshot_bytes", static_cast<long long>(snap_bytes_));
  m.addInt("nodes_bytes", static_cast<long long>(nodesBytes));
  m.addInt("sismo_bytes", static_cast<long long>(sismoBytes));
  m.addInt("total_bytes", static_cast<long long>(totalBytes));
  m.addNum("snapshot_MBps", tSnap > 0 ? snap_bytes_ / mega / tSnap : 0.0);
  m.addNum("io_MBps", tIo > 0 ? (snap_bytes_ + sismoBytes) / mega / tIo : 0.0);

  // memory of the host process
  m.addNum("peak_rss_MiB", peakRssMiB());

  try
  {
    if (!metrics_file_.empty())
    {
      m.writeJson(metrics_file_);
      std::cout << "Metrics written to " << metrics_file_ << std::endl;
    }
    if (!metrics_csv_.empty())
    {
      m.appendCsv(metrics_csv_);
      std::cout << "Metrics appended to " << metrics_csv_ << std::endl;
    }
  }
  catch (const std::exception& e)
  {
    std::cerr << "WARNING: metrics not written: " << e.what() << std::endl;
  }
}

SolverFactory::implemType SEMproxy::getImplem(string implemArg)
{
  if (implemArg == "makutu") return SolverFactory::MAKUTU;
  if (implemArg == "shiva") return SolverFactory::SHIVA;

  throw std::invalid_argument(
      "Implentation type does not follow any valid type.");
}

SolverFactory::meshType SEMproxy::getMesh(string meshArg)
{
  if (meshArg == "cartesian") return SolverFactory::Struct;
  if (meshArg == "ucartesian") return SolverFactory::Unstruct;

  std::cout << "Mesh type found is " << meshArg << std::endl;
  throw std::invalid_argument("Mesh type does not follow any valid type.");
}

SolverFactory::methodType SEMproxy::getMethod(string methodArg)
{
  if (methodArg == "sem") return SolverFactory::SEM;
  if (methodArg == "dg") return SolverFactory::DG;

  throw std::invalid_argument("Method type does not follow any valid type.");
}

float SEMproxy::find_cfl_dt(float cfl_factor)
{
  float sqrtDim3 = 1.73;  // to change for 2d
  float min_spacing = m_mesh->getMinSpacing();
  float v_max = m_mesh->getMaxSpeed();

  float dt = cfl_factor * min_spacing / (sqrtDim3 * v_max);

  return dt;
}

// Prepare the snapshot output: folder, node coordinates, metadata.
// Nothing is done (and nothing is written) if snapshots are disabled.
void SEMproxy::initSnapshots(const SemProxyOptions& opt)
{
  is_snapshots_ = opt.snapshots;
  snap_time_interval_ = opt.snap_interval;
  snap_folder_ = opt.snap_folder;
  if (!is_snapshots_) return;

  namespace fs = std::filesystem;
  fs::create_directories(snap_folder_);

  const int nbNodes = m_mesh->getNumberOfNodes();
  snap_buffer_.resize(nbNodes);

  // Node coordinates: nbNodes x 3 float32, row n = (x, y, z) of node n.
  // Written once, it gives the node <-> coordinates mapping of every snapshot.
  {
    std::vector<float> coords(static_cast<size_t>(nbNodes) * 3);
    for (int n = 0; n < nbNodes; n++)
      for (int d = 0; d < 3; d++)
        coords[static_cast<size_t>(n) * 3 + d] = m_mesh->nodeCoord(n, d);

    std::ofstream f(snap_folder_ + "/nodes.bin", std::ios::binary);
    if (!f) throw std::runtime_error("Cannot write " + snap_folder_ + "/nodes.bin");
    f.write(reinterpret_cast<const char*>(coords.data()),
            coords.size() * sizeof(float));
  }

  // Metadata (JSON) so that a visualisation script knows how to read the files.
  {
    std::ofstream f(snap_folder_ + "/snapshots_meta.json");
    if (!f) throw std::runtime_error("Cannot write snapshots_meta.json");
    f << "{\n"
      << "  \"dtype\": \"float32\",\n"
      << "  \"nodes_file\": \"nodes.bin\",\n"
      << "  \"nodes_shape\": [" << nbNodes << ", 3],\n"
      << "  \"snapshot_pattern\": \"snapshot_<iteration:05d>.bin\",\n"
      << "  \"snapshot_shape\": [" << nbNodes << "],\n"
      << "  \"snap_interval\": " << snap_time_interval_ << ",\n"
      << "  \"dt\": " << dt_ << ",\n"
      << "  \"num_iterations\": " << num_sample_ << ",\n"
      << "  \"order\": " << m_mesh->getOrder() << ",\n"
      << "  \"ex\": " << nb_elements_[0] << ", \"ey\": " << nb_elements_[1]
      << ", \"ez\": " << nb_elements_[2] << ",\n"
      << "  \"lx\": " << domain_size_[0] << ", \"ly\": " << domain_size_[1]
      << ", \"lz\": " << domain_size_[2] << "\n"
      << "}\n";
  }

  std::cout << "Snapshots enabled: every " << snap_time_interval_
            << " iterations in folder '" << snap_folder_ << "'" << std::endl;
}

// Save the newest pressure field. After computeOneStep the new time step is
// stored in column i1 of pnGlobal (updatePressureField writes into i1), so
// this must be called before swap(i1, i2) in run().
void SEMproxy::saveSnapshot(int indexTimeSample)
{
  const auto start = std::chrono::steady_clock::now();

#ifdef USE_KOKKOS
  Kokkos::fence();  // make sure the device is done before reading on the host
#endif

  const int nbNodes = m_mesh->getNumberOfNodes();
  for (int n = 0; n < nbNodes; n++) snap_buffer_[n] = pnGlobal(n, i1);

  std::ostringstream filename;
  filename << snap_folder_ << "/snapshot_" << std::setfill('0') << std::setw(5)
           << indexTimeSample << ".bin";

  std::ofstream f(filename.str(), std::ios::binary);
  if (!f) throw std::runtime_error("Cannot write " + filename.str());
  f.write(reinterpret_cast<const char*>(snap_buffer_.data()),
          snap_buffer_.size() * sizeof(float));
  f.close();

  snap_count_++;
  snap_bytes_ += snap_buffer_.size() * sizeof(float);
  snap_write_seconds_ +=
      std::chrono::duration<double>(std::chrono::steady_clock::now() - start)
          .count();
}
