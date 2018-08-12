#
# This file is part of pysnmp software.
#
# Copyright (c) 2005-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysnmp/license.html
#
import os
import shutil
import sys
import tempfile
from typing import Any, Dict

from pyasn1.compat.octets import str2octs


from pysnmp import debug, error
from pysnmp.carrier.base import AbstractTransportAddress, AbstractTransportDispatcher
from pysnmp.entity import observer
from pysnmp.proto.acmod import rfc3415, void
from pysnmp.proto.mpmod.rfc2576 import (
    SnmpV1MessageProcessingModel,
    SnmpV2cMessageProcessingModel,
)
from pysnmp.proto.mpmod.rfc3412 import SnmpV3MessageProcessingModel
from pysnmp.proto.rfc1902 import OctetString
from pysnmp.proto.rfc3412 import MsgAndPduDispatcher
from pysnmp.proto.secmod.rfc2576 import SnmpV1SecurityModel, SnmpV2cSecurityModel
from pysnmp.proto.secmod.rfc3414 import SnmpUSMSecurityModel

__all__ = ["SnmpEngine"]


class SnmpEngine:
    """Creates SNMP engine object.

    SNMP engine object is central in SNMP v3 architecture. It is an umbrella
    object that coordinates interactions between all parts of SNMP v3 system.
    See :RFC:`3412#section-2.1` (where it is termed *The Dispatcher*).

    With PySNMP design, `SnmpEngine` is the only stateful object, all SNMP
    v3 operations require an instance of SNMP engine. Users do not normally
    request services directly from `SnmpEngine`, but pass it around to
    other PySNMP interfaces.

    It is possible to run multiple instances of `SnmpEngine` in the
    application. In a multithreaded environment, each thread that
    works with SNMP must have its own `SnmpEngine` instance.

    Parameters
    ----------
    snmpEngineID : :py:class:`~pysnmp.proto.rfc1902.OctetString`
        Unique and unambiguous identifier of an SNMP engine.
        If not given, `snmpEngineID` is autogenerated and stored on
        the filesystem. See :RFC:`3411#section-3.1.1`  for details.

    Examples
    --------
    >>> SnmpEngine()
    SnmpEngine(snmpEngineID=OctetString(hexValue='0x80004fb80567726f6d6d69742'))
    >>>

    """

    transportDispatcher: "AbstractTransportDispatcher | None"
    msgAndPduDsp: MsgAndPduDispatcher
    snmpEngineId: OctetString
    cache: Dict[str, Any]

    def __init__(
        self,
        snmpEngineID: "OctetString | None" = None,
        maxMessageSize: int = 65507,
        msgAndPduDsp: "MsgAndPduDispatcher | None" = None,
    ):
        self.cache = {}

        self.observer = observer.MetaObserver()

        if msgAndPduDsp is None:
            self.msgAndPduDsp = MsgAndPduDispatcher()
        else:
            self.msgAndPduDsp = msgAndPduDsp
        self.messageProcessingSubsystems = {
            SnmpV1MessageProcessingModel.MESSAGE_PROCESSING_MODEL_ID: SnmpV1MessageProcessingModel(),
            SnmpV2cMessageProcessingModel.MESSAGE_PROCESSING_MODEL_ID: SnmpV2cMessageProcessingModel(),
            SnmpV3MessageProcessingModel.MESSAGE_PROCESSING_MODEL_ID: SnmpV3MessageProcessingModel(),
        }
        self.securityModels = {
            SnmpV1SecurityModel.SECURITY_MODEL_ID: SnmpV1SecurityModel(),
            SnmpV2cSecurityModel.SECURITY_MODEL_ID: SnmpV2cSecurityModel(),
            SnmpUSMSecurityModel.SECURITY_MODEL_ID: SnmpUSMSecurityModel(),
        }
        self.accessControlModel = {
            void.Vacm.ACCESS_MODEL_ID: void.Vacm(),
            rfc3415.Vacm.ACCESS_MODEL_ID: rfc3415.Vacm(),
        }

        self.transportDispatcher = None

        if self.msgAndPduDsp.mibInstrumController is None:
            raise error.PySnmpError("MIB instrumentation does not yet exist")
        (
            snmpEngineMaxMessageSize,
        ) = self.msgAndPduDsp.mibInstrumController.mibBuilder.importSymbols(  # type: ignore
            "__SNMP-FRAMEWORK-MIB", "snmpEngineMaxMessageSize"
        )
        snmpEngineMaxMessageSize.syntax = snmpEngineMaxMessageSize.syntax.clone(
            maxMessageSize
        )
        (
            snmpEngineBoots,
        ) = self.msgAndPduDsp.mibInstrumController.mibBuilder.importSymbols(  # type: ignore
            "__SNMP-FRAMEWORK-MIB", "snmpEngineBoots"
        )
        snmpEngineBoots.syntax += 1
        (
            origSnmpEngineID,
        ) = self.msgAndPduDsp.mibInstrumController.mibBuilder.importSymbols(  # type: ignore
            "__SNMP-FRAMEWORK-MIB", "snmpEngineID"
        )

        if snmpEngineID is None:
            self.snmpEngineID = origSnmpEngineID.syntax
        else:
            origSnmpEngineID.syntax = origSnmpEngineID.syntax.clone(snmpEngineID)
            self.snmpEngineID = origSnmpEngineID.syntax

            debug.logger & debug.FLAG_APP and debug.logger(
                "SnmpEngine: using custom SNMP Engine ID: %s"
                % self.snmpEngineID.prettyPrint()
            )

            # Attempt to make some of snmp Engine settings persistent.
            # This should probably be generalized as a non-volatile MIB store.

            persistentPath = os.path.join(
                tempfile.gettempdir(), "__pysnmp", self.snmpEngineID.prettyPrint()
            )

            debug.logger & debug.FLAG_APP and debug.logger(
                "SnmpEngine: using persistent directory: %s" % persistentPath
            )

            if not os.path.exists(persistentPath):
                try:
                    os.makedirs(persistentPath)
                except OSError:
                    return

            f = os.path.join(persistentPath, "boots")
            try:
                snmpEngineBoots.syntax = snmpEngineBoots.syntax.clone(open(f).read())
            except Exception:
                pass

            try:
                snmpEngineBoots.syntax += 1
            except Exception:
                snmpEngineBoots.syntax = snmpEngineBoots.syntax.clone(1)

            try:
                fd, fn = tempfile.mkstemp(dir=persistentPath)
                os.write(fd, str2octs(snmpEngineBoots.syntax.prettyPrint()))
                os.close(fd)
                shutil.move(fn, f)
            except Exception:
                debug.logger & debug.FLAG_APP and debug.logger(
                    "SnmpEngine: could not stored SNMP Engine Boots: %s"
                    % sys.exc_info()[1]
                )
            else:
                debug.logger & debug.FLAG_APP and debug.logger(
                    "SnmpEngine: stored SNMP Engine Boots: %s"
                    % snmpEngineBoots.syntax.prettyPrint()
                )

    def __repr__(self):
        return f"{self.__class__.__name__}(snmpEngineID={self.snmpEngineID!r})"

    def openDispatcher(self, timeout: float = 0):
        """
        Open the dispatcher used by SNMP engine.

        This method is called when SNMP engine is ready to process SNMP
        messages. It opens the dispatcher and starts processing incoming
        messages.
        """
        if self.transportDispatcher:
            self.transportDispatcher.runDispatcher(timeout)

    def closeDispatcher(self):
        """
        Close the dispatcher used by SNMP engine.

        This method is called when SNMP engine is no longer needed. It
        releases all resources allocated by the engine.
        """
        if self.transportDispatcher:
            self.transportDispatcher.closeDispatcher()
            self.unregisterTransportDispatcher()

    # Transport dispatcher bindings

    def __receiveMessageCbFun(
        self,
        transportDispatcher: AbstractTransportDispatcher,
        transportDomain: "tuple[int, ...]",
        transportAddress: AbstractTransportAddress,
        wholeMsg,
    ):
        self.msgAndPduDsp.receiveMessage(
            self, transportDomain, transportAddress, wholeMsg
        )

    def __receiveTimerTickCbFun(self, timeNow: float):
        self.msgAndPduDsp.receiveTimerTick(self, timeNow)
        for mpHandler in self.messageProcessingSubsystems.values():
            mpHandler.receiveTimerTick(self, timeNow)
        for smHandler in self.securityModels.values():
            smHandler.receiveTimerTick(self, timeNow)

    def registerTransportDispatcher(
        self,
        transportDispatcher: AbstractTransportDispatcher,
        recvId: "tuple[int, ...] | None" = None,
    ):
        if (
            self.transportDispatcher is not None
            and self.transportDispatcher is not transportDispatcher
        ):
            raise error.PySnmpError("Transport dispatcher already registered")
        transportDispatcher.registerRecvCbFun(self.__receiveMessageCbFun, recvId)
        if self.transportDispatcher is None:
            transportDispatcher.registerTimerCbFun(self.__receiveTimerTickCbFun)
            self.transportDispatcher = transportDispatcher

    def unregisterTransportDispatcher(self, recvId: "tuple[int, ...] | None" = None):
        if self.transportDispatcher is None:
            raise error.PySnmpError("Transport dispatcher not registered")
        self.transportDispatcher.unregisterRecvCbFun(recvId)
        self.transportDispatcher.unregisterTimerCbFun()
        self.transportDispatcher = None

    def getMibBuilder(self):
        return self.msgAndPduDsp.mibInstrumController.mibBuilder

    # User app may attach opaque objects to SNMP Engine
    def setUserContext(self, **kwargs):
        self.cache.update({"__%s" % k: kwargs[k] for k in kwargs})

    def getUserContext(self, arg) -> "dict[str, Any] | None":
        return self.cache.get("__%s" % arg)

    def delUserContext(self, arg):
        try:
            del self.cache["__%s" % arg]
        except KeyError:
            pass
