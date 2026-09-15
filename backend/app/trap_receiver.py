"""SNMP v1/v2c trap receiver. Only linkUp/linkDown events are forwarded."""

import asyncio
import json
import logging
import threading

from pysnmp.carrier.asyncio.dgram import udp
from pysnmp.entity import config, engine
from pysnmp.entity.rfc3413 import ntfrcv


LOGGER = logging.getLogger(__name__)
LINK_DOWN = "1.3.6.1.6.3.1.1.5.3"
LINK_UP = "1.3.6.1.6.3.1.1.5.4"
TRAP_OID = "1.3.6.1.6.3.1.1.4.1.0"
IF_INDEX = "1.3.6.1.2.1.2.2.1.1"


class TrapReceiver:
    def __init__(self, host: str, port: int, community: str, on_event):
        self.host = host
        self.port = port
        self.community = community
        self.on_event = on_event
        self.snmp_engine = None
        self.thread = None

    def start(self):
        def run():
            try:
                worker_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(worker_loop)
                self.snmp_engine = engine.SnmpEngine()
                config.add_transport(self.snmp_engine, udp.DOMAIN_NAME, udp.UdpTransport().open_server_mode((self.host, self.port)))
                config.add_v1_system(self.snmp_engine, "monitor-area", self.community)
                ntfrcv.NotificationReceiver(self.snmp_engine, self._callback)
                self.snmp_engine.transport_dispatcher.job_started(1)
                LOGGER.info("SNMP trap receiver listening on %s:%s/udp", self.host, self.port)
                self.snmp_engine.open_dispatcher()
            except Exception as exc:
                LOGGER.warning("Trap receiver could not bind %s:%s: %s", self.host, self.port, exc)
        self.thread = threading.Thread(target=run, name="snmp-trap-receiver", daemon=True)
        self.thread.start()

    def stop(self):
        if self.snmp_engine:
            self.snmp_engine.close_dispatcher()

    def _callback(self, snmp_engine, state_reference, context_engine_id, context_name, var_binds, callback_context):
        values = {name.prettyPrint(): value.prettyPrint() for name, value in var_binds}
        trap_oid = values.get(TRAP_OID)
        if trap_oid not in (LINK_UP, LINK_DOWN):
            return
        try:
            _, source = snmp_engine.message_dispatcher.get_transport_info(state_reference)
            source_ip = source[0]
        except Exception:
            source_ip = "unknown"
        if_index = None
        for oid, value in values.items():
            if oid == IF_INDEX or oid.startswith(f"{IF_INDEX}."):
                try:
                    if_index = int(value)
                except ValueError:
                    if_index = int(oid.rsplit(".", 1)[1])
                break
        self.on_event({"source_ip": source_ip, "if_index": if_index, "event_type": "linkUp" if trap_oid == LINK_UP else "linkDown", "raw_varbinds": json.dumps(values)})
