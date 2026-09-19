# NOC LAB — SNMP Network Monitor

Web Application สำหรับเรียนรู้การทำ Network Monitoring ด้วย SNMP ใช้ได้ทั้ง Router/Switch จริงและห้องทดลอง EVE-NG หน้าตาเป็น NOC Dashboard ที่อ่านสถานะได้เร็วในแนวทางเดียวกับระบบ monitoring ระดับองค์กร แต่เป็นงานต้นฉบับสำหรับการเรียนรู้

โปรเจกต์นี้ไม่ใช่แค่หน้า UI: Backend จะ Poll อุปกรณ์ผ่าน SNMP, รับ Trap จริงบน UDP/162, บันทึกข้อมูลลง SQLite และส่งสถานะใหม่ไปหน้าเว็บผ่าน WebSocket

> ไม่มีการใช้โลโก้ PRTG, Cisco หรือแบรนด์จริง

## สารบัญ

- [โปรเจกต์ทำอะไรได้บ้าง](#โปรเจกต์ทำอะไรได้บ้าง)
- [ภาพรวมการทำงาน](#ภาพรวมการทำงาน)
- [โครงสร้างโค้ด](#โครงสร้างโค้ด)
- [สิ่งที่ต้องติดตั้ง](#สิ่งที่ต้องติดตั้ง)
- [เริ่มรันโปรเจกต์](#เริ่มรันโปรเจกต์)
- [ใช้งานกับ EVE-NG และอุปกรณ์จริง](#ใช้งานกับ-eve-ng-และอุปกรณ์จริง)
- [การใช้งานหน้าเว็บ](#การใช้งานหน้าเว็บ)
- [OID และ API](#oid-และ-api)
- [แก้ปัญหาที่พบบ่อย](#แก้ปัญหาที่พบบ่อย)
- [แนวทางอธิบายอาจารย์](#แนวทางอธิบายอาจารย์)

## โปรเจกต์ทำอะไรได้บ้าง

- เพิ่ม Router หรือ Switch ด้วย IP Address และ SNMP v2c / v3 credential
- อ่าน `sysName`, `sysDescr`, `sysUpTime` และ SNMP Walk ทุก Interface จาก IF-MIB
- แสดง Port View: เขียว = up, แดง = down, เหลือง = warning
- แสดงกราฟ Receive / Sent รายวัน, สัปดาห์, เดือน และปี
- คำนวณ Traffic เป็น Mbps จาก `ifHCInOctets` และ `ifHCOutOctets`
- สั่ง Up / Down port ด้วย SNMP SET ที่ `ifAdminStatus`
- รับเฉพาะ `linkUp` และ `linkDown` ผ่าน SNMP Trap บน UDP/162
- แสดง Trap Event แบบ realtime ผ่าน WebSocket พร้อมเก็บ Event Log ใน SQLite
- สร้าง Network map จาก LLDP หรือ CDP ผ่าน SNMP และแสดงเส้นพร้อมชื่อ port
- เพิ่ม VPCS / PC ในแผนที่แบบ Manual Endpoint ได้ เพราะ VPCS ไม่มี SNMP, LLDP หรือ CDP

## ภาพรวมการทำงาน

```text
                 SNMP GET / WALK / SET (UDP 161)
Router / Switch ───────────────────────────────────► FastAPI + PySNMP
                                                          │
                                                          ├── SQLite
                                                          │    devices / ports / traffic / events / links
                                                          │
Router / Switch ── linkUp / linkDown Trap (UDP 162) ──────┤
                                                          │
Browser (React) ◄──── REST API + WebSocket ───────────────┘
```

ระบบมีสองส่วนที่ต้องรันพร้อมกัน:

| ส่วน | หน้าที่ | URL ปกติ |
|---|---|---|
| Frontend | หน้า Dashboard, Port View, Graph, Network map | `http://localhost:5173` |
| Backend | REST API, Poller, Trap Receiver, SQLite | `http://127.0.0.1:8000` |

พอร์ตที่เกี่ยวข้อง:

| Port | ทิศทาง | ใช้ทำอะไร |
|---|---|---|
| TCP 5173 | Browser → Frontend | เปิดหน้าเว็บ |
| TCP 8000 | Browser → Backend | REST API / WebSocket |
| UDP 161 | Backend → Device | SNMP GET, WALK, SET |
| UDP 162 | Device → Backend | SNMP Trap |

## โครงสร้างโค้ด

```text
snmp-monitor/
├─ app/
│  └─ monitor-app.tsx       หน้าจอ React: Dashboard, Port, Graph, Topology
├─ components/ui/           ชิ้นส่วน UI ที่ใช้ซ้ำ
├─ backend/
│  ├─ app/
│  │  ├─ main.py            FastAPI routes, poll loop, WebSocket และ topology sync
│  │  ├─ snmp_client.py     PySNMP GET/WALK/SET และ LLDP/CDP discovery
│  │  ├─ trap_receiver.py   ตัวรับ UDP/162 และแปลง Trap เป็น event
│  │  ├─ database.py        SQLite schema และการอ่าน/เขียนข้อมูล
│  │  └─ schemas.py         ตรวจสอบข้อมูลก่อนเข้า API
│  ├─ scripts/send_test_trap.py
│  ├─ .env.example
│  └─ requirements.txt
├─ package.json
└─ README.md
```

### โค้ดแต่ละส่วนทำงานอย่างไร

1. `main.py` เริ่ม FastAPI และสร้าง polling loop ทุก `SNMP_POLL_INTERVAL` วินาที
2. `snmp_client.py` ติดต่ออุปกรณ์ด้วย PySNMP เพื่ออ่าน System MIB, IF-MIB, LLDP/CDP และส่ง SNMP SET
3. `database.py` เก็บ inventory, interface, counter, traffic, Trap และ topology link ลง SQLite
4. `trap_receiver.py` เปิด UDP/162 รอ `linkUp` / `linkDown` แล้ว broadcast ไป Browser ด้วย WebSocket
5. `monitor-app.tsx` เรียก REST API มาแสดงผลและรับ event ใหม่ทันทีจาก WebSocket

สูตร Traffic:

```text
Mbps = (current_octets - previous_octets) × 8 / elapsed_seconds / 1,000,000
```

กล่าวคือระบบไม่ได้อ่านค่า Mbps จากอุปกรณ์โดยตรง แต่คำนวณจากผลต่างของ counter 64-bit ในแต่ละรอบ Poll

## สิ่งที่ต้องติดตั้ง

- Node.js 22 ขึ้นไป
- pnpm 11 ขึ้นไป
- Python 3.11 ขึ้นไป
- EVE-NG หรือ Router/Switch ที่เปิด SNMP ได้ สำหรับ Live mode

ตรวจรุ่นบน Windows PowerShell:

```powershell
node --version
python --version
pnpm.cmd --version
```

ถ้า PowerShell แจ้ง `pnpm.ps1 cannot be loaded because running scripts is disabled` ให้ใช้ `pnpm.cmd` แทน `pnpm` โดยไม่ต้องปรับลดความปลอดภัยของ PowerShell

## เริ่มรันโปรเจกต์

เปิด PowerShell สองหน้าต่าง แล้วเข้าโฟลเดอร์โปรเจกต์:

```powershell
cd C:\Users\Admin\Documents\Codex\2026-09-16\prompt-2-snmp-monitor-router-switch\outputs\snmp-monitor
```

### หน้าต่างที่ 1: เริ่ม Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

คำสั่ง `Copy-Item .env.example .env` ใช้เฉพาะครั้งแรกเท่านั้น เพราะการคัดลอกซ้ำจะเขียนทับค่า Live mode

เมื่อ Backend พร้อม จะเห็นข้อความลักษณะนี้:

```text
Application startup complete.
SNMP trap receiver listening on 0.0.0.0:162/udp
```

ตรวจสุขภาพ Backend:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/health"
```

ถ้าขึ้น `status : ok` แปลว่า Backend ทำงานแล้ว เปิดเอกสาร API ได้ที่ `http://127.0.0.1:8000/docs`

### หน้าต่างที่ 2: เริ่ม Frontend

```powershell
cd C:\Users\Admin\Documents\Codex\2026-09-16\prompt-2-snmp-monitor-router-switch\outputs\snmp-monitor
pnpm.cmd install
pnpm.cmd dev
```

เปิด URL ที่ terminal แสดง ซึ่งปกติคือ `http://localhost:5173/`

> ต้องเปิด Backend ไว้พร้อม Frontend จึงจะได้ข้อมูลจริง, Trap และ WebSocket หน้าเว็บอาจเปิดได้แม้ Backend ปิด แต่จะแสดง fallback/demo data เท่านั้น

### ใช้ Frontend จากเครื่องอื่น

สร้าง `.env.local` ใน root ของโปรเจกต์:

```env
NEXT_PUBLIC_API_URL=http://<BACKEND_IP>:8000/api
```

เริ่ม Frontend ใหม่ และเพิ่ม URL นั้นลงใน `FRONTEND_ORIGINS` ของ `backend/.env`

## Demo mode

ค่าเริ่มต้นใน `backend/.env.example`:

```env
SNMP_DEMO_MODE=true
```

Backend จะสร้างข้อมูลตัวอย่าง 3 อุปกรณ์, port, traffic และ Trap ใน `backend/data/snmp_monitor.db` เหมาะสำหรับอธิบาย UI โดยไม่ต้องมี EVE-NG

ส่ง Trap จำลองใน Demo mode:

```powershell
Invoke-RestMethod -Method Post `
  -Uri http://127.0.0.1:8000/api/demo/trap `
  -ContentType application/json `
  -Body '{"device_id":1,"if_index":3,"event_type":"linkDown"}'
```

ทดสอบ UDP Trap ด้วย script:

```powershell
cd backend
.\.venv\Scripts\python.exe scripts\send_test_trap.py --event linkDown --if-index 3
.\.venv\Scripts\python.exe scripts\send_test_trap.py --event linkUp --if-index 3
```

## ใช้งานกับ EVE-NG และอุปกรณ์จริง

### 1. เปลี่ยนเป็น Live mode

แก้ `backend/.env` เป็น:

```env
SNMP_MONITOR_DB=./data/snmp_monitor.db
SNMP_POLL_INTERVAL=30
SNMP_TRAP_HOST=0.0.0.0
SNMP_TRAP_PORT=162
SNMP_TRAP_COMMUNITY=noclab
SNMP_ENABLE_TRAP_RECEIVER=true
SNMP_DEMO_MODE=false
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

ถ้าเปิดหน้าเว็บด้วย IP ของเครื่อง Backend ให้เพิ่ม origin นั้นด้วย เช่น:

```env
FRONTEND_ORIGINS=http://localhost:5173,http://127.0.0.1:5173,http://192.168.70.1:5173
```

กด `Ctrl+C` ที่ Backend แล้วรัน Uvicorn ใหม่ จากนั้นตรวจ health check ต้องเห็น `demo_mode : False`

### 2. เชื่อม EVE-NG เข้ากับ Management Network

ต่อ Router/Switch เข้ากับ `Management (Cloud0)` และตั้ง IP management ให้อยู่ network เดียวกับเครื่อง Backend หรือมี route หากันได้

แผน IP ตัวอย่างของห้องแลบนี้:

| อุปกรณ์ | IP management | หน้าที่ |
|---|---|---|
| Backend Windows | `192.168.70.1` | Poll SNMP และรับ Trap |
| R1 | `192.168.70.101` | Router |
| R2 | `192.168.70.102` | Router |
| SW4 | `192.168.70.111` | Core switch |
| SW5 | `192.168.70.112` | Access switch |
| SW3 | `192.168.70.113` | Distribution switch |

```text
          R1 ──┐
               ├── SW4 ─── SW3 ─── SW5 ─── VPC6
          R2 ──┘                     └────── VPC
```

### 3. ตั้ง IP บน Switch

Switch Layer 2 ต้องใส่ IP ที่ SVI เช่น `Vlan1` ไม่ใช่ physical port:

```text
enable
configure terminal
hostname SW4
interface Vlan1
 ip address 192.168.70.111 255.255.255.0
 no shutdown
exit
ip default-gateway 192.168.70.1
end
write memory
```

ทำซ้ำสำหรับ SW5 และ SW3 โดยเปลี่ยน hostname/IP แล้วตรวจ:

```text
show ip interface brief
```

`Vlan1` ต้องเป็น `up/up` หากเป็น `administratively down/down` ให้สั่ง `no shutdown` ที่ `interface Vlan1`

### 4. ตั้ง link และ VLAN

Link ระหว่าง Switch สองตัวต้องกำหนด trunk ทั้งสองฝั่งของสายเดียวกัน:

```text
configure terminal
interface GigabitEthernet0/3
 switchport mode trunk
 switchport trunk allowed vlan 1
 no shutdown
end
write memory
```

Port ที่ต่อ Cloud0, Router และ VPC ปกติใช้ access port ใน VLAN 1 เว้นแต่ตั้ง Router-on-a-Stick ไว้

### 5. เปิด SNMP v2c และ Trap

ตัวอย่าง IOS-like สำหรับทุก Router/Switch ที่ต้อง monitor:

```text
enable
configure terminal
snmp-server community noclab RO
snmp-server community noclab-rw RW
snmp-server host 192.168.70.1 version 2c noclab
snmp-server enable traps snmp linkdown linkup

interface GigabitEthernet0/1
 snmp trap link-status
end
write memory
```

- `noclab` ใช้อ่านข้อมูล Polling
- `noclab-rw` ใช้กับอุปกรณ์ที่อนุญาตให้หน้าเว็บสั่ง Up/Down port
- แทน `192.168.70.1` ด้วย IP Backend ที่อุปกรณ์ ping ถึงจริง
- เพิ่ม `snmp trap link-status` เฉพาะ port ที่ต้องการดูเหตุการณ์
- อย่าปิด Cloud0, management port หรือ uplink ระหว่างทดสอบ

ตัวอย่าง SNMPv3 แนว IOS-like:

```text
configure terminal
snmp-server group noclab v3 priv
snmp-server user student noclab v3 auth sha <AUTH_PASSWORD> priv aes 128 <PRIV_PASSWORD>
snmp-server host <BACKEND_IP> version 3 priv student
snmp-server enable traps snmp linkdown linkup
end
write memory
```

### 6. ตรวจสอบก่อนเพิ่มเข้าหน้าเว็บ

ตรวจจากอุปกรณ์:

```text
ping 192.168.70.1
show snmp
```

ตรวจจาก Windows โดยเปลี่ยน `<DEVICE_IP>`:

```powershell
snmpget -v2c -c noclab <DEVICE_IP> 1.3.6.1.2.1.1.5.0
snmpwalk -v2c -c noclab <DEVICE_IP> 1.3.6.1.2.1.2.2.1.2
```

### 7. เปิด Windows Firewall สำหรับ Trap

เปิด PowerShell แบบ Administrator:

```powershell
New-NetFirewallRule -DisplayName "NOC LAB SNMP Trap UDP 162" -Direction Inbound -Protocol UDP -LocalPort 162 -Action Allow
```

## การใช้งานหน้าเว็บ

### เพิ่ม Router / Switch

1. กด **เพิ่มอุปกรณ์**
2. ตั้งชื่อให้ตรง hostname ของอุปกรณ์ เช่น `SW4`, `R1`
3. ใส่ IP และเลือก SNMP version
4. v2c: ใส่ `noclab-rw` หากต้องการใช้ปุ่ม Up/Down port
5. กด **ทดสอบและเพิ่ม**

ระบบอ่าน System MIB และ Interface table ทันที ถ้าอุปกรณ์ตอบไม่ได้ ระบบจะเก็บเป็น Offline เพื่อให้แก้ IP, routing, community หรือ firewall

### ดู Port และสั่ง Up / Down

เลือก Host จาก sidebar หรือหน้า Hosts แล้วคลิก port:

- แผงกลางแสดง port ของอุปกรณ์ตาม `ifIndex`
- แผงขวาแสดงชื่อ, description, speed, admin/oper status และกราฟ traffic
- ปุ่ม **สั่ง Down interface** / **สั่ง Up interface** เรียก SNMP SET ไปที่ `ifAdminStatus`

แนะนำให้ทดสอบกับ port ที่ต่อ VPC เท่านั้น เช่น SW5 `Gi0/1`, `Gi0/2`

### Trap Events

เมื่อสายหรือ interface เปลี่ยนสถานะ อุปกรณ์ส่ง Trap มายัง Backend แล้วหน้า **SNMP traps** แสดงเวลา, device, IP, interface, event type, severity และข้อความทันที

ถ้ากด Up/Down จากหน้าเว็บแล้ว Trap ไม่ขึ้น ให้ตรวจ:

1. Backend ยังมีข้อความ `SNMP trap receiver listening on 0.0.0.0:162/udp`
2. Windows Firewall เปิด UDP/162
3. `snmp-server host` ใช้ IP Backend ที่ถูกต้อง
4. Port นั้นมี `snmp trap link-status`
5. อุปกรณ์ ping ถึง Backend

### Network map: Router / Switch

ระบบใช้ LLDP-MIB และ Cisco CDP-MIB เพื่อหาเพื่อนบ้านผ่าน SNMP ชื่อ Host ในแอปควรตรง hostname ที่อุปกรณ์ส่งออกมา

เปิด LLDP หาก image รองรับ:

```text
configure terminal
lldp run
interface range GigabitEthernet0/0 - 3
 lldp transmit
 lldp receive
end
write memory
show lldp neighbors
```

หาก IOS มี CDP อยู่แล้ว ระบบใช้ CDP ได้โดยอัตโนมัติ ตรวจด้วย:

```text
show cdp neighbors
```

จากนั้นเปิด **Network map** แล้วกด **ค้นหา link ใหม่** เส้นสีฟ้าจะแสดงสายระหว่าง Router/Switch พร้อมชื่อ port

### Network map: VPCS / PC

VPCS ไม่มี SNMP agent และไม่ประกาศ LLDP/CDP จึงค้นหาอัตโนมัติแบบ Router/Switch ไม่ได้

1. เข้า **Network map**
2. กด **เพิ่ม VPC / PC**
3. กรอกชื่อ เช่น `VPC6`
4. เลือก Switch เช่น `SW5`
5. เลือก port เช่น `Gi0/1`
6. ระบุ port ของ VPC เป็น `eth0` แล้วกดเพิ่ม

VPC จะเป็น node สีม่วง เส้นสีม่วง และจะไม่ถูกลบเมื่อกด **ค้นหา link ใหม่**

| Endpoint | Switch | Port Switch | Port Endpoint |
|---|---|---|---|
| VPC6 | SW5 | Gi0/1 | eth0 |
| VPC | SW5 | Gi0/2 | eth0 |

## ลำดับเดโมสำหรับนำเสนอ

1. เปิด Backend และ Frontend แล้วแสดง health check เป็น `ok`
2. เปิด Dashboard เพื่อโชว์ Host และสถานะ
3. เลือก SW5 แล้วเปิด Port View
4. เปิด Network map แล้วกด **ค้นหา link ใหม่**
5. เพิ่ม `VPC6` และ `VPC` ด้วยปุ่ม **เพิ่ม VPC / PC**
6. เลือก port ที่ต่อ VPC แล้วสั่ง Down ผ่านเว็บ หรือสั่ง `shutdown` ใน EVE
7. เปิด SNMP traps เพื่อแสดง `linkDown` แบบ realtime
8. สั่ง Up / `no shutdown` แล้วแสดง `linkUp`
9. กลับ Port View เพื่ออธิบาย admin/oper status และ graph traffic

## OID และ API

### OID หลัก

| รายการ | OID |
|---|---|
| sysDescr | `1.3.6.1.2.1.1.1.0` |
| sysUpTime | `1.3.6.1.2.1.1.3.0` |
| sysName | `1.3.6.1.2.1.1.5.0` |
| ifName | `1.3.6.1.2.1.31.1.1.1.1` |
| ifDescr | `1.3.6.1.2.1.2.2.1.2` |
| ifAdminStatus | `1.3.6.1.2.1.2.2.1.7` |
| ifOperStatus | `1.3.6.1.2.1.2.2.1.8` |
| ifSpeed / ifHighSpeed | `1.3.6.1.2.1.2.2.1.5` / `1.3.6.1.2.1.31.1.1.1.15` |
| ifLastChange | `1.3.6.1.2.1.2.2.1.9` |
| ifHCInOctets | `1.3.6.1.2.1.31.1.1.1.6` |
| ifHCOutOctets | `1.3.6.1.2.1.31.1.1.10` |
| linkDown Trap | `1.3.6.1.6.3.1.1.5.3` |
| linkUp Trap | `1.3.6.1.6.3.1.1.5.4` |
| LLDP remote name | `1.0.8802.1.1.2.1.4.1.1.9` |
| LLDP remote port | `1.0.8802.1.1.2.1.4.1.1.7` |
| CDP device ID | `1.3.6.1.4.1.9.9.23.1.2.1.1.6` |
| CDP device port | `1.3.6.1.4.1.9.9.23.1.2.1.1.7` |

### API หลัก

| Method | Endpoint | หน้าที่ |
|---|---|---|
| GET | `/api/health` | ตรวจ Backend และ demo mode |
| GET / POST | `/api/devices` | รายการ / เพิ่มอุปกรณ์ |
| GET / DELETE | `/api/devices/{id}` | ดู / ลบอุปกรณ์ |
| POST | `/api/devices/{id}/poll` | Poll อุปกรณ์ทันที |
| POST | `/api/devices/{id}/interfaces/{ifIndex}/admin` | SNMP SET Up/Down |
| GET | `/api/devices/{id}/interfaces/{ifIndex}/traffic?period=day` | Traffic history |
| GET | `/api/events` | Trap event log |
| GET | `/api/topology` | Device และ Link topology |
| POST | `/api/topology/discover` | Poll และหา LLDP/CDP ทันที |
| POST | `/api/topology/endpoints` | เพิ่ม VPC/PC แบบ manual |
| WS | `/ws` | Realtime device/trap/topology update |

## แก้ปัญหาที่พบบ่อย

### `node` หรือ `pnpm` ไม่พบ

ติดตั้ง Node.js แล้วปิดและเปิด PowerShell ใหม่ จากนั้นตรวจ `node --version` และ `pnpm.cmd --version`

### `pnpm.ps1 cannot be loaded`

```powershell
pnpm.cmd install
pnpm.cmd dev
```

### เปิด `localhost:5173` ไม่ได้

ตรวจว่า terminal ของ Frontend ยังเปิดอยู่และรัน `pnpm.cmd dev` สำเร็จ อย่าปิดหน้าต่างนั้น

### `Unable to connect to the remote server` ที่ `/api/health`

Backend ยังไม่ทำงาน หรือรันคนละ port ให้เปิด terminal ใน `backend` แล้วรัน Uvicorn ใหม่

### `SNMP poll failed ... No SNMP response received before timeout`

ตรวจตามลำดับ: IP ถูกต้อง, ping ถึงกัน, เปิด SNMP แล้ว, community ตรงกัน, UDP/161 ไม่ถูก firewall/ACL บล็อก และอุปกรณ์ไม่ได้ CPU สูงเกินไป

### มี `10.10.0.x` ใน log ทั้งที่ใช้ EVE-NG

เป็น record Demo เก่าที่ยังอยู่ใน SQLite ตรวจรายการก่อน:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/devices"
```

ลบเฉพาะ ID ที่ยืนยันว่าเป็น Demo:

```powershell
Invoke-RestMethod -Method Delete "http://127.0.0.1:8000/api/devices/1"
```

อย่าลบ ID ที่เป็นอุปกรณ์จริง

### Network map มีอุปกรณ์แต่ไม่มีเส้น

1. เช็ก `show cdp neighbors` หรือ `show lldp neighbors`
2. hostname ที่ส่งออกต้องตรงกับชื่อที่เพิ่มในแอป
3. กด **ค้นหา link ใหม่**
4. รีเฟรชเต็มด้วย `Ctrl + Shift + R`

### Trap ไม่ขึ้น

ตรวจ IP ใน `snmp-server host`, UDP/162 firewall, `snmp-server enable traps snmp linkdown linkup` และ `snmp trap link-status` บน port ที่ทดสอบ

### EVE Console ดำ หรือทุก Node Ping ไม่ตอบ

ดูหน้า **Status** ของ EVE-NG:

- CPU 100%: หยุด Winserver หรือ QEMU node ที่ยังไม่จำเป็น แล้วเปิดกลับทีละตัว
- Disk เกือบ 100%: อย่าเพิ่ม Node ต่อ ให้สำรอง config แล้วเพิ่มพื้นที่หรือจัดการ image/lab ที่ไม่ใช้
- Console ดำแต่ Node running: ปิด Console tab เดิม เปิดใหม่ แล้วกด Enter
- ก่อน restart/stop Node ให้ใช้ `write memory` เพื่อเก็บ config

## แนวทางอธิบายอาจารย์

1. **ปัญหา:** ผู้ดูแลต้องรู้ว่าอุปกรณ์และ port ใด up/down รวมถึง traffic
2. **Polling:** Backend ส่ง SNMP GET/WALK ไปอ่าน System MIB และ IF-MIB ทุก 30 วินาที
3. **Traffic:** ใช้ counter 64-bit หาผลต่างตามเวลา แล้วแปลงเป็น Mbps
4. **เหตุการณ์ทันที:** Link Up/Down ใช้ SNMP Trap เท่านั้นตาม requirement ไม่ใช้ polling ตัดสิน event
5. **การควบคุม:** ปุ่ม Up/Down ส่ง SNMP SET ไปที่ `ifAdminStatus` และต้องใช้ RW credential
6. **Topology:** Router/Switch ประกาศเพื่อนบ้านด้วย CDP/LLDP จึงค้นหาเส้นอัตโนมัติได้; VPCS ไม่มี protocol เหล่านี้จึงเพิ่มแบบ manual
7. **Realtime:** Backend broadcast event ผ่าน WebSocket หน้าเว็บจึงอัปเดตโดยไม่ต้อง refresh
8. **ฐานข้อมูล:** SQLite เก็บข้อมูลเวอร์ชันแรก และแยก `traffic_samples` ไว้เพื่อย้ายไป TimescaleDB/InfluxDB ภายหลังได้

## ข้อจำกัดและการต่อยอด

- SQLite และ credential แบบ plain text ใช้เพื่อการศึกษาเท่านั้น; ระบบจริงควรเข้ารหัส secrets และมี role-based access control
- ควรใช้ SNMPv3 `authPriv` นอกห้องแลบ
- ใช้ ACL จำกัด UDP/161 และ UDP/162 ให้เฉพาะ Backend/Device ที่อนุญาต
- ต่อไปเพิ่ม alert rule เช่น port down นานกว่า 5 นาที หรือ bandwidth เกิน threshold ได้
- เพิ่ม authentication, user account และ audit log ก่อนเปิดให้หลายคนใช้งาน

## คำอธิบายสำหรับ Resume

> **NOC LAB — SNMP Network Monitor**: Built a full-stack network monitoring web application using React, TypeScript, FastAPI, PySNMP, SQLite, WebSocket, and ECharts. Implemented SNMP interface polling, traffic-rate calculation, SNMP SET port control, UDP Trap Receiver for link events, and CDP/LLDP-based network topology discovery for EVE-NG labs.
