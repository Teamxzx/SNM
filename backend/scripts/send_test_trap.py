"""Send an RFC 3418 linkUp/linkDown trap to the local receiver."""

import argparse
import asyncio

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    Integer32,
    NotificationType,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    TimeTicks,
    UdpTransportTarget,
    send_notification,
)


async def send(host: str, port: int, community: str, event: str, if_index: int):
    trap_oid = "1.3.6.1.6.3.1.1.5.3" if event == "linkDown" else "1.3.6.1.6.3.1.1.5.4"
    snmp_engine = SnmpEngine()
    try:
        error_indication, error_status, error_index, _ = await send_notification(
            snmp_engine,
            CommunityData(community, mpModel=1),
            await UdpTransportTarget.create((host, port)),
            ContextData(),
            "trap",
            NotificationType(ObjectIdentity(trap_oid)).add_varbinds(
                ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.1.{if_index}"), Integer32(if_index)),
                ObjectType(ObjectIdentity(f"1.3.6.1.2.1.2.2.1.9.{if_index}"), TimeTicks(0)),
            ),
        )
        if error_indication or error_status:
            raise RuntimeError(f"{error_indication or error_status} at {error_index}")
        print(f"Sent {event} trap for ifIndex {if_index} to {host}:{port}")
    finally:
        snmp_engine.close_dispatcher()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=162)
    parser.add_argument("--community", default="public")
    parser.add_argument("--event", choices=("linkUp", "linkDown"), default="linkDown")
    parser.add_argument("--if-index", type=int, default=1)
    args = parser.parse_args()
    asyncio.run(send(args.host, args.port, args.community, args.event, args.if_index))
