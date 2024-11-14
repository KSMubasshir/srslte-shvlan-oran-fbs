#!/usr/bin/env python
import geni.portal as portal
import geni.rspec.pg as rspec
import geni.rspec.igext as IG
import geni.rspec.emulab.pnext as PN
import geni.rspec.emulab.emuext
import geni.urn as URN
import hashlib
import os
import socket
import struct

tourDescription = """

## srsLTE Controlled/Indoor RF with O-RAN support

---

IMPORTANT: DO NOT start this expirment until you have first instantiated a
companion O-RAN experiment via the following profile:

  https://www.powderwireless.net/p/PowderProfiles/O-RAN

Furthermore, DO NOT start the srsLTE services in that experiment as
directed.  See the instructions in this profile for more information.

---

Use this profile to instantiate an end-to-end srsLTE network in a controlled RF
environment (wired connections between UE and eNB).

The following resources will be allocated:

  * Intel NUC5300/B210 w/ srsLTE UE(s) 
    * 1 or 2, depending on "Number of UEs" parameter: `rue1`, `rue2`
  * Intel NUC5300/B210 w/ srsLTE eNB/EPC (`enb1`)

"""

tourInstructions = """

### Prerequisites: O-RAN Setup

You should have already started up an O-RAN experiment connected to
the same shared VLAN you specified during the "parameterize" step.
Make sure it is up and fully deployed first - see the instructions
included in that profile.  However, DO NOT start the srsLTE components
or `kpimon` xApp as directed in those instructions.

Make note of the `e2term-sctp` service's IP address in the O-RAN
experiment.  To do that, open an SSH session to `node-0` in that
experiment and run:

```
# Extract `e2term-sctp` IP address
kubectl get svc -n ricplt --field-selector metadata.name=service-ricplt-e2term-sctp-alpha -o jsonpath='{.items[0].spec.clusterIP}'
```

You will need this address when starting the srsLTE eNodeB service.

### Start EPC and eNB

Login to `enb1` via `ssh` and start the srsLTE EPC services:

```
# start srsepc
sudo srsepc
```

Then in another SSH session on `enb1`, start the eNB service.
Substitute the IP address (or set it as an environment variable) in
this command for the one captured for the `e2term-sctp` O-RAN service
in the previous step.

```
# start srsenb (with agent connectivity to O-RAN RIC)
sudo srsenb --ric.agent.remote_ipv4_addr=${E2TERM_IP} --log.all_level=warn --ric.agent.log_level=debug --log.filename=stdout
```

There will be output in srsenb and the O-RAN e2term mgmt and other
service logs showing that the enb has connected to the O-RAN RIC.

### Start the `kpimon` xApp

Go back to the instructions in the O-RAN profile and follow the steps
for starting the `kpimon` xApp (start with step 3 under "Running the
O-RAN/srsLTE scp-kpimon demo").

You should start seeing `srsenb` send periodic reports once the
`kpimon` xApp starts.  These will appear in the `kpimon` xApp log
output as well in the srsenb output.

### Start the srsLTE UE

SSH to `rue1` and run:

```
sudo srsue
```

You should see changes in the `kpimon` output when `srsue` is
connected.  Try pinging `172.16.0.1` (the srs SPGW gateway address)
from the UE and watch the `kpimon` counters tick.

"""

class GLOBALS(object):
    NUC_HWTYPE = "nuc5300"
    UBUNTU_1804_IMG = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU18-64-STD"
    UBUNTU_2204_IMG = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-STD"
    SRSLTE_IMG = "urn:publicid:IDN+emulab.net+image+PowderTeam:U18LL-SRSLTE"
    UBUNTU_2204_GR_IMG = "urn:publicid:IDN+emulab.net+image+emulab-ops//UBUNTU22-64-GR310"
    POWDER_CM_ID = "urn:publicid:IDN+emulab.net+authority+cm"

pc = portal.Context()

pc.defineParameterGroup("indoorOTA", "Indoor OTA Resources")
pc.defineParameterGroup("controlledRF", "Controlled RF Resources")

indoorOtaX310s = [
    ("ota-x310-%d" % (i,), "Indoor OTA X310 #%d" % (i,)) for i in range(1, 5) ]
indoorOtaNucs = [
    ("ota-nuc%d" % (i,), "Indoor OTA nuc#%d with B210" % (i,)) for i in range(1, 5) ]
anyIndoorRadios = [ ("", "") ]
anyIndoorRadios.extend(indoorOtaX310s)
anyIndoorRadios.extend(indoorOtaNucs)

pc.defineStructParameter(
    "indoorX310s", "Indoor OTA X310 with Server",
    [], multiValue=True, itemDefaultValue={}, min=0, max=None,
    members=[
        portal.Parameter(
            "fixedNodeId", "Indoor OTA X310", portal.ParameterType.STRING,
            indoorOtaX310s[0], indoorOtaX310s),
        portal.Parameter(
            "nodeType", "Compute Node Type", portal.ParameterType.STRING,
            "d430", [("d740", "POWDER, d740"), ("d430", "Emulab d430")]),
        portal.Parameter(
            "diskImage", "Compute Node Disk Image", portal.ParameterType.STRING,
            GLOBALS.UBUNTU_2204_GR_IMG),
        portal.Parameter(
            "role", "Role", portal.ParameterType.STRING,
            "NodeB", [("NodeB", "NodeB"), ("UE", "UE")]),
        portal.Parameter(
            "bindToNodeB", "Bind UE to NodeB", portal.ParameterType.STRING,
            "", anyIndoorRadios,
            longDescription="If this is a UE, add its IMSI only to the EPC of the selected NodeB.  Leave empty to map the IMSI to any of the NodeBs you are allocating."),
        portal.Parameter(
            "sharedVlanAddress", "Shared VLAN IP Address",
            portal.ParameterType.STRING, "",
            longDescription="Set the IP address for the shared VLAN interface.  Make sure you choose an unused address within the subnet of an existing shared vlan."),
        portal.Parameter(
            "dlFreq", "DL Frequency",
            portal.ParameterType.STRING, "",
            longDescription="Set the DL Frequency (e.g. 3435e6)."),
        portal.Parameter(
            "ulFreq", "UL Frequency",
            portal.ParameterType.STRING, "",
            longDescription="Set the UL Frequency (e.g. 3410e6)."),
        portal.Parameter(
            "prbs", "Number PRBs (if NodeB)",
            portal.ParameterType.INTEGER, 25,
            [(6, "1.4MHz"), (15, "3MHz"), (25, "5MHz"), (50, "10MHz"), (75, "15MHz"), (100, "20MHz")],
            longDescription="Set the bandwidth in PRBs."),
        portal.Parameter(
            "dlMask", "DL RBG Mask (if NodeB)",
            portal.ParameterType.STRING, "",
            longDescription="Set the DL RBG mask as a bit string.  Do not set this unless you know what you are doing."),
        portal.Parameter(
            "ulMask", "UL PRB Mask (if NodeB)",
            portal.ParameterType.STRING, "",
            longDescription="Set the UL PRB mask as a bit string.  For instance, if you are operating at 25 PRB (5MHz) and have two NodeBs sharing one uplink band, you could give one a mask of 0x001fff, and the other 0xfffe000.  This would partition each NodeB into 12 PRBs on either side of the band, leaving 1 PRB unused in the middle as a guard.")
    ],
    groupId="indoorOTA")
pc.defineStructParameter(
    "indoorB210s", "Indoor OTA Nuc with B210",
    [], multiValue=True, min=0, max=None,
    members=[
        portal.Parameter(
            "fixedNodeId", "Indoor OTA Nuc", portal.ParameterType.STRING,
            indoorOtaNucs[0], indoorOtaNucs),
        portal.Parameter(
            "diskImage", "Disk Image", portal.ParameterType.STRING,
            GLOBALS.UBUNTU_2204_GR_IMG),
        portal.Parameter(
            "role", "Role", portal.ParameterType.STRING,
            "NodeB", [("NodeB", "NodeB"), ("UE", "UE")]),
        portal.Parameter(
            "bindToNodeB", "Bind UE to NodeB", portal.ParameterType.STRING,
            "", anyIndoorRadios,
            longDescription="If this is a UE, add its IMSI only to the EPC of the selected NodeB.  Leave empty to map the IMSI to any of the NodeBs you are allocating."),
        portal.Parameter(
            "sharedVlanAddress", "Shared VLAN IP Address",
            portal.ParameterType.STRING, "",
            longDescription="Set the IP address for the shared VLAN interface.  Make sure you choose an unused address within the subnet of an existing shared vlan."),
        portal.Parameter(
            "dlFreq", "DL Frequency",
            portal.ParameterType.STRING, "",
            longDescription="Set the DL Frequency (e.g. 3435e6)."),
        portal.Parameter(
            "ulFreq", "UL Frequency",
            portal.ParameterType.STRING, "",
            longDescription="Set the UL Frequency (e.g. 3410e6)."),
        portal.Parameter(
            "prbs", "Number PRBs (if NodeB)",
            portal.ParameterType.INTEGER, 25,
            [(6, "1.4MHz"), (15, "3MHz"), (25, "5MHz"), (50, "10MHz"), (75, "15MHz"), (100, "20MHz")],
            longDescription="Set the bandwidth in PRBs."),
        portal.Parameter(
            "dlMask", "DL RBG Mask (if NodeB)",
            portal.ParameterType.STRING, "",
            longDescription="Set the DL RBG mask as a bit string.  Do not set this unless you know what you are doing."),
        portal.Parameter(
            "ulMask", "UL PRB Mask (if NodeB)",
            portal.ParameterType.STRING, "",
            longDescription="Set the UL PRB mask as a bit string.  For instance, if you are operating at 25 PRB (5MHz) and have two NodeBs sharing one uplink band, you could give one a mask of 0x001fff, and the other 0xfffe000.  This would partition each NodeB into 12 PRBs on either side of the band, leaving 1 PRB unused in the middle as a guard.")
    ],
    groupId="indoorOTA")

pc.defineParameter(
    "matrixUeCount", "Number of Controlled RF B210 UEs",
    portal.ParameterType.INTEGER, 0, [0, 1, 2, 3],
    longDescription="The number of controlled RF B210s you want to act as UEs.  If 0, no resources in the controlled RF environment will be allocated.",
    groupId="controlledRF")
pc.defineParameter(
    "matrixNodeBFixedNode", "Fixed Controlled RF B210 NodeB Node ID",
    portal.ParameterType.STRING, "",
    longDescription="Specific eNodeB node to allocate.  If unset and you have requested 1 or more Controlled RF B210 UEs, one will be chosen for you.",
    groupId="controlledRF")
pc.defineParameter(
    "matrixDiskImage", "Controlled RF Disk Image", portal.ParameterType.STRING,
    GLOBALS.UBUNTU_2204_GR_IMG)
pc.defineParameter(
    "matrixSharedVlanAddress", "Shared VLAN IP Address",
    portal.ParameterType.STRING, "",
    longDescription="Set the IP address for the shared VLAN interface.  Make sure you choose an unused address within the subnet of an existing shared vlan.")

pc.defineParameter(
    "oranAddress", "O-RAN Services Gateway Address",
    portal.ParameterType.STRING, "10.254.254.1",
    longDescription="The IP address of the O-RAN services gateway running on an adjacent experiment connected to the same shared VLAN.")
pc.defineParameter(
    "oranVirtualSubnets", "O-RAN Kubernetes Subnets to route via Gateway",
    portal.ParameterType.STRING, "10.96.0.0/12",
    longDescription="A space-separated list of subnets in CIDR format to route via the O-RAN Services Gateway Address.")
pc.defineParameter(
    "sharedVlanName","Shared VLAN Name",
    portal.ParameterType.STRING,"",
    longDescription="Connect NodeB nodes to a shared VLAN.  This allows your srsLTE base stations to connect to another experiment (e.g., one running O-RAN services). The shared VLAN must already exist.")
pc.defineParameter(
    "sharedVlanNetmask","Shared VLAN IP Netmask",
    portal.ParameterType.STRING,"255.255.255.0",
    longDescription="Set the subnet mask for the shared VLAN interface.")
pc.defineParameter(
    "multiplexLans", "Multiplex Networks",
    portal.ParameterType.BOOLEAN,True,
    longDescription="Multiplex any networks over physical interfaces using VLANs.  Some physical machines have only a single experiment network interface, so if you want multiple links/LANs, you have to enable multiplexing.  Currently, if you select this option.")
pc.defineParameter(
    "installVNC", "Install VNC on Compute Nodes",
    portal.ParameterType.BOOLEAN, True,
    longDescription="Install VNC on the SDR compute nodes.  This is useful if you are participating in a tutorial, demo; want to visualize SDR metrics and signals; or simply do not want to open several SSH connections in separate terminals on your desktop or in the web UI.")

params = pc.bindParameters()

pc.verifyParameters()
request = pc.makeRequestRSpec()

if params.installVNC:
    request.initVNC()

ueIndex = 0
nbIndex = 0
randint = int(hashlib.sha256(os.urandom(128)).hexdigest()[:8],base=16) % 1000000

# ue1,xor,001010123456789,00112233445566778899aabbccddeeff,opc,63bfa50ee6523365ff14c1f45f88737d,9001,000000001297,7,192.168.0.2
def makeUeTuple(idx):
    return (str(idx),
            "001010{:06d}{:03d}".format(randint, idx),
            "353490{:06d}{:03d}".format(randint, idx),
            "192.168.0.%d" % (idx + 10))

def next_ipv4_addr(base_addr_str, mask_str, offset):
    bai = struct.unpack(">i",socket.inet_aton(base_addr_str))[0]
    mi = struct.unpack(">i",socket.inet_aton(mask_str))[0]
    ni = bai + offset
    if bai & mi != ni & mi:
        raise Exception("insufficient space in netmask %s to increment %s + %d" % (
            mask_str, base_addr_str, offset))
    return socket.inet_ntoa(struct.pack(">i",ni))

def connect_shared_vlan(node, vlan_name, addr, mask):
    shiface = node.addInterface("ifSharedVlan")
    if addr:
        shiface.addAddress(rspec.IPv4Address(addr, mask))
    sharedvlan = request.Link(node.name + '-shvlan')
    sharedvlan.addInterface(shiface)
    sharedvlan.connectSharedVlan(vlan_name)
    if params.multiplexLans:
        sharedvlan.link_multiplexing = True
        sharedvlan.best_effort = True

def add_ue_services(ue, ueTuple, radioKind, ueParams):
    ue.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-cpu.sh"))
    ue.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-%s.sh" % (radioKind,)))
    ue.addService(rspec.Execute(shell="bash", command="/local/repository/bin/setup-srslte.sh"))
    envstr = ""
    if ueParams:
        if ueParams.dlFreq:
            envstr += " DL_FREQ=" + ueParams.dlFreq
        if ueParams.ulFreq:
            envstr += " UL_FREQ=" + ueParams.ulFreq
    ue.addService(rspec.Execute(shell="bash", command="" + envstr + " /local/repository/bin/update-ue-config-files.sh '%s,%s'" % (ueTuple[1],ueTuple[2])))
    if params.installVNC:
        ue.startVNC()

def add_nb_services(nb, nbIdx, ueTuples, radioKind, nbParams):
    nb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-cpu.sh"))
    nb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/tune-%s.sh" % (radioKind,)))
    nb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/setup-ip-config.sh %s '%s'" % (params.oranAddress,params.oranVirtualSubnets)))
    nb.addService(rspec.Execute(shell="bash", command="/local/repository/bin/setup-srslte.sh"))
    enb_update_args = ["'%s,%s,%s,%s'" % (x[0],x[1],x[2],x[3]) for x in ueTuples]
    envstr = ""
    if nbParams:
        if nbParams.dlFreq:
            envstr += " DL_FREQ=" + nbParams.dlFreq
        if nbParams.ulFreq:
            envstr += " UL_FREQ=" + nbParams.ulFreq
        if nbParams.prbs:
            envstr += " PRBS=" + str(nbParams.prbs)
        if nbParams.dlMask:
            envstr += " DL_MASK=" + nbParams.dlMask
        if nbParams.ulMask:
            envstr += " UL_MASK=" + nbParams.ulMask
    nb.addService(rspec.Execute(shell="bash", command="" + envstr + " /local/repository/bin/update-enb-config-files.sh " + "'0x{:03x}'".format(nbIdx) + " " + " ".join(enb_update_args)))
    if params.installVNC:
        nb.startVNC()


nbs = dict()
ueTuplesByNodeB = {"":[]}

for x in params.indoorX310s:
    if x.role == "UE":
        ueIndex += 1
    else:
        nbIndex += 1
    node = request.RawPC("{}-comp".format(x.fixedNodeId))
    node.hardware_type = x.nodeType
    node.disk_image = x.diskImage
    node.component_manager_id = GLOBALS.POWDER_CM_ID
    node_radio_if = node.addInterface(node.name + "-usrp-if")
    node_radio_if.addAddress(
        rspec.IPv4Address("192.168.40.1", "255.255.255.0"))
    radio_link = request.Link(node.name + "-radio-link")
    radio_link.bandwidth = 10*1000*1000
    radio_link.addInterface(node_radio_if)
    radio = request.RawPC(x.fixedNodeId)
    radio.component_id = x.fixedNodeId
    radio.component_manager_id = GLOBALS.POWDER_CM_ID
    radio_link.addNode(radio)

    if x.role == "NodeB":
        nbs[x.fixedNodeId] = (node, nbIndex, "x310", x)
        if params.sharedVlanName:
            sva = x.sharedVlanAddress
            if not sva:
                sva = next_ipv4_addr(params.oranAddress, params.sharedVlanNetmask, nbIndex)
            connect_shared_vlan(node, params.sharedVlanName, sva, params.sharedVlanNetmask)
    elif x.role == "UE":
        ueTuple = makeUeTuple(ueIndex)
        if x.bindToNodeB not in ueTuplesByNodeB:
            ueTuplesByNodeB[x.bindToNodeB] = []
        ueTuplesByNodeB[x.bindToNodeB].append(ueTuple)
        add_ue_services(node, ueTuple, "x310", x)

for x in params.indoorB210s:
    if x.role == "UE":
        ueIndex += 1
    else:
        nbIndex += 1
    node = request.RawPC(x.fixedNodeId)
    node.disk_image = x.diskImage
    node.component_manager_id = GLOBALS.POWDER_CM_ID
    node.component_id = x.fixedNodeId

    if x.role == "NodeB":
        nbs[x.fixedNodeId] = (node, nbIndex, "b210", x)
        if params.sharedVlanName:
            sva = x.sharedVlanAddress
            if not sva:
                sva = next_ipv4_addr(params.oranAddress, params.sharedVlanNetmask, nbIndex)
            connect_shared_vlan(node, params.sharedVlanName, sva, params.sharedVlanNetmask)
    elif x.role == "UE":
        ueTuple = makeUeTuple(ueIndex)
        if x.bindToNodeB not in ueTuplesByNodeB:
            ueTuplesByNodeB[x.bindToNodeB] = []
        ueTuplesByNodeB[x.bindToNodeB].append(ueTuple)
        add_ue_services(node, ueTuple, "b210", x)

for (name,nodeDetails) in nbs.items():
    (node, localNbIndex, radioKind, nbParams) = nodeDetails
    t = list(ueTuplesByNodeB[""])
    t.extend(ueTuplesByNodeB.get(name,[]))
    add_nb_services(node, localNbIndex, t, radioKind, nbParams)

if params.matrixUeCount > 0:
    # Add a NUC eNB node
    nbIndex += 1
    nb = request.RawPC("m-nb-%d" % (nbIndex,))
    nb.component_manager_id = GLOBALS.POWDER_CM_ID
    if params.matrixNodeBFixedNode:
        nb.component_id = params.matrixNodeBFixedNode
    nb.hardware_type = GLOBALS.NUC_HWTYPE
    nb.disk_image = params.matrixDiskImage
    nb.Desire("rf-controlled", 1)

    # Connect nb to shared vlan, if requested.
    if params.sharedVlanName:
        sva = params.matrixSharedVlanAddress
        if not sva:
            sva = next_ipv4_addr(params.oranAddress, params.sharedVlanNetmask, nbIndex)
        connect_shared_vlan(nb, params.sharedVlanName, sva, params.sharedVlanNetmask)

    # Add a srsLTE SDR-based UE nodes
    ueTuples = []
    for i in range(1, params.matrixUeCount + 1):
        ueIndex += 1
        ue = request.RawPC("m-ue-%d" % (ueIndex,))
        ue.component_manager_id = GLOBALS.POWDER_CM_ID
        ue.hardware_type = GLOBALS.NUC_HWTYPE
        ue.disk_image = params.matrixDiskImage
        ue.Desire("rf-controlled", 1)
        # Create the RF link between the UE and eNodeB
        rflink = request.RFLink("rflink-%d" % i)
        ue_nb_rf = ue.addInterface("m-nb1-rf")
        nb_ue_rf = nb.addInterface("m-ue%d-rf" % i)
        rflink.addInterface(nb_ue_rf)
        rflink.addInterface(ue_nb_rf)
        ueTuple = makeUeTuple(ueIndex)
        ueTuples.append(ueTuple)
        add_ue_services(ue, ueTuple, "b210", None)

    add_nb_services(nb, nbIndex, ueTuples, "b210", None)

tour = IG.Tour()
tour.Description(IG.Tour.MARKDOWN, tourDescription)
tour.Instructions(IG.Tour.MARKDOWN, tourInstructions)
request.addTour(tour)

pc.printRequestRSpec(request)
