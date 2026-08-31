/*
 * Copyright (c) 2025 Microsoft Research Asia
 *
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * Authors: Wenkai Li <wkli24@stu.xjtu.edu.cn>
 */

#ifndef TIMING_PROFILER_H
#define TIMING_PROFILER_H

#include "ns3/simulation-singleton.h"

#include <chrono>
#include <iomanip>
#include <iostream>
#include <map>
#include <string>
#include <vector>

namespace ns3
{

class TimingProfiler
{
  public:
    static TimingProfiler* GetInstance();

    void StartTimer(const std::string& operation);
    void EndTimer(const std::string& operation);

    double GetElapsedTime(const std::string& operation) const; // 返回秒数
    void PrintTimingReport() const;
    void Reset();

    // For detailed per-operation statistics
    struct OperationStats
    {
        uint32_t callCount = 0;
        double totalTime = 0.0; // 秒数
        double minTime = std::numeric_limits<double>::max();
        double maxTime = std::numeric_limits<double>::min();
        double avgTime = 0.0;
    };

    const OperationStats& GetOperationStats(const std::string& operation) const;

  private:
    friend class SimulationSingleton<TimingProfiler>;

    TimingProfiler();
    ~TimingProfiler();

    std::map<std::string, std::chrono::high_resolution_clock::time_point> m_activeTimers;
    std::map<std::string, OperationStats> m_operationStats;
};

// Declare as SimulationSingleton
typedef SimulationSingleton<TimingProfiler> TimingProfilerSingleton;

} // namespace ns3

#endif /* TIMING_PROFILER_H */