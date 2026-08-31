/*
 * Lightweight object-level counters for memory profiling experiments.
 */

#pragma once

#include <cstdint>
#include <iosfwd>
#include <string>
#include <unordered_map>

namespace ns3
{

class ObjectMemoryProfiler
{
  public:
    struct Counter
    {
        uint64_t created{0};
        uint64_t destroyed{0};
        uint64_t live{0};
        uint64_t maxLive{0};
        uint64_t bytes{0};
        uint64_t liveBytes{0};
        uint64_t maxLiveBytes{0};
    };

    static ObjectMemoryProfiler& Get();

    void Reset();
    void SetEnabled(bool enabled);
    bool IsEnabled() const;

    void RecordCreate(const std::string& object, uint64_t bytes = 0);
    void RecordDestroy(const std::string& object, uint64_t bytes = 0);
    void RecordEvent(const std::string& object, uint64_t count = 1, uint64_t bytes = 0);
    void Print(std::ostream& os) const;

  private:
    bool m_enabled{false};
    std::unordered_map<std::string, Counter> m_counters;
};

} // namespace ns3
