#!/usr/bin/env python3
# LOXJIE A30 control, dump, and development tool

import socket, struct, time, sys, subprocess, re, argparse
try:
    import readline
except ImportError:
    pass

SOF = 0xFF
VER = 0x01
FLAGS = 0x00
VENDOR = 0x000A

ST_OK = 0x00
ST_NOT_SUPPORTED = 0x01
ST_BAD_PARAM = 0x05
ST_BAD_STATE = 0x06

STATUS = {
    0x00: "OK", 0x01: "NOT_SUPPORTED", 0x05: "BAD_PARAM", 0x06: "BAD_STATE",
}

CMD_GET_API_VERSION = 0x0300
CMD_GET_RSSI = 0x0301
CMD_GET_BATTERY = 0x0302
CMD_GET_MODULE_ID = 0x0303
CMD_GET_APP_VERSION = 0x0304
CMD_GET_BOOT_MODE = 0x0282
CMD_GET_POWER_STATE = 0x0284
CMD_GET_EQ = 0x0294
CMD_GET_MEMORY_SLOTS = 0x0730
CMD_GET_DEFAULT_VOLUME = 0x0183
CMD_GET_AUDIO_GAIN_CONFIG = 0x018A
CMD_GET_VOLUME_CONFIG = 0x018B

CMD_SET_MUTE = 0x0201
CMD_SET_EQ = 0x0214
CMD_SET_BASS = 0x0215
CMD_SET_3D = 0x0216
CMD_SET_POWER = 0x0204
CMD_DEVICE_RESET = 0x0202
CMD_DELETE_PDL = 0x0750
CMD_SET_LED_CTRL = 0x0207
CMD_AV_REMOTE = 0x021F
CMD_SWITCH_EQ = 0x0217
CMD_TOGGLE_BASS = 0x0218
CMD_TOGGLE_3D = 0x0219
CMD_TOGGLE_USER_EQ = 0x0221
CMD_AV_PLAY = 0x44
CMD_AV_STOP = 0x45
CMD_AV_PAUSE = 0x46
CMD_AV_NEXT = 0x4B
CMD_AV_PREV = 0x4C
CMD_AV_VOLUP = 0x41
CMD_AV_VOLDOWN = 0x42
CMD_AV_MUTE = 0x43
CMD_GET_PSKEY = 0x0710
CMD_SET_PSKEY = 0x0711

LOXJIE_NAME = "LOXJIE"

AV_OPS = {"play": CMD_AV_PLAY, "stop": CMD_AV_STOP, "pause": CMD_AV_PAUSE,
          "next": CMD_AV_NEXT, "prev": CMD_AV_PREV,
          "volup": CMD_AV_VOLUP, "voldown": CMD_AV_VOLDOWN, "mute": CMD_AV_MUTE}

def make_pkt(cmd, payload=b""):
    n = len(payload)
    hdr = struct.pack(">BBBBH", SOF, VER, FLAGS, n, VENDOR) + struct.pack(">H", cmd)
    return hdr + payload

def parse_pkt(data):
    if len(data) < 8 or data[0] != SOF:
        return None
    ver, flags, plen = data[1], data[2], data[3]
    if len(data) < 8 + plen:
        return None
    vendor = struct.unpack(">H", data[4:6])[0]
    cmd = struct.unpack(">H", data[6:8])[0]
    status = data[8] if plen >= 1 else None
    payload = data[9:8 + plen] if plen >= 2 else b""
    return {"ver": ver, "flags": flags, "plen": plen, "vendor": vendor,
            "cmd": cmd, "is_ack": bool(cmd & 0x8000), "status": status, "payload": payload}

def scan_loxjie(timeout=8):
    devices = _scan_inquiry(timeout)
    if not devices:
        devices = _scan_paired()
    return devices

def _scan_inquiry(timeout):
    proc = subprocess.Popen(["bluetoothctl", "scan", "on"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
    found = {}
    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            m = re.match(r".*\[NEW\]\s+Device\s+((?:[0-9A-F]{2}:){5}[0-9A-F]{2})\s+(.*)", line)
            if m:
                found[m.group(1)] = m.group(2).strip()
    finally:
        proc.terminate()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: proc.kill(); proc.wait()
    return [(a, n) for a, n in found.items() if LOXJIE_NAME.upper() in n.upper()]

def _scan_paired():
    out = subprocess.run(["bluetoothctl", "devices", "Paired"],
        capture_output=True, text=True, timeout=5)
    devices = []
    for line in out.stdout.splitlines():
        m = re.match(r"Device\s+((?:[0-9A-F]{2}:){5}[0-9A-F]{2})\s+(.*)", line.strip())
        if m and LOXJIE_NAME.upper() in m.group(2).upper():
            devices.append((m.group(1), m.group(2)))
    return devices

class LoxError(Exception):
    pass

class LoxClient:
    def __init__(self, addr, timeout=5):
        self.addr = addr
        self.timeout = timeout
        self.sock = None
        self.channel = None

    def _find_channel(self):
        out = subprocess.run(["sdptool", "search", "--bdaddr", self.addr, "0x1101"],
            capture_output=True, text=True, timeout=10)
        m = re.search(r"Channel:\s*(\d+)", out.stdout)
        if not m:
            raise LoxError("SPP service not found (device offline?)")
        return int(m.group(1))

    def connect(self):
        self.channel = self._find_channel()
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_STREAM, socket.BTPROTO_RFCOMM)
        self.sock.settimeout(self.timeout)
        self.sock.connect((self.addr, self.channel))

    def disconnect(self):
        if self.sock:
            try: self.sock.close()
            except OSError: pass
            self.sock = None

    def send(self, cmd, payload=b""):
        if not self.sock:
            raise LoxError("not connected")
        self.sock.sendall(make_pkt(cmd, payload))
        return self._read_resp()

    def _read_resp(self):
        self.sock.settimeout(2)
        try:
            data = self.sock.recv(256)
        except socket.timeout:
            raise LoxError("timeout waiting for response")
        if not data:
            raise LoxError("connection closed by device")
        r = parse_pkt(data)
        if r is None:
            raise LoxError(f"unparseable response: {data.hex()}")
        if not r["is_ack"]:
            raise LoxError(f"unexpected non-ACK response: cmd=0x{r['cmd']:04X}")
        return r

    def read_many(self, timeout=0.5):
        self.sock.settimeout(timeout)
        buf = b""
        try:
            while True:
                chunk = self.sock.recv(256)
                if not chunk: break
                buf += chunk
        except socket.timeout:
            pass
        return buf

def cmd_api_version(gc):
    r = gc.send(CMD_GET_API_VERSION)
    return tuple(r["payload"][:3]) if r["status"] == ST_OK and len(r["payload"]) >= 3 else None

def cmd_rssi(gc):
    r = gc.send(CMD_GET_RSSI)
    return struct.unpack("b", r["payload"][:1])[0] if r["status"] == ST_OK and r["payload"] else None

def cmd_battery(gc):
    r = gc.send(CMD_GET_BATTERY)
    return struct.unpack(">H", r["payload"][:2])[0] if r["status"] == ST_OK and len(r["payload"]) >= 2 else None

def cmd_fw_version(gc):
    r = gc.send(CMD_GET_APP_VERSION)
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_boot_mode(gc):
    r = gc.send(CMD_GET_BOOT_MODE)
    return r["payload"][0] if r["status"] == ST_OK and r["payload"] else None

def cmd_power_state(gc):
    r = gc.send(CMD_GET_POWER_STATE)
    return r["payload"][0] if r["status"] == ST_OK and r["payload"] else None

def cmd_eq_preset(gc):
    r = gc.send(CMD_GET_EQ)
    return r["payload"][0] if r["status"] == ST_OK and r["payload"] else None

def cmd_module_id(gc):
    r = gc.send(CMD_GET_MODULE_ID)
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_set_mute(gc, muted):
    return gc.send(CMD_SET_MUTE, payload=bytes([1 if muted else 0]))["status"] == ST_OK

def cmd_set_eq(gc, preset):
    return gc.send(CMD_SET_EQ, payload=bytes([preset]))["status"] == ST_OK

def cmd_set_bass(gc, enable):
    return gc.send(CMD_SET_BASS, payload=bytes([1 if enable else 0]))["status"] == ST_OK

def cmd_set_3d(gc, enable):
    return gc.send(CMD_SET_3D, payload=bytes([1 if enable else 0]))["status"] == ST_OK

def cmd_set_power(gc, on):
    return gc.send(CMD_SET_POWER, payload=bytes([1 if on else 0]))["status"] == ST_OK

def cmd_device_reset(gc):
    return gc.send(CMD_DEVICE_RESET)["status"] == ST_OK

def cmd_delete_pdl(gc):
    return gc.send(CMD_DELETE_PDL)["status"] == ST_OK

def cmd_memory_slots(gc):
    r = gc.send(CMD_GET_MEMORY_SLOTS)
    if r["status"] == ST_OK and len(r["payload"]) >= 4:
        return struct.unpack(">HH", r["payload"][:4])
    return None

def cmd_default_volume(gc):
    r = gc.send(CMD_GET_DEFAULT_VOLUME)
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_audio_gain_config(gc):
    r = gc.send(CMD_GET_AUDIO_GAIN_CONFIG)
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_volume_config(gc):
    r = gc.send(CMD_GET_VOLUME_CONFIG)
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_set_led(gc, on):
    return gc.send(CMD_SET_LED_CTRL, payload=bytes([1 if on else 0]))["status"] == ST_OK

def cmd_av(gc, op):
    return gc.send(CMD_AV_REMOTE, payload=bytes([op]))["status"] == ST_OK

def cmd_switch_eq(gc):
    return gc.send(CMD_SWITCH_EQ)["status"] == ST_OK

def cmd_toggle_bass(gc):
    return gc.send(CMD_TOGGLE_BASS)["status"] == ST_OK

def cmd_toggle_3d(gc):
    return gc.send(CMD_TOGGLE_3D)["status"] == ST_OK

def cmd_toggle_user_eq(gc):
    return gc.send(CMD_TOGGLE_USER_EQ)["status"] == ST_OK

def cmd_read_pskey(gc, key_id):
    r = gc.send(CMD_GET_PSKEY, payload=struct.pack(">H", key_id))
    return r["payload"] if r["status"] == ST_OK and r["payload"] else None

def cmd_write_pskey(gc, key_id, data):
    return gc.send(CMD_SET_PSKEY, payload=struct.pack(">H", key_id) + data)["status"] == ST_OK


def dump_pskeys(gc, start=0, end=0x200, skip_empty=True):
    for kid in range(start, end):
        try:
            data = cmd_read_pskey(gc, kid)
        except LoxError:
            print(f"  PS key connection lost at {kid:#06x}, stopping.")
            break
        if data is None:
            continue
        if skip_empty and (set(data) == {0x00} or set(data) == {0xFF}):
            continue
        yield kid, data

def _exporter(mem_msg, fn, packer, gc, prefix, label):
    v = fn(gc)
    if not v: return
    data = packer(v)
    with open(f"{prefix}_{label}.bin", "wb") as f:
        f.write(data)
    msg = mem_msg(v) if mem_msg else f"({len(data)} B)"
    print(f"  {prefix}_{label}.bin  {msg}")

def export_device(gc, prefix):
    print(f"Exporting to {prefix}_* ...")
    keys = {}
    for kid, data in dump_pskeys(gc, 0, 1024, skip_empty=True):
        keys[kid] = data
        print(f"\r  {kid:#06x} ({kid / 1024 * 100:.0f}%) {len(keys)} non-empty keys found", end="")
    print()
    buf = bytearray()
    for kid in sorted(keys):
        buf += struct.pack(">HH", kid, len(keys[kid])) + keys[kid]
    with open(f"{prefix}_pskeys.bin", "wb") as f:
        f.write(buf)
    print(f"  {prefix}_pskeys.bin  ({len(keys)} PS keys, {len(buf)} B)")

    print("  Fetching device config tables ...")
    configs = [
        (lambda v: f"malloc={v[0]} PS_key_slots={v[1]}", cmd_memory_slots, lambda v: struct.pack(">HH", *v), "memslots"),
        (None, cmd_volume_config, lambda v: v, "volconfig"),
        (None, cmd_audio_gain_config, lambda v: v, "audiogain"),
        (None, cmd_default_volume, lambda v: v, "default_volume"),
        (None, cmd_fw_version, lambda v: v, "firmware_version"),
        (None, cmd_module_id, lambda v: v, "module_id"),
        (lambda v: f"{v[0]}.{v[1]}.{v[2]}", cmd_api_version, lambda v: struct.pack("BBB", *v), "api_version"),
    ]
    for mem_msg, fn, packer, label in configs:
        try: _exporter(mem_msg, fn, packer, gc, prefix, label)
        except LoxError: pass

REPL_HELP = """\
Commands:
  s <cmd> [<hex payload>]   send raw command
  r <hex>                   send raw bytes
  info                      device info
  battery                   battery mV
  rssi                      signal dBm
  eq [<preset>]             get/set EQ preset
  bass <0|1>                bass boost
  3d <0|1>                  3D enhancement
  mute <0|1>                mute off/on
  power <0|1>               power
  led <0|1>                 LED off/on
  av <op>                   AV: play,stop,pause,next,prev,volup,voldown,mute
  switch-eq                 cycle EQ preset
  toggle-bass               flip bass boost
  toggle-3d                 flip 3D
  toggle-usereq             flip user EQ
  memslots                  memory slots
  audiogain                 audio gain config table
  volconfig                 volume config table
  reset                     reboot device
  delete-pdl                wipe paired devices
  pskey <id>                read PS key
  pskey <id> <hex>          write PS key
  dump [file]               dump PS keys
  help / ?                  this message
  q / quit / exit           disconnect"""

class Repl:
    def __init__(self, gc):
        self.gc = gc

    def loop(self):
        print("loxctl repl -- type 'help' for commands, 'q' to quit")
        while True:
            try:
                line = input("lox> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            self._dispatch(line)

    def _dispatch(self, line):
        parts = line.split()
        cmd = parts[0].lower()
        gc = self.gc

        match cmd:
            case "q" | "quit" | "exit":
                raise SystemExit(0)
            case "?" | "help":
                print(REPL_HELP)
            case "info":
                print("  ", end=""); cli_info(gc)
            case "battery":
                v = cmd_battery(gc)
                print(f"  {v} mV ({v/1000:.1f} V)" if v else "  n/a")
            case "rssi":
                print(f"  {v} dBm" if (v := cmd_rssi(gc)) is not None else "  n/a")
            case "mute" if len(parts) >= 2:
                ok = cmd_set_mute(gc, parts[1] != "0"); print(f"  {'OK' if ok else 'FAIL'}")
            case "eq":
                if len(parts) >= 2:
                    ok = cmd_set_eq(gc, int(parts[1])); print(f"  set eq: {'OK' if ok else 'FAIL'}")
                else:
                    v = cmd_eq_preset(gc); print(f"  {v}" if v is not None else "  n/a")
            case "bass" if len(parts) >= 2:
                ok = cmd_set_bass(gc, parts[1] != "0"); print(f"  {'OK' if ok else 'FAIL'}")
            case "3d" if len(parts) >= 2:
                ok = cmd_set_3d(gc, parts[1] != "0"); print(f"  {'OK' if ok else 'FAIL'}")
            case "power" if len(parts) >= 2:
                ok = cmd_set_power(gc, parts[1] != "0"); print(f"  {'OK' if ok else 'FAIL'}")
            case "led" if len(parts) >= 2:
                ok = cmd_set_led(gc, parts[1] != "0"); print(f"  {'OK' if ok else 'FAIL'}")
            case "av" if len(parts) >= 2:
                op = AV_OPS.get(parts[1].lower())
                if op is None:
                    print("  bad op: play stop pause next prev volup voldown mute")
                else:
                    ok = cmd_av(gc, op); print(f"  AV: {'OK' if ok else 'FAIL'}")
            case "switch-eq":
                ok = cmd_switch_eq(gc); print(f"  switch EQ: {'OK' if ok else 'FAIL'}")
            case "toggle-bass":
                ok = cmd_toggle_bass(gc); print(f"  toggle bass: {'OK' if ok else 'FAIL'}")
            case "toggle-3d":
                ok = cmd_toggle_3d(gc); print(f"  toggle 3D: {'OK' if ok else 'FAIL'}")
            case "toggle-usereq":
                ok = cmd_toggle_user_eq(gc); print(f"  toggle user EQ: {'OK' if ok else 'FAIL'}")
            case "memslots":
                v = cmd_memory_slots(gc)
                print(f"  malloc={v[0]} PS_key_slots={v[1]}" if v else "  n/a")
            case "audiogain":
                print(f"  {d.hex()} ({len(d)} bytes)" if (d := cmd_audio_gain_config(gc)) else "  n/a")
            case "volconfig":
                print(f"  {d.hex()} ({len(d)} bytes)" if (d := cmd_volume_config(gc)) else "  n/a")
            case "reset":
                ok = cmd_device_reset(gc); print(f"  reset: {'OK' if ok else 'FAIL'}")
            case "delete-pdl":
                ok = cmd_delete_pdl(gc); print(f"  delete PDL: {'OK' if ok else 'FAIL'}")
            case "dump":
                self._dump_pskeys(parts[1] if len(parts) >= 2 else None)
            case "s" if len(parts) >= 2:
                self._send_raw(parts)
            case "r" if len(parts) >= 2:
                self._send_bytes(parts[1])
            case "pskey" if len(parts) >= 2:
                self._pskey(parts)
            case _:
                print(f"  unknown: {cmd}")

    def _send_raw(self, parts):
        try:
            cid = int(parts[1], 16)
        except ValueError:
            print("  bad hex command"); return
        pld = bytes.fromhex(parts[2]) if len(parts) >= 3 else b""
        pkt = make_pkt(cid, pld)
        print(f"  TX: {pkt.hex()}")
        self.gc.sock.sendall(pkt)
        time.sleep(0.15)
        try:
            data = self.gc.sock.recv(256)
        except socket.timeout:
            print("  RX: (timeout)"); return
        if r := parse_pkt(data):
            st = STATUS.get(r["status"], f"0x{r['status']:02X}")
            ack = "ACK" if r["is_ack"] else "NOACK"
            extra = f" payload={r['payload'].hex()}" if r["payload"] else ""
            print(f"  RX: {data.hex()}  [{ack}] cmd=0x{r['cmd']&0x7FFF:04X} st={st}{extra}")
        else:
            print(f"  RX: {data.hex()} (unparsed)")

    def _send_bytes(self, hex_str):
        try:
            raw = bytes.fromhex(hex_str)
        except ValueError:
            print("  bad hex"); return
        self.gc.sock.sendall(raw)
        time.sleep(0.1)
        if r := self.gc.read_many():
            print(f"  {r.hex()} ({len(r)} bytes)")
        else:
            print("  (no response)")

    def _pskey(self, parts):
        try:
            kid = int(parts[1], 16)
        except ValueError:
            print("  bad key id (hex)"); return
        if len(parts) >= 3:
            ok = cmd_write_pskey(self.gc, kid, bytes.fromhex(parts[2]))
            print(f"  PS key {kid:#06x} write: {'OK' if ok else 'FAIL'}")
        else:
            data = cmd_read_pskey(self.gc, kid)
            if data is None:
                print(f"  PS key {kid:#06x}: not found")
            else:
                print(f"  PS key {kid:#06x}: {data.hex()} ({len(data)} bytes)")

    def _dump_pskeys(self, fname):
        print("  Enumerating PS keys (0x000..0x1FF) ...")
        keys = {}
        for kid, data in dump_pskeys(self.gc, 0, 0x200):
            print(f"    {kid:#06x}: {data.hex()} ({len(data)} bytes)")
            keys[kid] = data
        if fname:
            with open(fname, "w") as f:
                for kid, data in sorted(keys.items()):
                    f.write(f"{kid:04x}:{data.hex()}\n")
            print(f"\n  Saved {len(keys)} keys to {fname}")
        else:
            print(f"\n  Found {len(keys)} non-empty PS keys")



def build_parser():
    p = argparse.ArgumentParser(prog="loxctl", description="LOXJIE A30 control utility")
    p.add_argument("-a", "--addr", help="BT MAC (autodetected if omitted)")
    p.add_argument("-t", "--timeout", type=int, default=5, help="connection timeout (s)")
    sub = p.add_subparsers(dest="cmd")

    for cmd, helptext in [
        ("scan", "scan for Loxjie devices"),
        ("info", "show device info and config tables"),
        ("battery", "read battery level (mV)"),
        ("rssi", "read RSSI (dBm)"),
        ("reset", "reboot device (drops connection)"),
        ("delete-pdl", "wipe paired device list"),
        ("repl", "interactive console"),
        ("memslots", "memory slot info"),
        ("audiogain", "audio gain config table"),
        ("volconfig", "volume config table"),
        ("switch-eq", "cycle EQ preset"),
        ("toggle-bass", "flip bass boost"),
        ("toggle-3d", "flip 3D enhancement"),
        ("toggle-usereq", "flip user EQ"),
    ]:
        sub.add_parser(cmd, help=helptext)

    dp = sub.add_parser("dump", help="export PS keys and config tables to files")
    dp.add_argument("output", nargs="?", help="output prefix (default: loxctl_<timestamp>)")

    for cmd, helptext, args in [
        ("mute", "mute toggle (0=off 1=on)", [("val", dict(type=int, choices=[0, 1], help="0 or 1"))]),
        ("bass", "bass boost (0=off 1=on)", [("val", dict(type=int, choices=[0, 1], help="0 or 1"))]),
        ("3d", "3D enhancement (0=off 1=on)", [("val", dict(type=int, choices=[0, 1], help="0 or 1"))]),
        ("power", "power (0=off 1=on)", [("val", dict(type=int, choices=[0, 1], help="0 or 1"))]),
        ("led", "LED off/on (0=off 1=on)", [("val", dict(type=int, choices=[0, 1], help="0 or 1"))]),
        ("av", "A/V remote", [("op", dict(choices=AV_OPS.keys(), help="play stop pause next prev volup voldown mute"))]),
    ]:
        sp = sub.add_parser(cmd, help=helptext)
        for name, kwargs in args:
            sp.add_argument(name, **kwargs)

    ep = sub.add_parser("eq", help="get/set EQ preset (0-6)")
    ep.add_argument("preset", nargs="?", type=int, help="preset number")

    pkp = sub.add_parser("pskey", help="read/write PS key")
    pkp.add_argument("key_id", help="PS key ID (hex)")
    pkp.add_argument("data", nargs="?", help="hex data to write (omit for read)")
    return p

def cli_info(gc):
    print("LOXJIE A30")
    def p(label, fn, fmt):
        v = fn(gc); print(f"  {label}: {fmt(v) if v is not None else 'n/a'}")
    p("API version", cmd_api_version, lambda v: f"{v[0]}.{v[1]}.{v[2]}")
    p("Firmware", cmd_fw_version, lambda v: v.hex())
    p("Module", cmd_module_id, lambda v: v.hex())
    p("RSSI", cmd_rssi, lambda v: f"{v} dBm")
    p("Battery", cmd_battery, lambda v: f"{v} mV ({v/1000:.1f} V)")
    p("EQ preset", cmd_eq_preset, lambda v: str(v))
    p("Boot mode", cmd_boot_mode, lambda v: str(v))
    p("Power", cmd_power_state, lambda v: "ON" if v == 1 else "OFF" if v == 0 else str(v))
    p("Memory", cmd_memory_slots, lambda v: f"malloc={v[0]} PS_key_slots={v[1]}")
    p("Default volume", cmd_default_volume, lambda v: v.hex())
    d = cmd_volume_config(gc)
    if d: print(f"  Volume config: {d.hex()} ({len(d)} B)")
    d = cmd_audio_gain_config(gc)
    if d: print(f"  Audio gain config: {d.hex()} ({len(d)} B)")


def _resolve_addr(args):
    if args.addr: return args.addr
    devices = scan_loxjie()
    if not devices:
        raise SystemExit("no Loxjie device found (is it powered on and in pairing mode?)")
    if len(devices) == 1:
        addr, name = devices[0]
        print(f"found: {addr} ({name})")
        return addr
    print("multiple Loxjie devices found:")
    for i, (addr, name) in enumerate(devices):
        print(f"  [{i}] {addr}  {name}")
    choice = input("select [0]: ").strip()
    try: idx = int(choice) if choice else 0
    except ValueError: raise SystemExit("invalid selection")
    if idx < 0 or idx >= len(devices): raise SystemExit("invalid selection")
    return devices[idx][0]

def main():
    parser = build_parser()
    args = parser.parse_args()
    if not args.cmd: print(parser.description); parser.print_help(); return
    if args.cmd == "scan":
        devices = scan_loxjie()
        if not devices: print("no Loxjie devices found"); return 0
        for addr, name in devices: print(f"  {addr}  {name}")
        return 0

    addr = _resolve_addr(args)
    gc = LoxClient(addr=addr, timeout=args.timeout)
    try: gc.connect()
    except LoxError as e: print(f"error: {e}"); return 1

    try:
        match args.cmd:
            case "info":
                cli_info(gc)
            case "dump":
                prefix = args.output or f"loxctl_{time.strftime('%Y%m%d_%H%M%S')}"
                export_device(gc, prefix)
            case "battery":
                v = cmd_battery(gc)
                print(f"{v} mV ({v/1000:.1f} V)" if v else "n/a")
            case "rssi":
                print(f"{v} dBm" if (v := cmd_rssi(gc)) is not None else "n/a")
            case "mute":
                ok = cmd_set_mute(gc, bool(args.val)); print("OK" if ok else "FAIL")
            case "eq":
                if args.preset is None:
                    v = cmd_eq_preset(gc); print(v if v is not None else "n/a")
                else:
                    ok = cmd_set_eq(gc, args.preset); print("OK" if ok else "FAIL")
            case "bass":
                ok = cmd_set_bass(gc, bool(args.val)); print("OK" if ok else "FAIL")
            case "3d":
                ok = cmd_set_3d(gc, bool(args.val)); print("OK" if ok else "FAIL")
            case "power":
                ok = cmd_set_power(gc, bool(args.val)); print("OK" if ok else "FAIL")
            case "led":
                ok = cmd_set_led(gc, bool(args.val)); print("OK" if ok else "FAIL")
            case "av":
                ok = cmd_av(gc, AV_OPS[args.op]); print("OK" if ok else "FAIL")
            case "switch-eq":
                ok = cmd_switch_eq(gc); print("OK" if ok else "FAIL")
            case "toggle-bass":
                ok = cmd_toggle_bass(gc); print("OK" if ok else "FAIL")
            case "toggle-3d":
                ok = cmd_toggle_3d(gc); print("OK" if ok else "FAIL")
            case "toggle-usereq":
                ok = cmd_toggle_user_eq(gc); print("OK" if ok else "FAIL")
            case "memslots":
                v = cmd_memory_slots(gc)
                print(f"malloc={v[0]} PS_key_slots={v[1]}" if v else "n/a")
            case "audiogain":
                print(f"{d.hex()}  ({len(d)} B)" if (d := cmd_audio_gain_config(gc)) else "n/a")
            case "volconfig":
                print(f"{d.hex()}  ({len(d)} B)" if (d := cmd_volume_config(gc)) else "n/a")
            case "reset":
                ok = cmd_device_reset(gc); print("OK" if ok else "FAIL")
            case "delete-pdl":
                ok = cmd_delete_pdl(gc); print("OK" if ok else "FAIL")
            case "pskey":
                try: kid = int(args.key_id, 16)
                except ValueError: raise SystemExit(f"bad hex key_id: {args.key_id}")
                if args.data is None:
                    data = cmd_read_pskey(gc, kid)
                    if data is None: print(f"PS key {kid:#06x}: not found")
                    else: print(f"PS key {kid:#06x}: {data.hex()} ({len(data)} bytes)")
                else:
                    ok = cmd_write_pskey(gc, kid, bytes.fromhex(args.data))
                    print(f"PS key {kid:#06x} write: {'OK' if ok else 'FAIL'}")
            case "repl":
                Repl(gc).loop()
    except LoxError as e: print(f"error: {e}"); return 1
    except KeyboardInterrupt: print()
    finally: gc.disconnect()
    return 0

if __name__ == "__main__":
    sys.exit(main())
