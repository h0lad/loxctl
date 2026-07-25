# LOXJIE A30 Remote Control over Bluetooth

```
$ python3 loxctl.py 
usage: loxctl [-h] [-a ADDR] [-t TIMEOUT] {scan,info,dump,battery,rssi,mute,eq,bass,3d,power,reset,delete-pdl,pskey,repl,memslots,audiogain,volconfig,led,av,switch-eq,toggle-bass,toggle-3d,toggle-usereq} ...

LOXJIE A30 control, dump, and development tool

positional arguments:
  {scan,info,dump,battery,rssi,mute,eq,bass,3d,power,reset,delete-pdl,pskey,repl,memslots,audiogain,volconfig,led,av,switch-eq,toggle-bass,toggle-3d,toggle-usereq}
    scan                scan for Loxjie devices
    info                show device info
    dump                dump PS keys and config to files
    battery             read battery level (mV)
    rssi                read RSSI (dBm)
    mute                mute toggle (0=off 1=on)
    eq                  get/set EQ preset (0-6)
    bass                bass boost (0=off 1=on)
    3d                  3D enhancement (0=off 1=on)
    power               power (0=off 1=on)
    reset               reboot device (drops connection)
    delete-pdl          wipe paired device list
    pskey               read/write PS key
    repl                interactive console
    memslots            memory slot info
    audiogain           audio gain config table
    volconfig           volume config table
    led                 LED off/on (0=off 1=on)
    av                  A/V remote (play stop pause next prev volup voldown mute)
    switch-eq           cycle EQ preset
    toggle-bass         flip bass boost
    toggle-3d           flip 3D enhancement
    toggle-usereq       flip user EQ

options:
  -h, --help            show this help message and exit
  -a, --addr ADDR       BT MAC (autodetected if omitted)
  -t, --timeout TIMEOUT
                        connection timeout (s)
```

## Example

```
$ loxctl info
found: E8:18:28:xx:xx:xx (LOXJIE BT5.0B)
LOXJIE A30
  API version: 1.2.5
  Firmware: 0001000affffffffffffffffffffffff
  Module: 0000000000000000
  RSSI: -47 dBm
  Battery: 3310 mV (3.3 V)
  EQ preset: 1
  Boot mode: 0
  Power: ON
  Memory: malloc=145 PS_key_slots=2262
  Default volume: 080a09
  Volume config: 00100004000affd8fff60000ffb000100004000affd8fff60000ffb00000000000000000000000000009350119030f18000935043513190600010009351f190907000009091cffff00093505 (76 B)
  Audio gain config: 0100000000020004000103010400020402040003050304000406040400050705040006080604000709070400080a080400090b0904000a0c0a04000b0d0b04000c0e0c04000d0f0d04000e0f0e00000f (80 B)
```
