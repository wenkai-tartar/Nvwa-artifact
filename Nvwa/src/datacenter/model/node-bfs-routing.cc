/*
 * Author: Wenkai Li (v-wenkaili@microsoft.com)
 */

#include "node-bfs-routing.h"
#include "object-memory-profiler.h"

#include "ns3/node-bfs-routing-helper.h"
#include "ns3/enum.h"
#include "ns3/point-to-point-channel.h"

#include <algorithm>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <unordered_map>

namespace ns3
{

NS_LOG_COMPONENT_DEFINE("NodeBfsRouting");

std::chrono::microseconds NodeBfsRouting::lookupTime = std::chrono::microseconds(0);
std::chrono::nanoseconds NodeBfsRouting::lookupTimeNs = std::chrono::nanoseconds(0);
uint64_t NodeBfsRouting::lookupCount = 0;


namespace
{

enum class RouteScopeKind
{
    Output,
    Input,
};

struct RouteTimingStats
{
    uint64_t outputCount{0};
    uint64_t inputCount{0};
    uint64_t ucbCount{0};
    std::chrono::nanoseconds outputNs{0};
    std::chrono::nanoseconds inputNs{0};
    std::chrono::nanoseconds ucbNs{0};
};

bool
RouteTimersEnabled()
{
    static bool enabled = []() -> bool {
        const char* v = std::getenv("NVWA_ROUTE_TIMERS");
        return (v != nullptr) && (v[0] != '\0') && (v[0] != '0');
    }();
    return enabled;
}

RouteTimingStats&
GetRouteTimingStats()
{
    static RouteTimingStats stats;
    return stats;
}

void
AddRouteUcbTiming(std::chrono::nanoseconds elapsed)
{
    if (!RouteTimersEnabled())
    {
        return;
    }
    auto& stats = GetRouteTimingStats();
    stats.ucbNs += elapsed;
    stats.ucbCount += 1;
}

struct RouteScopeTimer
{
    explicit RouteScopeTimer(RouteScopeKind kind)
        : active(RouteTimersEnabled()),
          kind(kind)
    {
        if (active)
        {
            start = std::chrono::high_resolution_clock::now();
        }
    }

    ~RouteScopeTimer()
    {
        if (!active)
        {
            return;
        }
        auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(
            std::chrono::high_resolution_clock::now() - start);
        auto& stats = GetRouteTimingStats();
        if (kind == RouteScopeKind::Output)
        {
            stats.outputNs += elapsed;
            stats.outputCount += 1;
        }
        else
        {
            stats.inputNs += elapsed;
            stats.inputCount += 1;
        }
    }

    bool active{false};
    RouteScopeKind kind{RouteScopeKind::Input};
    std::chrono::high_resolution_clock::time_point start{};
};

void
PrintRouteTimingStats(const std::string& routingLabel)
{
    if (!RouteTimersEnabled())
    {
        return;
    }
    const auto& stats = GetRouteTimingStats();
    const double outputS = static_cast<double>(stats.outputNs.count()) / 1e9;
    const double inputS = static_cast<double>(stats.inputNs.count()) / 1e9;
    const double ucbS = static_cast<double>(stats.ucbNs.count()) / 1e9;
    std::cout << "ROUTE_TIMERS"
              << " routing=" << routingLabel
              << " output_count=" << stats.outputCount
              << " output_s=" << outputS
              << " input_count=" << stats.inputCount
              << " input_s=" << inputS
              << " ucb_count=" << stats.ucbCount
              << " ucb_s=" << ucbS
              << " total_s=" << (outputS + inputS)
              << std::endl;
}

struct ForwardEgressDistribution
{
    std::unordered_map<uint64_t, uint64_t> counts;
    uint64_t total{0};
};

bool
ForwardEgressStatsEnabled()
{
    static bool enabled = []() -> bool {
        const char* v = std::getenv("NVWA_FORWARD_EGRESS_STATS");
        return (v != nullptr) && (v[0] != '\0') && (v[0] != '0');
    }();
    return enabled;
}

ForwardEgressDistribution&
GetForwardEgressDistribution()
{
    static ForwardEgressDistribution stats;
    return stats;
}

void
RecordForwardEgress(uint32_t nodeId, uint32_t outIf)
{
    if (!ForwardEgressStatsEnabled())
    {
        return;
    }
    auto& stats = GetForwardEgressDistribution();
    const uint64_t key = (static_cast<uint64_t>(nodeId) << 32) | outIf;
    stats.counts[key] += 1;
    stats.total += 1;
}

void
PrintForwardEgressDistribution(const std::string& routingLabel)
{
    if (!ForwardEgressStatsEnabled())
    {
        return;
    }
    auto& stats = GetForwardEgressDistribution();
    std::vector<std::pair<uint64_t, uint64_t>> entries(stats.counts.begin(), stats.counts.end());
    std::sort(entries.begin(), entries.end(), [](const auto& a, const auto& b) {
        if (a.second != b.second)
        {
            return a.second > b.second;
        }
        return a.first < b.first;
    });
    const uint64_t maxCount = entries.empty() ? 0 : entries.front().second;
    const double avg = entries.empty() ? 0.0 : static_cast<double>(stats.total) / entries.size();
    std::cout << "FORWARD_EGRESS_STATS"
              << " routing=" << routingLabel
              << " total=" << stats.total
              << " active_egress=" << entries.size()
              << " avg_per_egress=" << avg
              << " max_per_egress=" << maxCount
              << std::endl;
    const size_t limit = std::min<size_t>(entries.size(), 10);
    for (size_t i = 0; i < limit; ++i)
    {
        const uint32_t nodeId = static_cast<uint32_t>(entries[i].first >> 32);
        const uint32_t outIf = static_cast<uint32_t>(entries[i].first & 0xffffffffULL);
        std::cout << "FORWARD_EGRESS_TOP"
                  << " routing=" << routingLabel
                  << " rank=" << (i + 1)
                  << " node=" << nodeId
                  << " outIf=" << outIf
                  << " count=" << entries[i].second
                  << std::endl;
    }
}
} // namespace

TypeId
NodeBfsRouting::GetTypeId()
{
    static TypeId tid = TypeId("ns3::NodeBfsRouting")
                            .SetParent<Object>()
                            .SetGroupName("Datacenter")
                            .AddAttribute("RandomEcmp",
                                          "Legacy ECMP toggle (true->kByHash, false->kFirst)",
                                          BooleanValue(false),
                                          MakeBooleanAccessor(&NodeBfsRouting::SetRandomEcmp,
                                                              &NodeBfsRouting::GetRandomEcmp),
                                          MakeBooleanChecker())
                            .AddAttribute(
                                "EcmpPolicy",
                                "Port selection policy for ECMP",
                                EnumValue(PortSelectPolicy::kFirst),
                                MakeEnumAccessor<PortSelectPolicy>(
                                    &NodeBfsRouting::GetPortSelectPolicy,
                                    &NodeBfsRouting::SetPortSelectPolicy),
                                MakeEnumChecker(PortSelectPolicy::kFirst,
                                                "kFirst",
                                                PortSelectPolicy::kRandom,
                                                "kRandom",
                                                PortSelectPolicy::kByHash,
                                                "kByHash"));
    return tid;
}

NodeBfsRouting::NodeBfsRouting()
    : m_ipv4(nullptr),
      m_node(nullptr),
      m_topo(nullptr)
{
    NS_LOG_FUNCTION(this);
}

NodeBfsRouting::NodeBfsRouting(Ptr<Node> node, Ptr<StructuredTopology> topo)
    : m_ipv4(nullptr),
      m_node(node),
      m_topo(topo)
{
    NS_LOG_FUNCTION(this);
    m_nodeId = node->GetId();
}

NodeBfsRouting::~NodeBfsRouting()
{
    NS_LOG_FUNCTION(this);
    m_ipv4 = nullptr;
    m_topo = nullptr;
    m_node = nullptr;
}

uint32_t
NodeBfsRouting::ComputeFlowHash(const Ipv4Header& h, Ptr<const Packet> p)
{
    // Extract 5-tuple for flow identification
    union {
        uint8_t u8[12];  // 12 bytes: SIP(4) + DIP(4) + Sport(2) + Dport(2)
        uint32_t u32[3];
    } buf;

    buf.u32[0] = h.GetSource().Get();       // Source IP
    buf.u32[1] = h.GetDestination().Get();  // Destination IP

    // Extract ports from TCP/UDP header
    uint16_t sport = 0;
    uint16_t dport = 0;

    if (p && (h.GetProtocol() == 6 || h.GetProtocol() == 17)) {  // TCP or UDP
        Ptr<Packet> pkt = p->Copy();
        ObjectMemoryProfiler::Get().RecordEvent("ns3::Packet::Copy(route_hash.NodeBfs)",
                                                1,
                                                pkt->GetSize());
        if (pkt->GetSize() >= 4) {
            uint8_t portBuf[4];
            pkt->CopyData(portBuf, 4);
            sport = (portBuf[0] << 8) | portBuf[1];
            dport = (portBuf[2] << 8) | portBuf[3];
        }
    }

    buf.u32[2] = sport | ((uint32_t)dport << 16);

    // MurmurHash3 algorithm
    // Use node ID as seed for per-node path diversity (consistent with RuleBased routing)
    uint32_t hash = m_nodeId;

    // Process 32-bit blocks
    for (int i = 0; i < 3; i++) {
        uint32_t k = buf.u32[i];
        k *= 0xcc9e2d51;
        k = (k << 15) | (k >> 17);
        k *= 0x1b873593;
        hash ^= k;
        hash = (hash << 13) | (hash >> 19);
        hash = hash * 5 + 0xe6546b64;
    }

    // Finalization
    hash ^= 12;
    hash ^= hash >> 16;
    hash *= 0x85ebca6b;
    hash ^= hash >> 13;
    hash *= 0xc2b2ae35;
    hash ^= hash >> 16;

    return hash;
}

Ptr<Ipv4Route>
NodeBfsRouting::LookupNodeBfs(const Ipv4Header& header, Ptr<const Packet> p, Ptr<NetDevice> oif)
{
    NS_LOG_FUNCTION(this << header.GetDestination() << oif);
    NS_LOG_LOGIC("Looking for route for destination " << header.GetDestination());

    struct LookupTimer
    {
        LookupTimer(std::chrono::microseconds& total,
                    std::chrono::nanoseconds& totalNs,
                    uint64_t& count)
            : totalTime(total),
              totalTimeNs(totalNs),
              totalCount(count),
              start(std::chrono::high_resolution_clock::now())
        {
        }
        ~LookupTimer()
        {
            auto end = std::chrono::high_resolution_clock::now();
            auto elapsed = end - start;
            auto duration = std::chrono::duration_cast<std::chrono::microseconds>(elapsed);
            auto durationNs = std::chrono::duration_cast<std::chrono::nanoseconds>(elapsed);
            totalTime += duration;
            totalTimeNs += durationNs;
            totalCount += 1;
        }
        std::chrono::microseconds& totalTime;
        std::chrono::nanoseconds& totalTimeNs;
        uint64_t& totalCount;
        std::chrono::high_resolution_clock::time_point start;
    } timer(lookupTime, lookupTimeNs, lookupCount);

    Ptr<Ipv4Route> rtentry = nullptr;

    auto entry = m_rtTable.find(header.GetDestination().Get());

    // no matching entry
    if (entry == m_rtTable.end())
    {
        return nullptr;
    }

    // entry found
    auto& nexthops = entry->second;
    RoutingContext ctx;
    if (m_portSelectPolicy != PortSelectPolicy::kFirst)
    {
        // Compute flow hash using 5-tuple (similar to RuleBasedRouting)
        ctx.SetFlowHash(ComputeFlowHash(header, p));
    }
    PortSelector selector(m_portSelectPolicy);
    auto maybeOut = selector.Pick(nexthops, ctx);
    if (!maybeOut.has_value())
    {
        return nullptr;
    }
    uint32_t outInterface = *maybeOut;

    RecordForwardEgress(m_nodeId, outInterface);

    // create a Ipv4Route object from the selected routing table entry
    rtentry = Create<Ipv4Route>();
    ObjectMemoryProfiler::Get().RecordEvent("ns3::Ipv4Route(NodeBfs)");
    rtentry->SetDestination(header.GetDestination());
    /// \todo handle multi-address case
    Ptr<NetDevice> outDevice = m_node->GetDevice(outInterface);
    rtentry->SetSource(m_ipv4->GetAddress(outInterface, 0).GetLocal());

    Ptr<PointToPointChannel> channel = DynamicCast<PointToPointChannel>(outDevice->GetChannel());
    Ptr<NetDevice> remoteDevice = nullptr;
    for (uint32_t i = 0; i < channel->GetNDevices(); i++)
    {
        if (channel->GetDevice(i) != outDevice)
        {
            remoteDevice = channel->GetDevice(i);
            break;
        }
    }
    Ptr<Ipv4> remoteIpv4 = remoteDevice->GetNode()->GetObject<Ipv4>();
    uint32_t remoteInterfaceIndex = remoteIpv4->GetInterfaceForDevice(remoteDevice);
    Ipv4Address nextHop = remoteIpv4->GetAddress(remoteInterfaceIndex, 0).GetLocal();
    rtentry->SetGateway(nextHop);
    rtentry->SetOutputDevice(outDevice);
    return rtentry;
}

Ptr<Ipv4Route>
NodeBfsRouting::RouteOutput(Ptr<Packet> p,
                            const Ipv4Header& header,
                            Ptr<NetDevice> oif,
                            Socket::SocketErrno& sockerr)
{
    RouteScopeTimer routeTimer(RouteScopeKind::Output);
    NS_LOG_FUNCTION(this << p << &header << oif << &sockerr);
    //
    // First, see if this is a multicast packet we have a route for.  If we
    // have a route, then send the packet down each of the specified interfaces.
    //
    if (header.GetDestination().IsMulticast())
    {
        NS_LOG_LOGIC("Multicast destination-- returning false");
        return nullptr; // Let other routing protocols try to handle this
    }
    //
    // See if this is a unicast packet we have a route for.
    //
    NS_LOG_LOGIC("Unicast destination- looking up");

    Ptr<Ipv4Route> rtentry = LookupNodeBfs(header, p, oif);

    if (rtentry)
    {
        sockerr = Socket::ERROR_NOTERROR;
    }
    else
    {
        sockerr = Socket::ERROR_NOROUTETOHOST;
    }
    return rtentry;
}

bool
NodeBfsRouting::RouteInput(Ptr<const Packet> p,
                           const Ipv4Header& header,
                           Ptr<const NetDevice> idev,
                           const UnicastForwardCallback& ucb,
                           const MulticastForwardCallback& mcb,
                           const LocalDeliverCallback& lcb,
                           const ErrorCallback& ecb)
{
    RouteScopeTimer routeTimer(RouteScopeKind::Input);
    NS_LOG_FUNCTION(this << p << header << header.GetSource() << header.GetDestination() << idev
                         << &lcb << &ecb);
    // Check if input device supports IP
    NS_ASSERT(m_ipv4->GetInterfaceForDevice(idev) >= 0);
    uint32_t iif = m_ipv4->GetInterfaceForDevice(idev);

    if (m_ipv4->IsDestinationAddress(header.GetDestination(), iif))
    {
        if (!lcb.IsNull())
        {
            NS_LOG_LOGIC("Local delivery to " << header.GetDestination());
            lcb(p, header, iif);
            return true;
        }
        else
        {
            // The local delivery callback is null.  This may be a multicast
            // or broadcast packet, so return false so that another
            // multicast routing protocol can handle it.  It should be possible
            // to extend this to explicitly check whether it is a unicast
            // packet, and invoke the error callback if so
            return false;
        }
    }

    // Check if input device supports IP forwarding
    if (!m_ipv4->IsForwarding(iif))
    {
        NS_LOG_LOGIC("Forwarding disabled for this interface");
        ecb(p, header, Socket::ERROR_NOROUTETOHOST);
        return true;
    }
    // Next, try to find a route
    NS_LOG_LOGIC("Unicast destination- looking up global route");

    Ptr<Ipv4Route> rtentry = LookupNodeBfs(header, p, nullptr);

    if (rtentry)
    {
        NS_LOG_LOGIC("Found unicast destination- calling unicast callback");
        if (RouteTimersEnabled())
        {
            auto ucbStart = std::chrono::high_resolution_clock::now();
            ucb(rtentry, p, header);
            AddRouteUcbTiming(std::chrono::duration_cast<std::chrono::nanoseconds>(
                std::chrono::high_resolution_clock::now() - ucbStart));
        }
        else
        {
            ucb(rtentry, p, header);
        }
        return true;
    }
    else
    {
        NS_LOG_LOGIC("Did not find unicast destination- returning false");
        return false; // Let other routing protocols try to handle this
                      // route request.
    }
}

void
NodeBfsRouting::NotifyInterfaceUp(uint32_t i)
{
    NS_LOG_FUNCTION(this << i);
    if (m_topo)
    {
        NodeBfsRoutingHelper::RecalculateRoutes(m_topo);
    }
}

void
NodeBfsRouting::NotifyInterfaceDown(uint32_t i)
{
    NS_LOG_FUNCTION(this << i);
    if (m_topo)
    {
        NodeBfsRoutingHelper::RecalculateRoutes(m_topo);
    }
}

void
NodeBfsRouting::NotifyAddAddress(uint32_t interface, Ipv4InterfaceAddress address)
{
    NS_LOG_FUNCTION(this << interface << address);
}

void
NodeBfsRouting::NotifyRemoveAddress(uint32_t interface, Ipv4InterfaceAddress address)
{
    NS_LOG_FUNCTION(this << interface << address);
}

void
NodeBfsRouting::DoDispose()
{
    NS_LOG_FUNCTION(this);
    m_topo = nullptr;

    Ipv4RoutingProtocol::DoDispose();
}

void
NodeBfsRouting::SetIpv4(Ptr<Ipv4> ipv4)
{
    NS_LOG_FUNCTION(this << ipv4);
    NS_ASSERT(!m_ipv4 && ipv4);
    m_ipv4 = ipv4;
}

void
NodeBfsRouting::SetTopology(Ptr<StructuredTopology> topo)
{
    NS_LOG_FUNCTION(this << topo);
    NS_ASSERT(topo);
    if (!m_topo)
    {
        m_topo = topo;
    }
}

void
NodeBfsRouting::PrintRoutingTable(Ptr<OutputStreamWrapper> stream, Time::Unit unit) const
{
    NS_LOG_FUNCTION(this << stream);
}

void
NodeBfsRouting::PrintRoutingTable() const
{
    std::cout << m_node->GetId() << " Routing table: " << std::endl;
    for (auto i = m_rtTable.begin(); i != m_rtTable.end(); i++)
    {
        uint32_t dst = i->first;
        std::vector<uint32_t> nexts = i->second;
        for (uint32_t k = 0; k < (uint32_t)nexts.size(); k++)
        {
            uint32_t interface = nexts[k];
            std::cout << "To " << dst << " from port: " << interface << std::endl;
        }
    }
}

void
NodeBfsRouting::AddTableEntry(Ipv4Address& dstAddr, uint32_t interface)
{
    uint32_t dip = dstAddr.Get();
    m_rtTable[dip].push_back(interface);
    std::sort(m_rtTable[dip].begin(), m_rtTable[dip].end());
}

void
NodeBfsRouting::SetPortSelectPolicy(PortSelectPolicy policy)
{
    m_portSelectPolicy = policy;
}

PortSelectPolicy
NodeBfsRouting::GetPortSelectPolicy() const
{
    return m_portSelectPolicy;
}

void
NodeBfsRouting::PrintForwardingStats(const std::string& routingLabel)
{
    const double total_s = static_cast<double>(lookupTime.count()) / 1e6;
    const double total_ns_s = static_cast<double>(lookupTimeNs.count()) / 1e9;
    const double avg_s = (lookupCount == 0) ? 0.0 : (total_ns_s / static_cast<double>(lookupCount));
    const auto flags = std::cout.flags();
    const auto precision = std::cout.precision();
    std::cout << std::fixed << std::setprecision(6);
    std::cout << "FORWARD_STATS"
              << " routing=" << routingLabel
              << " count=" << lookupCount
              << " total_s=" << total_s
              << " total_ns_s=" << total_ns_s
              << " avg_s=" << avg_s
              << std::endl;
    PrintForwardEgressDistribution(routingLabel);
    PrintRouteTimingStats(routingLabel);
    std::cout.flags(flags);
    std::cout.precision(precision);
}

void
NodeBfsRouting::SetRandomEcmp(bool enable)
{
    m_portSelectPolicy = enable ? PortSelectPolicy::kByHash : PortSelectPolicy::kFirst;
}

bool
NodeBfsRouting::GetRandomEcmp() const
{
    return m_portSelectPolicy != PortSelectPolicy::kFirst;
}

void
NodeBfsRouting::ClearRoutingTable()
{
    m_rtTable.clear();
}

} /* namespace ns3 */
