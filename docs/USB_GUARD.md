# USB guard (`usb-guard`)

A USB stick or cable can pretend to be a keyboard and type commands in a second ("BadUSB"). With USB guard, only USB devices
you know work; anything new stays blocked until you say so, from a notification:
**Allow once** · **Always allow** · **Keep blocked**. If a gadget claims to be a keyboard *and* something else (storage,
network), the notification warns you.

## Turn it on (be at the laptop)
1. Plug in everything you use regularly (mouse/keyboard receiver, phone cable, Pi/MCU probes…).
2. `! bash scripts/phase16-usbguard.sh`: installs USBGuard, allows exactly what's plugged in now (in any port), blocks
   everything else, and starts the notifier.
3. Unplug and replug the mouse receiver: it should keep working. Plug in something new: you're asked.

The laptop's **built-in keyboard and touchpad aren't USB** (AT keyboard, I2C touchpad), so they work whatever USB guard does.
Internal USB devices (camera, Bluetooth) are allowed by the generated policy.

## Commands
`usb-guard` (every device and whether it's allowed) · `usb-guard allow ID [--always]` · `usb-guard block ID`.

## Recovery
- Something you need is blocked: `usb-guard` to find its ID, then `usb-guard allow ID --always`.
- Turn it off now: `sudo systemctl stop usbguard` (every device works again; it comes back at the next boot).
- Turn it off for good: `sudo systemctl disable --now usbguard`.
- Can't log in at all (very unlikely: the built-in keyboard isn't USB): at the boot menu press `e`, add
  `systemd.mask=usbguard.service` to the `linux` line, boot with Ctrl+X, then disable it as above.
