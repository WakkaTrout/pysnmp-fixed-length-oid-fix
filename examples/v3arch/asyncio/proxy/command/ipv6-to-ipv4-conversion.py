"""
IPv6-to-IPv4 conversion
+++++++++++++++++++++++

Act as a local SNMPv1/v2c Agent listening on a UDP/IPv6 transport, relay
messages to distant SNMPv1/2c Agent over UDP/IPv4 transport:

* with local SNMPv2c community 'public'
* local Agent listening at [::1]:161
* remote SNMPv2c community 'public'
* remote Agent listening at 127.0.0.1:161

This script can be queried with the following Net-SNMP command:

| $ snmpget -v2c -c public udp6:[::1]:161 sysDescr.0

due to proxy, it is equivalent to

| $ snmpget -v2c -c public 127.0.0.1:161 sysDescr.0

Warning: for production operation you would need to modify this script
so that it will re-map possible duplicate request-ID values, coming in
initial request PDUs from different Managers, into unique values to
avoid sending duplicate request-IDs to Agents.

"""  #
from pysnmp.carrier.asyncio.dgram import udp, udp6
from pysnmp.entity import engine, config
from pysnmp.entity.rfc3413 import cmdrsp, cmdgen, context
from pysnmp.proto.api import v2c
from pysnmp import error

# Create SNMP engine with autogenernated engineID and pre-bound
# to socket transport dispatcher
snmpEngine = engine.SnmpEngine()

#
# Transport setup
#

# Agent section

# UDP over IPv6
config.add_transport(
    snmpEngine, udp6.DOMAIN_NAME, udp6.Udp6Transport().open_server_mode(("::1", 161))
)

# Manager section

# UDP over IPv4
config.add_transport(snmpEngine, udp.DOMAIN_NAME, udp.UdpTransport().open_client_mode())

#
# SNMPv1/2c setup (Agent role)
#

# SecurityName <-> CommunityName mapping
config.add_v1_system(snmpEngine, "1-my-area", "public")

#
# SNMPv1/v2c setup (Manager role)
#
# Here we configure securityName lexicographically lesser than '1-my-area'
# to let it match first in snmpCommunityTable on response processing.
#

config.add_v1_system(snmpEngine, "0-distant-area", "public", transportTag="remote")

#
# Transport target used by Manager
#

config.add_target_parameters(
    snmpEngine, "distant-agent-auth", "0-distant-area", "noAuthNoPriv", 1
)
config.add_target_address(
    snmpEngine,
    "distant-agent",
    udp.DOMAIN_NAME,
    ("127.0.0.1", 161),
    "distant-agent-auth",
    retryCount=0,
    tagList="remote",
)

# Default SNMP context
config.add_context(snmpEngine, "")


class CommandResponder(cmdrsp.CommandResponderBase):
    cmdGenMap = {
        v2c.GetRequestPDU.tagSet: cmdgen.GetCommandGenerator(),
        v2c.SetRequestPDU.tagSet: cmdgen.SetCommandGenerator(),
        v2c.GetNextRequestPDU.tagSet: cmdgen.NextCommandGeneratorSingleRun(),
        v2c.GetBulkRequestPDU.tagSet: cmdgen.BulkCommandGeneratorSingleRun(),
    }
    SUPPORTED_PDU_TYPES = cmdGenMap.keys()  # This app will handle these PDUs

    # SNMP request relay
    def handle_management_operation(
        self, snmpEngine, stateReference, contextName, PDU, acInfo
    ):
        cbCtx = stateReference, PDU
        contextEngineId = None  # address authoritative SNMP Engine
        try:
            self.cmdGenMap[PDU.tagSet].sendPdu(
                snmpEngine,
                "distant-agent",
                contextEngineId,
                contextName,
                PDU,
                self.handleResponsePdu,
                cbCtx,
            )
        except error.PySnmpError:
            self.handleResponsePdu(snmpEngine, stateReference, "error", None, cbCtx)

    # SNMP response relay
    # noinspection PyUnusedLocal
    def handleResponsePdu(
        self, snmpEngine, sendRequestHandle, errorIndication, PDU, cbCtx
    ):
        stateReference, reqPDU = cbCtx

        if errorIndication:
            PDU = v2c.apiPDU.get_response(reqPDU)
            PDU.set_error_status(PDU, 5)

        self.send_pdu(snmpEngine, stateReference, PDU)

        self.release_state_information(stateReference)


CommandResponder(snmpEngine, context.SnmpContext(snmpEngine))

snmpEngine.transport_dispatcher.job_started(1)  # this job would never finish

# Run I/O dispatcher which would receive queries and send responses
try:
    snmpEngine.open_dispatcher()
except:
    snmpEngine.close_dispatcher()
    raise
