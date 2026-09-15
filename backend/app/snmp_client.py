"""Async PySNMP v7 client used by the poller and interface-control API."""

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    Integer32,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    USM_AUTH_HMAC96_MD5,
    USM_AUTH_HMAC96_SHA,
    USM_AUTH_NONE,
    USM_PRIV_CBC56_DES,
    USM_PRIV_CFB128_AES,
    USM_PRIV_NONE,
    get_cmd,
    set_cmd,
    walk_cmd,
)


OIDS = {
    "sysDescr": "1.3.6.1.2.1.1.1.0",
    "sysName": "1.3.6.1.2.1.1.5.0",
    "sysUpTime": "1.3.6.1.2.1.1.3.0",
    "ifName": "1.3.6.1.2.1.31.1.1.1.1",
    "ifDescr": "1.3.6.1.2.1.2.2.1.2",
    "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
    "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
    "ifSpeed": "1.3.6.1.2.1.2.2.1.5",
    "ifHighSpeed": "1.3.6.1.2.1.31.1.1.1.15",
    "ifLastChange": "1.3.6.1.2.1.2.2.1.9",
    "ifHCInOctets": "1.3.6.1.2.1.31.1.1.1.6",
    "ifHCOutOctets": "1.3.6.1.2.1.31.1.1.1.10",
}


def _auth(device):
    if device["snmp_version"] == "2c":
        return CommunityData(device.get("community") or "public", mpModel=1)
    level = device.get("security_level") or "authPriv"
    auth_protocol = USM_AUTH_NONE if level == "noAuthNoPriv" else (USM_AUTH_HMAC96_MD5 if device.get("auth_protocol") == "MD5" else USM_AUTH_HMAC96_SHA)
    priv_protocol = USM_PRIV_NONE if level != "authPriv" else (USM_PRIV_CBC56_DES if device.get("priv_protocol") == "DES" else USM_PRIV_CFB128_AES)
    return UsmUserData(
        device.get("username") or "",
        authKey=device.get("auth_password"),
        privKey=device.get("priv_password"),
        authProtocol=auth_protocol,
        privProtocol=priv_protocol,
    )


async def _target(ip_address: str):
    return await UdpTransportTarget.create((ip_address, 161), timeout=2, retries=1)


def _raise_on_error(error_indication, error_status, error_index):
    if error_indication:
        raise TimeoutError(str(error_indication))
    if error_status:
        raise RuntimeError(f"{error_status.prettyPrint()} at index {error_index}")


async def get_system(device):
    engine = SnmpEngine()
    try:
        error_indication, error_status, error_index, var_binds = await get_cmd(
            engine, _auth(device), await _target(device["ip_address"]), ContextData(),
            ObjectType(ObjectIdentity(OIDS["sysName"])),
            ObjectType(ObjectIdentity(OIDS["sysDescr"])),
            ObjectType(ObjectIdentity(OIDS["sysUpTime"])),
            lookupMib=False,
        )
        _raise_on_error(error_indication, error_status, error_index)
        values = [value.prettyPrint() for _, value in var_binds]
        return {"sys_name": values[0], "sys_descr": values[1], "sys_uptime_ticks": int(values[2])}
    finally:
        engine.close_dispatcher()


async def _walk_column(engine, device, oid):
    values = {}
    iterator = walk_cmd(
        engine, _auth(device), await _target(device["ip_address"]), ContextData(),
        ObjectType(ObjectIdentity(oid)), lexicographicMode=False, lookupMib=False,
    )
    async for error_indication, error_status, error_index, var_binds in iterator:
        _raise_on_error(error_indication, error_status, error_index)
        for name, value in var_binds:
            numeric_oid = name.prettyPrint()
            if not numeric_oid.startswith(f"{oid}."):
                return values
            values[int(numeric_oid.rsplit(".", 1)[1])] = value.prettyPrint()
    return values


async def walk_interfaces(device):
    engine = SnmpEngine()
    try:
        columns = {}
        for name in ("ifName", "ifDescr", "ifAdminStatus", "ifOperStatus", "ifSpeed", "ifHighSpeed", "ifLastChange", "ifHCInOctets", "ifHCOutOctets"):
            columns[name] = await _walk_column(engine, device, OIDS[name])
        indices = sorted(set(columns["ifDescr"]) | set(columns["ifName"]))
        interfaces = []
        for index in indices:
            high_speed = int(columns["ifHighSpeed"].get(index, 0) or 0) * 1_000_000
            interfaces.append({
                "if_index": index,
                "if_name": columns["ifName"].get(index) or columns["ifDescr"].get(index) or f"if{index}",
                "if_descr": columns["ifDescr"].get(index, ""),
                "admin_status": int(columns["ifAdminStatus"].get(index, 2)),
                "oper_status": int(columns["ifOperStatus"].get(index, 2)),
                "speed_bps": high_speed or int(columns["ifSpeed"].get(index, 0)),
                "last_change_ticks": int(columns["ifLastChange"].get(index, 0)),
                "in_octets": int(columns["ifHCInOctets"].get(index, 0)),
                "out_octets": int(columns["ifHCOutOctets"].get(index, 0)),
            })
        return interfaces
    finally:
        engine.close_dispatcher()


async def set_admin_status(device, if_index: int, admin_status: int):
    engine = SnmpEngine()
    try:
        error_indication, error_status, error_index, _ = await set_cmd(
            engine, _auth(device), await _target(device["ip_address"]), ContextData(),
            ObjectType(ObjectIdentity(f"{OIDS['ifAdminStatus']}.{if_index}"), Integer32(admin_status)),
            lookupMib=False,
        )
        _raise_on_error(error_indication, error_status, error_index)
    finally:
        engine.close_dispatcher()
