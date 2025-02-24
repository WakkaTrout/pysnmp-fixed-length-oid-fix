"""
Agent operations on MIB
+++++++++++++++++++++++

This script explains how SNMP Agent application manipulates
its MIB possibly triggered by SNMP Manager's commands.

"""  #
# SNMP agent backend e.g. Agent access to Managed Objects
from pysnmp.smi import builder, instrum, exval

print("Loading MIB modules..."),
mibBuilder = builder.MibBuilder().load_modules(
    "SNMPv2-MIB", "SNMP-FRAMEWORK-MIB", "SNMP-COMMUNITY-MIB"
)
print("done")

print("Building MIB tree..."),
mibInstrum = instrum.MibInstrumController(mibBuilder)
print("done")

print("Building table entry index from human-friendly representation..."),
(snmpCommunityEntry,) = mibBuilder.import_symbols(
    "SNMP-COMMUNITY-MIB", "snmpCommunityEntry"
)
instanceId = snmpCommunityEntry.getInstIdFromIndices("my-router")
print("done")

print("Create/update SNMP-COMMUNITY-MIB::snmpCommunityEntry table row: ")
varBinds = mibInstrum.write_variables(
    (snmpCommunityEntry.name + (2,) + instanceId, "mycomm"),
    (snmpCommunityEntry.name + (3,) + instanceId, "mynmsname"),
    (snmpCommunityEntry.name + (7,) + instanceId, "volatile"),
)
for oid, val in varBinds:
    print(
        "{} = {}".format(
            ".".join([str(x) for x in oid]),
            not val.isValue and "N/A" or val.prettyPrint(),
        )
    )
print("done")

print("Read whole MIB (table walk)")
varBinds = [((), None)]
while True:
    varBinds = mibInstrum.read_next_variables(*varBinds)
    oid, val = varBinds[0]
    if exval.endOfMib.isSameTypeWith(val):
        break
    print(
        "{} = {}".format(
            ".".join([str(x) for x in oid]),
            not val.isValue and "N/A" or val.prettyPrint(),
        )
    )
print("done")

print("Unloading MIB modules..."),
mibBuilder.unload_modules()
print("done")
