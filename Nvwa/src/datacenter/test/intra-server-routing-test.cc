/*
 * Copyright (c) 2026 Microsoft Research Asia
 *
 * SPDX-License-Identifier: GPL-2.0-only
 */

#include "ns3/core-module.h"
#include "ns3/datacenter-module.h"
#include "ns3/internet-module.h"
#include "ns3/packet.h"
#include "ns3/test.h"

#include <cstdint>
#include <sstream>
#include <string>
#include <utility>
#include <vector>

using namespace ns3;

namespace
{

struct Hop
{
    uint32_t level{UINT32_MAX};
    uint32_t local{UINT32_MAX};
};

std::string
TraceToString(const std::vector<Hop>& trace)
{
    std::ostringstream os;
    for (size_t i = 0; i < trace.size(); ++i)
    {
        if (i > 0)
        {
            os << " -> ";
        }
        os << "L" << trace[i].level << ":" << trace[i].local;
    }
    return os.str();
}

bool
TraceEquals(const std::vector<Hop>& trace, const std::vector<Hop>& expected)
{
    if (trace.size() != expected.size())
    {
        return false;
    }
    for (size_t i = 0; i < trace.size(); ++i)
    {
        if (trace[i].level != expected[i].level || trace[i].local != expected[i].local)
        {
            return false;
        }
    }
    return true;
}

Ipv4Address
FirstNonLoopbackAddress(Ptr<Node> node)
{
    Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
    for (uint32_t iface = 1; iface < ipv4->GetNInterfaces(); ++iface)
    {
        if (ipv4->GetNAddresses(iface) > 0)
        {
            return ipv4->GetAddress(iface, 0).GetLocal();
        }
    }
    return Ipv4Address::GetZero();
}

Ptr<Packet>
CreateUdpPacket()
{
    Ptr<Packet> packet = Create<Packet>(100);
    uint8_t udpHeader[8] = {0xC0, 0x01, 0x00, 0x09, 0, 0, 0, 0};
    packet->AddAtEnd(Create<Packet>(udpHeader, 8));
    return packet;
}

Hop
FindNodeLocation(const StructuredTopology& topo, Ptr<Node> node)
{
    for (uint32_t level = 0; level < topo.GetNumLevels(); ++level)
    {
        const NodeContainer& nodes = topo.GetLevel(level);
        for (uint32_t local = 0; local < nodes.GetN(); ++local)
        {
            if (nodes.Get(local) == node)
            {
                return Hop{level, local};
            }
        }
    }
    return Hop{};
}

Hop
PeerForDevice(const StructuredTopology& topo, Ptr<NetDevice> outputDevice)
{
    Ptr<Channel> channel = outputDevice->GetChannel();
    if (!channel)
    {
        return Hop{};
    }

    for (uint32_t i = 0; i < channel->GetNDevices(); ++i)
    {
        Ptr<NetDevice> peerDevice = channel->GetDevice(i);
        if (peerDevice != outputDevice)
        {
            return FindNodeLocation(topo, peerDevice->GetNode());
        }
    }
    return Hop{};
}

std::vector<Hop>
BuildRuleBasedTrace(const StructuredTopology& topo, uint32_t srcHostLocal, uint32_t dstHostLocal)
{
    Ptr<Node> srcNode = topo.GetNodeByLocal(0, srcHostLocal);
    Ptr<Node> dstNode = topo.GetNodeByLocal(0, dstHostLocal);

    Ipv4Header header;
    header.SetSource(FirstNonLoopbackAddress(srcNode));
    header.SetDestination(FirstNonLoopbackAddress(dstNode));
    header.SetProtocol(17);

    Ptr<Packet> packet = CreateUdpPacket();
    std::vector<Hop> trace;
    Hop current{0, srcHostLocal};
    trace.push_back(current);

    for (uint32_t hop = 0; hop < 8 && !(current.level == 0 && current.local == dstHostLocal); ++hop)
    {
        Ptr<Node> node = topo.GetNodeByLocal(current.level, current.local);
        Ptr<Ipv4> ipv4 = node->GetObject<Ipv4>();
        Ptr<RuleBasedRouting> routing = DynamicCast<RuleBasedRouting>(ipv4->GetRoutingProtocol());
        if (!routing)
        {
            trace.push_back(Hop{});
            break;
        }

        Ptr<Ipv4Route> route = routing->Lookup(header, packet, nullptr, nullptr, current.level == 0);
        if (!route)
        {
            trace.push_back(Hop{});
            break;
        }

        current = PeerForDevice(topo, route->GetOutputDevice());
        trace.push_back(current);
    }

    return trace;
}

Ptr<StructuredTopology>
BuildIntraServerRailTopology()
{
    RoutingRuleManager::GetInstance()->Clear();
    StructuredAddressDirectory::Get()->Clear();

    std::shared_ptr<TopologyHelper> topoHelper = std::make_shared<TopologyHelper>();
    RuleBasedRoutingHelper ruleBasedRoutingHelper;
    topoHelper->GetInternetStack().SetRoutingHelper(ruleBasedRoutingHelper);

    LevelTemplate::LinkProfile nvlink{DataRate("900Gbps"), NanoSeconds(100)};
    LevelTemplate::LinkProfile network{DataRate("100Gbps"), MicroSeconds(1)};

    TopologyBuilder builder;

    Ptr<IntraServerLevelTemplate> intra =
        CreateObject<IntraServerLevelTemplate>(4, 4, std::string("FullMesh"), nvlink);
    intra->SetTopologyHelper(topoHelper);
    builder.AddLevel(intra);

    Ptr<ClosInterLevelTemplate> gpuToAsw = CreateObject<ClosInterLevelTemplate>(1,
                                                                                0,
                                                                                8,
                                                                                1,
                                                                                1,
                                                                                std::string("RailOptimized"),
                                                                                4,
                                                                                2,
                                                                                network);
    gpuToAsw->SetTopologyHelper(topoHelper);
    builder.AddLevel(gpuToAsw);

    Ptr<ClosInterLevelTemplate> aswToPsw =
        CreateObject<ClosInterLevelTemplate>(2, 0, 2, 1, 1, network);
    aswToPsw->SetTopologyHelper(topoHelper);
    builder.AddLevel(aswToPsw);

    Ptr<StructuredTopology> topo = CreateObject<StructuredTopology>(topoHelper);
    builder.Build(topo);
    topo->RegisterAddresses();
    ruleBasedRoutingHelper.Initialize(*topo);
    return topo;
}

class IntraServerRoutingTraceTestCase : public TestCase
{
  public:
    IntraServerRoutingTraceTestCase()
        : TestCase("IntraServer RuleBased routing trace")
    {
    }

  private:
    void AssertTrace(const StructuredTopology& topo,
                     uint32_t srcHostLocal,
                     uint32_t dstHostLocal,
                     const std::vector<Hop>& expected,
                     const std::string& label)
    {
        std::vector<Hop> trace = BuildRuleBasedTrace(topo, srcHostLocal, dstHostLocal);
        NS_TEST_ASSERT_MSG_EQ(TraceEquals(trace, expected),
                              true,
                              label << ": expected " << TraceToString(expected) << ", got "
                                    << TraceToString(trace));
    }

    void DoRun() override
    {
        Simulator::Destroy();
        Ptr<StructuredTopology> topo = BuildIntraServerRailTopology();

        NS_TEST_ASSERT_MSG_EQ(topo->GetLevel(0).GetN(), 16u, "Expected 16 endpoints");
        NS_TEST_ASSERT_MSG_EQ(topo->GetLevel(1).GetN(), 8u, "Expected 8 ASWs");
        NS_TEST_ASSERT_MSG_EQ(topo->GetLevel(2).GetN(), 2u, "Expected 2 PSWs");

        // Server-major endpoint layout, 4 endpoints per server:
        // server0: hosts 0..3, server1: 4..7, server2: 8..11, server3: 12..15.
        // RailOptimized ASW layout, 2 servers per segment:
        // segment0 rails: ASW 0..3, segment1 rails: ASW 4..7.
        AssertTrace(*topo,
                    0,
                    1,
                    {{0, 0}, {0, 1}},
                    "same server should use intra-server same-level link");

        AssertTrace(*topo,
                    0,
                    4,
                    {{0, 0}, {1, 0}, {0, 4}},
                    "same rail and same ASW segment should go endpoint -> ASW -> endpoint");

        AssertTrace(*topo,
                    0,
                    8,
                    {{0, 0}, {1, 0}, {2, 0}, {1, 4}, {0, 8}},
                    "same rail and different ASW segment should go through PSW to target ASW");

        AssertTrace(*topo,
                    0,
                    9,
                    {{0, 0}, {1, 0}, {2, 0}, {1, 5}, {0, 9}},
                    "different rail and different segment should choose the destination rail ASW");

        Simulator::Destroy();
        RoutingRuleManager::GetInstance()->Clear();
        StructuredAddressDirectory::Get()->Clear();
    }
};

class IntraServerRoutingTestSuite : public TestSuite
{
  public:
    IntraServerRoutingTestSuite()
        : TestSuite("intra-server-routing", Type::UNIT)
    {
        AddTestCase(new IntraServerRoutingTraceTestCase, TestCase::Duration::QUICK);
    }
};

static IntraServerRoutingTestSuite g_intraServerRoutingTestSuite;

} // namespace
