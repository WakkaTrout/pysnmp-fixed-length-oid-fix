import asyncio
import pytest


from pysnmp.hlapi.v3arch.asyncio import *
import tests.manager_context


@pytest.mark.asyncio
async def test_send_v3_trap_notification():
    async with tests.manager_context.ManagerContextManager():
        # snmptrap -v3 -l authPriv -u usr-md5-des -A authkey1 -X privkey1 -e 8000000001020304 localhost:MANAGER_PORT 0 1.3.6.1.6.3.1.1.5.1 1.3.6.1.2.1.1.1.0 s "my system"
        snmpEngine = SnmpEngine(OctetString(hexValue="8000000001020304"))
        errorIndication, errorStatus, errorIndex, varBinds = await sendNotification(
            snmpEngine,
            UsmUserData("usr-md5-des", "authkey1", "privkey1"),
            await UdpTransportTarget.create(
                ("localhost", tests.manager_context.MANAGER_PORT)
            ),
            ContextData(),
            "trap",
            NotificationType(ObjectIdentity("IF-MIB", "linkDown")),
        )

        snmpEngine.closeDispatcher()
        await asyncio.sleep(1)
        assert tests.manager_context.message_count == 1
