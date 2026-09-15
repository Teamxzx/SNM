import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .database import connect, device_dict, event_dict, initialize_database, row_dict, seed_demo_data
from .schemas import AdminStatusUpdate, DemoTrapCreate, DeviceCreate
from .snmp_client import get_system, set_admin_status, walk_interfaces
from .trap_receiver import TrapReceiver


load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
LOGGER = logging.getLogger("snmp-monitor")
POLL_INTERVAL = int(os.getenv("SNMP_POLL_INTERVAL", "30"))
DEMO_MODE = os.getenv("SNMP_DEMO_MODE", "true").lower() == "true"


class WebSocketHub:
    def __init__(self):
        self.clients: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.clients.add(websocket)

    def disconnect(self, websocket: WebSocket):
        self.clients.discard(websocket)

    async def broadcast(self, payload: dict):
        stale = []
        for client in self.clients:
            try:
                await client.send_json(payload)
            except Exception:
                stale.append(client)
        for client in stale:
            self.disconnect(client)


hub = WebSocketHub()
poll_task = None
trap_receiver = None


def load_device(device_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        return row_dict(row)


def persist_interfaces(device_id: int, interfaces: list[dict]):
    now = datetime.now(timezone.utc).isoformat()
    with connect() as db:
        for interface in interfaces:
            previous = db.execute("SELECT * FROM interfaces WHERE device_id=? AND if_index=?", (device_id, interface["if_index"])).fetchone()
            db.execute(
                """INSERT INTO interfaces(device_id, if_index, if_name, if_descr, admin_status, oper_status, speed_bps, last_change_ticks, in_octets, out_octets, last_polled)
                VALUES(:device_id,:if_index,:if_name,:if_descr,:admin_status,:oper_status,:speed_bps,:last_change_ticks,:in_octets,:out_octets,:last_polled)
                ON CONFLICT(device_id,if_index) DO UPDATE SET if_name=excluded.if_name,if_descr=excluded.if_descr,admin_status=excluded.admin_status,
                oper_status=excluded.oper_status,speed_bps=excluded.speed_bps,last_change_ticks=excluded.last_change_ticks,in_octets=excluded.in_octets,out_octets=excluded.out_octets,last_polled=excluded.last_polled""",
                {**interface, "device_id": device_id, "last_polled": now},
            )
            current = db.execute("SELECT id FROM interfaces WHERE device_id=? AND if_index=?", (device_id, interface["if_index"])).fetchone()
            if previous and previous["last_polled"]:
                seconds = max(1, (datetime.fromisoformat(now) - datetime.fromisoformat(previous["last_polled"])).total_seconds())
                in_delta = max(0, interface["in_octets"] - previous["in_octets"])
                out_delta = max(0, interface["out_octets"] - previous["out_octets"])
                db.execute("INSERT INTO traffic_samples(interface_id, sampled_at, in_mbps, out_mbps, in_octets, out_octets) VALUES(?,?,?,?,?,?)", (current["id"], now, in_delta * 8 / seconds / 1_000_000, out_delta * 8 / seconds / 1_000_000, interface["in_octets"], interface["out_octets"]))


async def poll_one(device: dict):
    if DEMO_MODE and device["ip_address"].startswith("10.10.0."):
        return
    try:
        system, interfaces = await asyncio.gather(get_system(device), walk_interfaces(device))
        with connect() as db:
            db.execute("UPDATE devices SET name=?, sys_descr=?, sys_uptime_ticks=?, status='online', last_seen=? WHERE id=?", (system["sys_name"] or device["name"], system["sys_descr"], system["sys_uptime_ticks"], datetime.now(timezone.utc).isoformat(), device["id"]))
        persist_interfaces(device["id"], interfaces)
        with connect() as db:
            updated = device_dict(db, db.execute("SELECT * FROM devices WHERE id=?", (device["id"],)).fetchone())
        await hub.broadcast({"type": "device_update", "data": updated})
    except Exception as exc:
        LOGGER.info("SNMP poll failed for %s: %s", device["ip_address"], exc)
        with connect() as db:
            db.execute("UPDATE devices SET status='offline' WHERE id=?", (device["id"],))


async def polling_loop():
    while True:
        with connect() as db:
            devices = [row_dict(row) for row in db.execute("SELECT * FROM devices").fetchall()]
        await asyncio.gather(*(poll_one(device) for device in devices), return_exceptions=True)
        await asyncio.sleep(POLL_INTERVAL)


async def store_trap(payload: dict):
    source_ip = payload["source_ip"]
    with connect() as db:
        device = db.execute("SELECT * FROM devices WHERE ip_address=?", (source_ip,)).fetchone()
        device_id = device["id"] if device else None
        interface = db.execute("SELECT * FROM interfaces WHERE device_id=? AND if_index=?", (device_id, payload.get("if_index"))).fetchone() if device else None
        interface_name = interface["if_name"] if interface else f"ifIndex {payload.get('if_index', '?')}"
        event_type = payload["event_type"]
        cursor = db.execute("INSERT INTO trap_events(occurred_at, device_id, source_ip, if_index, interface_name, event_type, severity, message, raw_varbinds) VALUES(?,?,?,?,?,?,?,?,?)", (datetime.now(timezone.utc).isoformat(), device_id, source_ip, payload.get("if_index"), interface_name, event_type, "critical" if event_type == "linkDown" else "info", f"Interface {interface_name} changed state to {'down' if event_type == 'linkDown' else 'up'}", payload.get("raw_varbinds", "{}")))
        row = db.execute("SELECT t.*, d.name device_name FROM trap_events t LEFT JOIN devices d ON d.id=t.device_id WHERE t.id=?", (cursor.lastrowid,)).fetchone()
        event = event_dict(row)
    await hub.broadcast({"type": "trap", "data": event})
    return event


@asynccontextmanager
async def lifespan(app: FastAPI):
    global poll_task, trap_receiver
    initialize_database()
    if DEMO_MODE:
        seed_demo_data()
    loop = asyncio.get_running_loop()
    poll_task = asyncio.create_task(polling_loop())
    if os.getenv("SNMP_ENABLE_TRAP_RECEIVER", "true").lower() == "true":
        trap_receiver = TrapReceiver(os.getenv("SNMP_TRAP_HOST", "0.0.0.0"), int(os.getenv("SNMP_TRAP_PORT", "162")), os.getenv("SNMP_TRAP_COMMUNITY", "public"), lambda event: asyncio.run_coroutine_threadsafe(store_trap(event), loop))
        trap_receiver.start()
    yield
    poll_task.cancel()
    if trap_receiver:
        trap_receiver.stop()


app = FastAPI(title="NOC LAB SNMP Monitor", version="1.0.0", lifespan=lifespan)
origins = [value.strip() for value in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"status": "ok", "demo_mode": DEMO_MODE, "poll_interval": POLL_INTERVAL}


@app.get("/api/devices")
def list_devices():
    with connect() as db:
        return [device_dict(db, row) for row in db.execute("SELECT * FROM devices ORDER BY name").fetchall()]


@app.get("/api/devices/{device_id}")
def get_device(device_id: int):
    with connect() as db:
        row = db.execute("SELECT * FROM devices WHERE id=?", (device_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Device not found")
        return device_dict(db, row)


@app.post("/api/devices", status_code=201)
async def add_device(payload: DeviceCreate):
    data = payload.model_dump(mode="json")
    data["ip_address"] = str(payload.ip_address)
    system = None
    try:
        system = await get_system(data)
    except Exception as exc:
        LOGGER.info("Initial SNMP probe failed for %s: %s", data["ip_address"], exc)
    with connect() as db:
        try:
            cursor = db.execute(
                """INSERT INTO devices(name,ip_address,device_type,snmp_version,community,username,security_level,auth_protocol,auth_password,priv_protocol,priv_password,sys_descr,sys_uptime_ticks,status,last_seen)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (payload.name or (system and system["sys_name"]) or data["ip_address"], data["ip_address"], payload.device_type, payload.snmp_version, payload.community, payload.username, payload.security_level, payload.auth_protocol, payload.auth_password, payload.priv_protocol, payload.priv_password, (system and system["sys_descr"]) or "Waiting for SNMP response", (system and system["sys_uptime_ticks"]) or 0, "online" if system else "offline", datetime.now(timezone.utc).isoformat() if system else None),
            )
        except Exception as exc:
            raise HTTPException(409, "IP address already exists") from exc
        device_id = cursor.lastrowid
    if system:
        try:
            persist_interfaces(device_id, await walk_interfaces({**data, "id": device_id}))
        except Exception as exc:
            LOGGER.info("Initial interface walk failed: %s", exc)
    return get_device(device_id)


@app.delete("/api/devices/{device_id}", status_code=204)
def delete_device(device_id: int):
    with connect() as db:
        if not db.execute("SELECT id FROM devices WHERE id=?", (device_id,)).fetchone():
            raise HTTPException(404, "Device not found")
        db.execute("DELETE FROM devices WHERE id=?", (device_id,))


@app.post("/api/devices/{device_id}/poll")
async def poll_now(device_id: int):
    device = load_device(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    await poll_one(device)
    return get_device(device_id)


@app.post("/api/devices/{device_id}/interfaces/{if_index}/admin")
async def change_admin_status(device_id: int, if_index: int, payload: AdminStatusUpdate):
    device = load_device(device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    if not (DEMO_MODE and device["ip_address"].startswith("10.10.0.")):
        try:
            await set_admin_status(device, if_index, payload.admin_status)
        except Exception as exc:
            raise HTTPException(502, f"SNMP SET failed: {exc}") from exc
    with connect() as db:
        cursor = db.execute("UPDATE interfaces SET admin_status=?, oper_status=? WHERE device_id=? AND if_index=?", (payload.admin_status, payload.admin_status, device_id, if_index))
        if not cursor.rowcount:
            raise HTTPException(404, "Interface not found")
    return {"device_id": device_id, "if_index": if_index, "admin_status": payload.admin_status}


@app.get("/api/devices/{device_id}/interfaces/{if_index}/traffic")
def traffic_history(device_id: int, if_index: int, period: str = Query("day", pattern="^(day|week|month|year)$")):
    ranges = {"day": timedelta(days=1), "week": timedelta(days=7), "month": timedelta(days=31), "year": timedelta(days=366)}
    start = (datetime.now(timezone.utc) - ranges[period]).isoformat()
    with connect() as db:
        interface = db.execute("SELECT id FROM interfaces WHERE device_id=? AND if_index=?", (device_id, if_index)).fetchone()
        if not interface:
            raise HTTPException(404, "Interface not found")
        rows = db.execute("SELECT sampled_at, in_mbps, out_mbps FROM traffic_samples WHERE interface_id=? AND sampled_at>=? ORDER BY sampled_at", (interface["id"], start)).fetchall()
        return [row_dict(row) for row in rows]


@app.get("/api/events")
def list_events(limit: int = Query(100, ge=1, le=1000)):
    with connect() as db:
        rows = db.execute("SELECT t.*, d.name device_name FROM trap_events t LEFT JOIN devices d ON d.id=t.device_id ORDER BY t.occurred_at DESC LIMIT ?", (limit,)).fetchall()
        return [event_dict(row) for row in rows]


@app.post("/api/demo/trap", status_code=201)
async def create_demo_trap(payload: DemoTrapCreate):
    if not DEMO_MODE:
        raise HTTPException(404, "Demo mode is disabled")
    device = load_device(payload.device_id)
    if not device:
        raise HTTPException(404, "Device not found")
    return await store_trap({"source_ip": device["ip_address"], "if_index": payload.if_index, "event_type": payload.event_type, "raw_varbinds": json.dumps({"demo": True})})


@app.get("/api/topology")
def topology():
    with connect() as db:
        devices = [device_dict(db, row) for row in db.execute("SELECT * FROM devices ORDER BY id").fetchall()]
        links = [row_dict(row) for row in db.execute("SELECT * FROM topology_links ORDER BY id").fetchall()]
        return {"devices": devices, "links": links}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await hub.connect(websocket)
    try:
        await websocket.send_json({"type": "connected", "data": {"message": "SNMP realtime stream connected"}})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        hub.disconnect(websocket)
