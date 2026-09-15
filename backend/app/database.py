import json
import math
import os
import random
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path


DB_PATH = Path(os.getenv("SNMP_MONITOR_DB", "./data/snmp_monitor.db"))


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def initialize_database():
    with connect() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                ip_address TEXT NOT NULL UNIQUE,
                device_type TEXT NOT NULL DEFAULT 'switch',
                snmp_version TEXT NOT NULL DEFAULT '2c',
                community TEXT,
                username TEXT,
                security_level TEXT,
                auth_protocol TEXT,
                auth_password TEXT,
                priv_protocol TEXT,
                priv_password TEXT,
                sys_descr TEXT NOT NULL DEFAULT '',
                sys_uptime_ticks INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'offline',
                last_seen TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS interfaces (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                if_index INTEGER NOT NULL,
                if_name TEXT NOT NULL,
                if_descr TEXT NOT NULL DEFAULT '',
                admin_status INTEGER NOT NULL DEFAULT 2,
                oper_status INTEGER NOT NULL DEFAULT 2,
                speed_bps INTEGER NOT NULL DEFAULT 0,
                last_change_ticks INTEGER NOT NULL DEFAULT 0,
                in_octets INTEGER NOT NULL DEFAULT 0,
                out_octets INTEGER NOT NULL DEFAULT 0,
                last_polled TEXT,
                UNIQUE(device_id, if_index)
            );

            CREATE TABLE IF NOT EXISTS traffic_samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                interface_id INTEGER NOT NULL REFERENCES interfaces(id) ON DELETE CASCADE,
                sampled_at TEXT NOT NULL,
                in_mbps REAL NOT NULL,
                out_mbps REAL NOT NULL,
                in_octets INTEGER NOT NULL,
                out_octets INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS trap_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                device_id INTEGER REFERENCES devices(id) ON DELETE SET NULL,
                source_ip TEXT NOT NULL,
                if_index INTEGER,
                interface_name TEXT,
                event_type TEXT NOT NULL CHECK(event_type IN ('linkUp', 'linkDown')),
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                raw_varbinds TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS topology_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
                local_if_index INTEGER NOT NULL,
                remote_device_name TEXT NOT NULL,
                remote_port_name TEXT NOT NULL,
                protocol TEXT NOT NULL,
                discovered_at TEXT NOT NULL,
                UNIQUE(local_device_id, local_if_index, remote_device_name, remote_port_name)
            );

            CREATE INDEX IF NOT EXISTS idx_interfaces_device ON interfaces(device_id);
            CREATE INDEX IF NOT EXISTS idx_traffic_interface_time ON traffic_samples(interface_id, sampled_at);
            CREATE INDEX IF NOT EXISTS idx_traps_time ON trap_events(occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_traps_device_time ON trap_events(device_id, occurred_at DESC);
            CREATE INDEX IF NOT EXISTS idx_links_local_device ON topology_links(local_device_id);
            PRAGMA optimize;
            """
        )


def seed_demo_data():
    with connect() as db:
        if db.execute("SELECT COUNT(*) FROM devices").fetchone()[0]:
            return
        now = datetime.now(timezone.utc)
        demo = [
            ("CORE-RTR-01", "10.10.0.1", "router", "NetOS Virtual Router 7.4 · EVE-NG lab", "online", 12),
            ("LAB-SW-01", "10.10.0.11", "switch", "Layer 2 managed switch · Student Lab A", "warning", 24),
            ("EDGE-SW-02", "10.10.0.12", "switch", "Secure access switch · Building B", "online", 16),
        ]
        ids = []
        for name, ip, kind, descr, status, count in demo:
            cursor = db.execute(
                "INSERT INTO devices(name, ip_address, device_type, snmp_version, community, sys_descr, sys_uptime_ticks, status, last_seen) VALUES(?,?,?,?,?,?,?,?,?)",
                (name, ip, kind, "2c", "public", descr, random.randint(7000000, 300000000), status, now.isoformat()),
            )
            device_id = cursor.lastrowid
            ids.append(device_id)
            for index in range(1, count + 1):
                down = (device_id == ids[0] and index == 8) or (name == "LAB-SW-01" and index > 18) or (name == "EDGE-SW-02" and index > 13)
                warning = name == "LAB-SW-01" and index == 12
                admin, oper = (2, 2) if down else (1, 3) if warning else (1, 1)
                port = db.execute(
                    "INSERT INTO interfaces(device_id, if_index, if_name, if_descr, admin_status, oper_status, speed_bps, last_change_ticks, in_octets, out_octets, last_polled) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (device_id, index, f"Gi0/{index}", f"GigabitEthernet0/{index}", admin, oper, 1_000_000_000, random.randint(1200, 900000), random.randint(10**8, 10**10), random.randint(10**8, 10**10), now.isoformat()),
                )
                interface_id = port.lastrowid
                for point in range(48):
                    stamp = now - timedelta(minutes=(47 - point) * 30)
                    base = 10 + ((index * 7) % 35)
                    in_rate = max(0, base + math.sin(point / 4) * 8 + random.random() * 4)
                    out_rate = max(0, base * .55 + math.cos(point / 5) * 5 + random.random() * 3)
                    db.execute("INSERT INTO traffic_samples(interface_id, sampled_at, in_mbps, out_mbps, in_octets, out_octets) VALUES(?,?,?,?,?,?)", (interface_id, stamp.isoformat(), in_rate, out_rate, int(in_rate * 1_000_000), int(out_rate * 1_000_000)))
        db.execute("INSERT INTO topology_links(local_device_id, local_if_index, remote_device_name, remote_port_name, protocol, discovered_at) VALUES(?,?,?,?,?,?)", (ids[0], 2, "LAB-SW-01", "Gi0/24", "LLDP", now.isoformat()))
        db.execute("INSERT INTO topology_links(local_device_id, local_if_index, remote_device_name, remote_port_name, protocol, discovered_at) VALUES(?,?,?,?,?,?)", (ids[0], 3, "EDGE-SW-02", "Gi0/16", "LLDP", now.isoformat()))
        traps = [(ids[0], "10.10.0.1", 8, "Gi0/8", "linkDown"), (ids[1], "10.10.0.11", 12, "Gi0/12", "linkUp"), (ids[2], "10.10.0.12", 6, "Gi0/6", "linkUp")]
        for offset, (device_id, ip, if_index, name, kind) in enumerate(traps):
            db.execute("INSERT INTO trap_events(occurred_at, device_id, source_ip, if_index, interface_name, event_type, severity, message) VALUES(?,?,?,?,?,?,?,?)", ((now - timedelta(minutes=offset * 17)).isoformat(), device_id, ip, if_index, name, kind, "critical" if kind == "linkDown" else "info", f"Interface {name} changed state to {'down' if kind == 'linkDown' else 'up'}"))


def row_dict(row):
    return dict(row) if row else None


def uptime_text(ticks: int) -> str:
    seconds = max(0, ticks // 100)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{days:02d} วัน {hours:02d}:{minutes:02d}:{seconds:02d}"


def interface_dict(row):
    item = row_dict(row)
    item["status"] = "up" if item["oper_status"] == 1 else "warning" if item["admin_status"] == 1 else "down"
    item["last_change"] = f"{max(0, item['last_change_ticks'] // 6000)} นาทีที่แล้ว"
    return item


def device_dict(db, row):
    item = row_dict(row)
    item["sys_uptime"] = uptime_text(item.pop("sys_uptime_ticks"))
    item["last_seen"] = item["last_seen"] or "ยังไม่เคยพบ"
    ports = db.execute(
        """SELECT i.*, COALESCE((SELECT in_mbps FROM traffic_samples t WHERE t.interface_id=i.id ORDER BY sampled_at DESC LIMIT 1),0) in_mbps,
        COALESCE((SELECT out_mbps FROM traffic_samples t WHERE t.interface_id=i.id ORDER BY sampled_at DESC LIMIT 1),0) out_mbps FROM interfaces i WHERE device_id=? ORDER BY if_index""",
        (item["id"],),
    ).fetchall()
    item["ports"] = [interface_dict(port) for port in ports]
    for secret in ("community", "username", "security_level", "auth_protocol", "auth_password", "priv_protocol", "priv_password"):
        item.pop(secret, None)
    return item


def event_dict(row):
    item = row_dict(row)
    stamp = datetime.fromisoformat(item["occurred_at"])
    item["occurred_at"] = stamp.astimezone().strftime("%d/%m/%Y %H:%M:%S")
    item["device"] = item.pop("device_name") or "Unknown device"
    item["ip_address"] = item.pop("source_ip")
    item["interface"] = item.pop("interface_name") or f"ifIndex {item.get('if_index', '?')}"
    item.pop("raw_varbinds", None)
    return item
