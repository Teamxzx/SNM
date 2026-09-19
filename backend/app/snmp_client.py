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
    # LLDP-MIB (standard) and CISCO-CDP-MIB.  Both are optional on a device,
    # so a device that does not advertise either protocol simply returns no links.
    "lldpLocPortId": "1.0.8802.1.1.2.1.3.7.1.3",
    "lldpRemLocalPortNum": "1.0.8802.1.1.2.1.4.1.1.2",
    "lldpRemPortId": "1.0.8802.1.1.2.1.4.1.1.7",
    "lldpRemSysName": "1.0.8802.1.1.2.1.4.1.1.9",
    "cdpCacheIfIndex": "1.3.6.1.4.1.9.9.23.1.2.1.1.1",
    "cdpCacheDeviceId": "1.3.6.1.4.1.9.9.23.1.2.1.1.6",
    "cdpCacheDevicePort": "1.3.6.1.4.1.9.9.23.1.2.1.1.7",
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


def _text(value) -> str:
    """Decode SNMP OctetString values instead of showing their 0x hexadecimal form."""
    if hasattr(value, "asOctets"):
        raw = value.asOctets()
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1", errors="replace")
    return value.prettyPrint()


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
        values = [_text(value) for _, value in var_binds]
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
            values[int(numeric_oid.rsplit(".", 1)[1])] = _text(value)
    return values


async def _walk_indexed(engine, device, oid):
    """Walk a table whose index has more than one number (LLDP/CDP tables)."""
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
            suffix = numeric_oid[len(oid) + 1 :]
            values[tuple(int(part) for part in suffix.split("."))] = _text(value)
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


async def discover_topology(device):
    """Read neighbouring devices advertised through LLDP and, when present, CDP."""
    engine = SnmpEngine()
    try:
        local_ports = await _walk_indexed(engine, device, OIDS["lldpLocPortId"])
        lldp_local_numbers = await _walk_indexed(engine, device, OIDS["lldpRemLocalPortNum"])
        lldp_remote_ports = await _walk_indexed(engine, device, OIDS["lldpRemPortId"])
        lldp_remote_names = await _walk_indexed(engine, device, OIDS["lldpRemSysName"])

        links = []
        for index, remote_name in lldp_remote_names.items():
            if not remote_name or remote_name in {"No Such Instance currently exists at this OID", "No Such Object currently exists at this OID"}:
                continue
            local_number = int(lldp_local_numbers.get(index, 0) or 0)
            local_port = local_ports.get((local_number,), str(local_number))
            links.append({
                "local_port_name": local_port,
                "remote_device_name": remote_name,
                "remote_port_name": lldp_remote_ports.get(index, "unknown"),
                "protocol": "LLDP",
            })

        cdp_if_indices = await _walk_indexed(engine, device, OIDS["cdpCacheIfIndex"])
        cdp_remote_names = await _walk_indexed(engine, device, OIDS["cdpCacheDeviceId"])
        cdp_remote_ports = await _walk_indexed(engine, device, OIDS["cdpCacheDevicePort"])
        for index, remote_name in cdp_remote_names.items():
            if not remote_name or remote_name in {"No Such Instance currently exists at this OID", "No Such Object currently exists at this OID"}:
                continue
            links.append({
                "local_if_index": int(cdp_if_indices.get(index, index[0] if index else 0) or 0),
                "remote_device_name": remote_name,
                "remote_port_name": cdp_remote_ports.get(index, "unknown"),
                "protocol": "CDP",
            })

        unique = {}
        for link in links:
            key = (link.get("local_if_index"), link.get("local_port_name"), link["remote_device_name"].strip().lower(), link["remote_port_name"].strip().lower(), link["protocol"])
            unique[key] = link
        return list(unique.values())
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
