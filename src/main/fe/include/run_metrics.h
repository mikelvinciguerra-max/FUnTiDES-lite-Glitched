#pragma once

// Tiny, dependency-free collector of run metrics (timings, sizes, parameters).
// One RunMetrics = one run = one flat list of (key, value).
//   - writeJson(path)  : the run as a JSON object (one file per run)
//   - appendCsv(path)  : one CSV row appended to a shared file (header written
//                        once, so a benchmark can accumulate all its runs)

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

class RunMetrics
{
 public:
  void addInt(const std::string& key, long long v)
  {
    entries_.push_back({key, std::to_string(v), false});
  }

  void addNum(const std::string& key, double v)
  {
    std::ostringstream s;
    s << std::setprecision(9) << v;
    entries_.push_back({key, s.str(), false});
  }

  void addStr(const std::string& key, const std::string& v)
  {
    entries_.push_back({key, v, true});
  }

  void writeJson(const std::string& path) const
  {
    makeParentDir(path);
    std::ofstream f(path);
    if (!f) throw std::runtime_error("Cannot write " + path);
    f << "{\n";
    for (size_t i = 0; i < entries_.size(); i++)
    {
      const Entry& e = entries_[i];
      f << "  \"" << e.key << "\": "
        << (e.isString ? "\"" + jsonEscape(e.value) + "\"" : e.value)
        << (i + 1 < entries_.size() ? ",\n" : "\n");
    }
    f << "}\n";
  }

  // Appends one row. The header is written if the file is new or empty.
  // If the file already has another header (different set of columns), the
  // row is NOT appended, to avoid mixing incompatible runs in one table.
  void appendCsv(const std::string& path) const
  {
    makeParentDir(path);

    std::string header, row;
    for (size_t i = 0; i < entries_.size(); i++)
    {
      header += (i ? "," : "") + entries_[i].key;
      row += (i ? "," : "") + csvEscape(entries_[i].value);
    }

    std::string existing;
    {
      std::ifstream in(path);
      if (in) std::getline(in, existing);
    }
    if (!existing.empty() && existing != header)
      throw std::runtime_error(
          path + " already exists with different columns; use another file");

    std::ofstream f(path, std::ios::app);
    if (!f) throw std::runtime_error("Cannot write " + path);
    std::string out;
    if (existing.empty()) out += header + "\n";
    out += row + "\n";
    f << out;  // a single write: safe enough for concurrent appends
  }

 private:
  struct Entry
  {
    std::string key;
    std::string value;
    bool isString;
  };
  std::vector<Entry> entries_;

  static void makeParentDir(const std::string& path)
  {
    const auto parent = std::filesystem::path(path).parent_path();
    if (!parent.empty()) std::filesystem::create_directories(parent);
  }

  static std::string jsonEscape(const std::string& s)
  {
    std::string r;
    for (char c : s)
    {
      if (c == '"' || c == '\\') r += '\\';
      r += (c == '\n') ? ' ' : c;
    }
    return r;
  }

  static std::string csvEscape(const std::string& s)
  {
    if (s.find_first_of(",\"\n") == std::string::npos) return s;
    std::string r = "\"";
    for (char c : s)
    {
      if (c == '"') r += '"';
      r += c;
    }
    return r + "\"";
  }
};

// Peak resident memory of this process in MiB (Linux: VmHWM), or -1.
inline double peakRssMiB()
{
  std::ifstream f("/proc/self/status");
  std::string line;
  while (std::getline(f, line))
  {
    if (line.rfind("VmHWM:", 0) == 0)
      return std::atof(line.c_str() + 6) / 1024.0;  // value is in kB
  }
  return -1.0;
}
