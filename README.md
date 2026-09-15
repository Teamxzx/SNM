# NOC LAB — SNMP Network Monitor

เว็บแอปสำหรับเรียนรู้ Network Monitoring ด้วย SNMP รองรับ Router/Switch ทั้งใน EVE-NG และอุปกรณ์จริง มี Device/Port view, traffic graph, SNMP SET, Trap receiver, topology และ realtime WebSocket พร้อม demo data สำหรับเปิดตรวจงานได้ทันที

## ฟีเจอร์ที่มีในเวอร์ชันนี้

- เพิ่มอุปกรณ์ด้วย IP Address และ credential ของ SNMP v2c หรือ v3
- อ่าน `sysName`, `sysDescr`, `sysUpTime` และทำ SNMP Walk ตาราง interface
- แสดง chassis/port map พร้อมสี Up (เขียว), Down (แดง), Warning (เหลือง)
- แสดงรายละเอียดพอร์ตและกราฟ Receive/Sent แบบ วัน / สัปดาห์ / เดือน / ปี
- คำนวณ Mbps จากผลต่างของ `ifHCInOctets` และ `ifHCOutOctets` ระหว่างรอบ polling
- สั่ง Up/Down interface ด้วย SNMP SET ที่ `ifAdminStatus`
- รับ SNMP Trap บน UDP/162 และบันทึกเฉพาะ `linkUp` / `linkDown`
- ส่ง event/device update ไป frontend ผ่าน WebSocket
- บันทึกอุปกรณ์, interface, traffic sample, trap event และ topology link ใน SQLite
- Topology ด้วย React Flow พร้อม demo LLDP links และโครงตารางสำหรับต่อยอด discovery จริง
- Demo mode มีอุปกรณ์ 3 ตัว, 52 ports, traffic ย้อนหลัง และ trap events

> UI และไอคอนเป็นงานต้นฉบับ ไม่มีโลโก้หรือ asset ของผลิตภัณฑ์/ผู้ผลิตรายใด

## โครงสร้างระบบ

```text
snmp-monitor/
├─ app/                     React + TypeScript + Tailwind dashboard
├─ components/ui/           UI primitives
├─ backend/
│  ├─ app/
│  │  ├─ main.py            FastAPI, poller, API, WebSocket
│  │  ├─ database.py        SQLite schema, queries, demo seed
│  │  ├─ snmp_client.py     PySNMP GET/WALK/SET
│  │  ├─ trap_receiver.py   UDP/162 trap receiver
│  │  └─ schemas.py         Request validation
│  ├─ scripts/
│  │  └─ send_test_trap.py  ส่ง linkUp/linkDown trap สำหรับทดสอบ
│  └─ requirements.txt
└─ README.md
```

Data flow:

```text
Router/Switch ── SNMP GET/WALK (UDP/161) ──► Poller ──► SQLite
Router/Switch ── linkUp/linkDown Trap (UDP/162) ──► Trap Receiver ──► SQLite
Browser ◄──────── REST API + WebSocket ──────── FastAPI
```

## ความต้องการ

- Node.js 22 ขึ้นไป และ pnpm 11 ขึ้นไป
- Python 3.12 ขึ้นไป
- Windows, Linux หรือ macOS
- เครื่อง backend ต้องเข้าถึง UDP/161 ของอุปกรณ์ได้
- การเปิด UDP/162 อาจต้องใช้สิทธิ์ Administrator/root; ถ้าไม่ต้องการรับ trap ระหว่างพัฒนาให้ตั้ง `SNMP_ENABLE_TRAP_RECEIVER=false`

## ติดตั้งและรัน

เปิด Terminal 2 หน้าต่างที่โฟลเดอร์โปรเจกต์

### 1. Backend

Windows PowerShell:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Linux/macOS:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

ตรวจ API ได้ที่ `http://127.0.0.1:8000/docs` และ health check ที่ `http://127.0.0.1:8000/api/health`

### 2. Frontend

```bash
pnpm install
pnpm dev
```

เปิด URL ที่แสดงใน terminal (โดยทั่วไป `http://localhost:5173`) ตัว frontend จะเรียก backend ที่ `http://127.0.0.1:8000` โดยอัตโนมัติ หาก backend อยู่คนละเครื่องให้สร้าง `.env.local` ที่ root:

```env
NEXT_PUBLIC_API_URL=http://192.168.1.50:8000/api
```

จากนั้น restart frontend

## Demo mode

ค่าเริ่มต้นใน `.env.example` คือ:

```env
SNMP_DEMO_MODE=true
```

เมื่อเริ่ม backend ครั้งแรก ระบบจะสร้างฐานข้อมูล `backend/data/snmp_monitor.db` พร้อมตัวอย่างทันที หน้าเว็บยังมี fallback demo ในตัว จึงเปิดดู UI ได้แม้ backend ยังไม่ทำงาน แต่ฟีเจอร์ persistence, REST API, trap และ WebSocket ต้องเปิด backend

ทดสอบ event โดยไม่ต้องส่ง UDP trap:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/demo/trap `
  -ContentType application/json `
  -Body '{"device_id":1,"if_index":3,"event_type":"linkDown"}'
```

ทดสอบเส้นทาง Trap จริงผ่าน UDP/162:

```bash
cd backend
python scripts/send_test_trap.py --event linkDown --if-index 3
python scripts/send_test_trap.py --event linkUp --if-index 3
```

## เพิ่มอุปกรณ์

1. กด **เพิ่มอุปกรณ์** มุมขวาบน
2. ใส่ชื่อ (ไม่บังคับ), IP Address และเลือก SNMP v2c/v3
3. v2c: ใส่ community string; v3: ใส่ username, security level, auth/privacy protocol และ password
4. กด **ทดสอบและเพิ่ม** ระบบจะ GET System MIB และ Walk IF-MIB
5. ถ้าอุปกรณ์ยังตอบไม่ได้ ระบบเก็บรายการเป็น Offline เพื่อแก้ network/credential แล้วสั่ง Poll ใหม่ผ่าน `POST /api/devices/{id}/poll`

Credential ถูกเก็บใน SQLite แบบ plain text เพื่อให้โค้ดอ่านง่ายในชั้นเรียน สำหรับ production ต้องเข้ารหัส secret หรือใช้ secrets manager และจำกัดสิทธิ์ไฟล์ฐานข้อมูล

## เปิด SNMP บนอุปกรณ์

คำสั่งจริงขึ้นกับ OS/image ที่ใช้ ตัวอย่างแนว IOS-like สำหรับห้องแลบ:

```text
configure terminal
snmp-server community noclab RO
snmp-server community noclab-rw RW
snmp-server host <BACKEND_IP> version 2c noclab
snmp-server enable traps snmp linkdown linkup
interface GigabitEthernet0/1
 snmp trap link-status
end
write memory
```

- ใช้ community แบบ RO สำหรับ polling
- การสั่ง Up/Down ต้องใช้ community/user ที่มี write permission
- กำหนด ACL ให้ UDP/161 รับเฉพาะ IP ของ backend
- Trap destination ต้องเป็น IP ที่อุปกรณ์ในแลบ route ไปถึงได้
- ชื่อคำสั่งอาจต่างกันตาม image ให้ตรวจคู่มือของ OS ที่ใช้อยู่

ตัวอย่าง SNMPv3 แนว IOS-like:

```text
configure terminal
snmp-server group noclab v3 priv
snmp-server user student noclab v3 auth sha <AUTH_PASSWORD> priv aes 128 <PRIV_PASSWORD>
snmp-server host <BACKEND_IP> version 3 priv student
snmp-server enable traps snmp linkdown linkup
end
```

สำหรับ Linux/snmpd ให้ติดตั้ง Net-SNMP, ตั้ง `agentAddress udp:161`, กำหนด `rocommunity`/`rwcommunity` หรือ USM user แล้ว restart `snmpd` อย่าเปิด community แบบเขียนได้ให้เครือข่ายภายนอกเข้าถึง

## ทดสอบกับ EVE-NG

1. เพิ่ม management/cloud network ที่ Router/Switch และเครื่อง backend เข้าถึงกันได้
2. ตั้ง IP management และ route กลับมายัง backend
3. เปิด SNMP/Trap ด้วยคำสั่งตาม image
4. จากเครื่อง backend ทดสอบก่อน:

```bash
snmpget -v2c -c noclab <DEVICE_IP> 1.3.6.1.2.1.1.5.0
snmpwalk -v2c -c noclab <DEVICE_IP> 1.3.6.1.2.1.2.2.1.2
```

5. เพิ่มอุปกรณ์ในหน้าเว็บ
6. ทดสอบ trap ด้วยการ `shutdown` / `no shutdown` interface แล้วดูหน้า Trap Events
7. ถ้า backend อยู่บน Windows ให้เปิด inbound firewall UDP/162; ถ้า EVE-NG อยู่คนละ VM ให้ตรวจ Host-only/Bridged network และ NAT

## OID ที่ระบบใช้

| รายการ | OID |
|---|---|
| sysDescr | `1.3.6.1.2.1.1.1.0` |
| sysUpTime | `1.3.6.1.2.1.1.3.0` |
| sysName | `1.3.6.1.2.1.1.5.0` |
| ifName | `1.3.6.1.2.1.31.1.1.1.1` |
| ifDescr | `1.3.6.1.2.1.2.2.1.2` |
| ifSpeed / ifHighSpeed | `1.3.6.1.2.1.2.2.1.5` / `1.3.6.1.2.1.31.1.1.1.15` |
| ifAdminStatus | `1.3.6.1.2.1.2.2.1.7` |
| ifOperStatus | `1.3.6.1.2.1.2.2.1.8` |
| ifLastChange | `1.3.6.1.2.1.2.2.1.9` |
| ifHCInOctets | `1.3.6.1.2.1.31.1.1.1.6` |
| ifHCOutOctets | `1.3.6.1.2.1.31.1.1.1.10` |
| linkDown | `1.3.6.1.6.3.1.1.5.3` |
| linkUp | `1.3.6.1.6.3.1.1.5.4` |

Mbps คำนวณด้วยสูตร:

```text
Mbps = (new_octets - old_octets) × 8 / elapsed_seconds / 1,000,000
```

ถ้า counter ลดลงเพราะ reboot/counter rollover ระบบจะไม่บันทึกค่าติดลบ

## API หลัก

| Method | Endpoint | หน้าที่ |
|---|---|---|
| GET | `/api/devices` | รายการอุปกรณ์และ ports |
| POST | `/api/devices` | ทดสอบและเพิ่มอุปกรณ์ |
| GET | `/api/devices/{id}` | Device/Port view |
| POST | `/api/devices/{id}/poll` | Poll ทันที |
| POST | `/api/devices/{id}/interfaces/{ifIndex}/admin` | SNMP SET Up/Down |
| GET | `/api/devices/{id}/interfaces/{ifIndex}/traffic?period=day` | Traffic history |
| GET | `/api/events` | Trap event log |
| GET | `/api/topology` | Device/link topology |
| WS | `/ws` | Realtime trap/device update |

## ต่อไปยัง TimescaleDB / InfluxDB

ตาราง `traffic_samples` ถูกแยกจาก device/interface metadata แล้ว จึงเปลี่ยนเฉพาะชั้น time-series repository ได้ โดยคง SQLite สำหรับ inventory และ event log:

- TimescaleDB: map `interface_id` เป็น tag/key และใช้ hypertable บน `sampled_at`
- InfluxDB: measurement `interface_traffic`, tags `device_id`/`if_index`, fields `in_mbps`/`out_mbps`
- เพิ่ม downsampling/retention แยกตามช่วงวัน สัปดาห์ เดือน ปี

สำหรับ topology discovery จริง ให้ Walk LLDP-MIB (`lldpRemSysName`, `lldpRemPortId`) และ vendor CDP MIB แล้ว upsert ลง `topology_links`; โครงตารางและหน้า React Flow เตรียมไว้แล้ว

## หมายเหตุด้านความปลอดภัย

- ควรใช้ SNMPv3 `authPriv` เมื่อพ้นจากห้องแลบ
- จำกัด source/destination ด้วย ACL และ firewall
- เปลี่ยน trap port เป็น `1162` ได้เมื่อต้องการรันแบบ non-root แล้วทำ firewall/port forward มายังพอร์ตนั้น
- อย่าเปิด RW community สู่ Internet
- ควรเพิ่ม authentication/role-based access ก่อนใช้ SNMP SET ในระบบจริง
