#include "object-memory-profiler.h"

#include <algorithm>
#include <ostream>
#include <vector>

namespace ns3
{

ObjectMemoryProfiler&
ObjectMemoryProfiler::Get()
{
    static ObjectMemoryProfiler profiler;
    return profiler;
}

void
ObjectMemoryProfiler::Reset()
{
    m_counters.clear();
}

void
ObjectMemoryProfiler::SetEnabled(bool enabled)
{
    m_enabled = enabled;
}

bool
ObjectMemoryProfiler::IsEnabled() const
{
    return m_enabled;
}

void
ObjectMemoryProfiler::RecordCreate(const std::string& object, uint64_t bytes)
{
    if (!m_enabled)
    {
        return;
    }
    Counter& c = m_counters[object];
    c.created += 1;
    c.live += 1;
    c.bytes += bytes;
    c.liveBytes += bytes;
    c.maxLive = std::max(c.maxLive, c.live);
    c.maxLiveBytes = std::max(c.maxLiveBytes, c.liveBytes);
}

void
ObjectMemoryProfiler::RecordDestroy(const std::string& object, uint64_t bytes)
{
    if (!m_enabled)
    {
        return;
    }
    Counter& c = m_counters[object];
    c.destroyed += 1;
    if (c.live > 0)
    {
        c.live -= 1;
    }
    if (bytes > 0 && c.liveBytes >= bytes)
    {
        c.liveBytes -= bytes;
    }
}

void
ObjectMemoryProfiler::RecordEvent(const std::string& object, uint64_t count, uint64_t bytes)
{
    if (!m_enabled)
    {
        return;
    }
    Counter& c = m_counters[object];
    c.created += count;
    c.bytes += bytes;
}

void
ObjectMemoryProfiler::Print(std::ostream& os) const
{
    if (!m_enabled)
    {
        return;
    }

    std::vector<std::pair<std::string, Counter>> entries(m_counters.begin(), m_counters.end());
    std::sort(entries.begin(), entries.end(), [](const auto& a, const auto& b) {
        if (a.second.bytes != b.second.bytes)
        {
            return a.second.bytes > b.second.bytes;
        }
        return a.first < b.first;
    });

    for (const auto& [name, c] : entries)
    {
        os << "Object memory profile:"
           << " object=" << name
           << " created=" << c.created
           << " destroyed=" << c.destroyed
           << " live=" << c.live
           << " max_live=" << c.maxLive
           << " bytes=" << c.bytes
           << " live_bytes=" << c.liveBytes
           << " max_live_bytes=" << c.maxLiveBytes
           << '\n';
    }
}

} // namespace ns3
