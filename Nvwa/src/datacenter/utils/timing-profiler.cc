/*
 * Copyright (c) 2025 Microsoft Research Asia
 *
 * SPDX-License-Identifier: GPL-2.0-only
 *
 * Authors: Wenkai Li <wkli24@stu.xjtu.edu.cn>
 */

#include "timing-profiler.h"

#include "ns3/log.h"

#include <limits>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("TimingProfiler");

TimingProfiler*
TimingProfiler::GetInstance()
{
    return TimingProfilerSingleton::Get();
}

TimingProfiler::TimingProfiler()
{
    NS_LOG_FUNCTION(this);
}

TimingProfiler::~TimingProfiler()
{
    NS_LOG_FUNCTION(this);
}

void
TimingProfiler::StartTimer(const std::string& operation)
{
    NS_LOG_FUNCTION(this << operation);
    m_activeTimers[operation] = std::chrono::high_resolution_clock::now();
}

void
TimingProfiler::EndTimer(const std::string& operation)
{
    NS_LOG_FUNCTION(this << operation);

    auto it = m_activeTimers.find(operation);
    if (it == m_activeTimers.end())
    {
        NS_LOG_WARN("Timer for operation '" << operation << "' was not started");
        return;
    }

    auto endTime = std::chrono::high_resolution_clock::now();
    auto duration = std::chrono::duration_cast<std::chrono::microseconds>(endTime - it->second);
    double elapsedSeconds = duration.count() / 1e6;

    m_activeTimers.erase(it);

    // Update statistics
    OperationStats& stats = m_operationStats[operation];
    stats.callCount++;
    stats.totalTime += elapsedSeconds;
    stats.minTime = std::min(stats.minTime, elapsedSeconds);
    stats.maxTime = std::max(stats.maxTime, elapsedSeconds);
    stats.avgTime = stats.totalTime / stats.callCount;

    NS_LOG_INFO("Operation '" << operation << "' completed in " << elapsedSeconds << " seconds");
}

double
TimingProfiler::GetElapsedTime(const std::string& operation) const
{
    auto it = m_operationStats.find(operation);
    return (it != m_operationStats.end()) ? it->second.totalTime : 0.0;
}

const TimingProfiler::OperationStats&
TimingProfiler::GetOperationStats(const std::string& operation) const
{
    static OperationStats emptyStats;
    auto it = m_operationStats.find(operation);
    return (it != m_operationStats.end()) ? it->second : emptyStats;
}

void
TimingProfiler::PrintTimingReport() const
{
    std::cout << "\n========================================" << std::endl;
    std::cout << "        TIMING PROFILER REPORT" << std::endl;
    std::cout << "========================================" << std::endl;

    for (const auto& pair : m_operationStats)
    {
        const std::string& operation = pair.first;
        const OperationStats& stats = pair.second;

        std::cout << "\nOperation: " << operation << std::endl;
        std::cout << "├─ Call Count: " << stats.callCount << std::endl;
        std::cout << "├─ Total Time: " << std::fixed << std::setprecision(6) << stats.totalTime
                  << " s" << std::endl;
        std::cout << "├─ Average Time: " << std::fixed << std::setprecision(6) << stats.avgTime
                  << " s" << std::endl;
        std::cout << "├─ Min Time: " << std::fixed << std::setprecision(6) << stats.minTime << " s"
                  << std::endl;
        std::cout << "└─ Max Time: " << std::fixed << std::setprecision(6) << stats.maxTime << " s"
                  << std::endl;
    }

    std::cout << "\n========================================" << std::endl;
}

void
TimingProfiler::Reset()
{
    m_activeTimers.clear();
    m_operationStats.clear();
}

} // namespace ns3