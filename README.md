# 🌌 Nebula

### Your music. Your lights. One atmosphere.

![macOS](https://img.shields.io/badge/macOS-14.2%2B-black?logo=apple)
![License: MIT](https://img.shields.io/badge/license-MIT-a783ff)

The next track starts. The artwork changes. Your room follows.

Nebula lives in your Mac’s menu bar and turns Spotify artwork into room-wide colour. Pick the lights that follow your music, mix supported systems, and change power, colour, or brightness without leaving your desktop. No Spotify developer account is needed.

**Made for late-night playlists, desk setups, and rooms that feel like the music playing in them.**

[Get started](#install-from-source) · [Connect your lights](#connecting-lights) · [How it works](#how-spotify-sync-works) · [Contribute](#contributing)

## What’s new in 2.0

- Control each light’s power, colour, and brightness from the menu bar.
- Add as many lights and lighting systems as you want.
- Choose exactly which lights follow Spotify.
- Connect Home Assistant, a Philips Hue Bridge, Nanoleaf, and WLED.
- Walk through a friendly first-run setup instead of editing configuration files.
- Use the new animated, accessible “cosmic glass” interface.
- Keep credentials in macOS Keychain and process Spotify screenshots only in memory.

## Install from source

Nebula requires macOS 14.2 or newer and Python 3.11 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-lock.txt
python nebula.py
```

On first launch, click the orbital icon in the menu bar. The setup guide helps connect lights and request Spotify window-capture permission.

### Install Nebula in Applications

From this folder, run:

```sh
python install.py
```

This builds `Nebula.app` and copies it to `/Applications/Nebula.app`. After installation, press **Command-Space**, type **Nebula**, and press **Return**. You can also keep Nebula in the Dock. Running `python install.py` again updates the installed app while preserving your settings and Keychain credentials.

To build `Nebula.app`:

```sh
python -m pip install pyinstaller
pyinstaller --noconfirm Nebula.spec
```

The unsigned app appears in `dist/Nebula.app`. Public distribution requires Apple signing and notarization.

## Connecting lights

| System | What you need | Connection |
| --- | --- | --- |
| Home Assistant | Server address and long-lived token | Local or remote REST API |
| Philips Hue | Bridge address; press its link button | Hue Bridge API v2, local |
| Nanoleaf | Device address; enable pairing mode | Local OpenAPI; token created in Nebula |
| WLED | Device address | Local JSON API |

Nebula’s provider interface lives in `providers.py`. New systems implement discovery plus one `set_state` method, keeping the Spotify engine independent from device-specific APIs.

### Home Assistant

1. Enter your server’s base address, such as `http://homeassistant.local:8123`.
2. Create a long-lived access token in your Home Assistant profile under Security. Paste it using **⌘V**.
3. Enter an entity ID such as `light.desk` to connect that light, or leave the field blank to discover all lights.
4. Connect, then select the lights that should follow Spotify. Entity IDs are available in Home Assistant’s entity settings.

### Philips Hue

Use a Hue Bridge on the same network as your Mac. Find its IP in the Hue app’s Bridge settings, enter it, press the physical link button, then click Connect. Nebula creates its own application key and lists the Bridge’s lights. Bluetooth-only Hue setups are not supported.

### Nanoleaf

Enter the controller’s IP; Nebula adds port 16021 automatically. Leave the token blank to pair. On Light Panels, Shapes, Canvas, Lines, or Elements, hold Power for 5–7 seconds until the LED flashes, then click Connect within 30 seconds. For Skylight, enable **Connect to API** in the Nanoleaf app first. A saved OpenAPI token can also be pasted. This adapter does not cover Essentials/Matter or USB products; each panel installation is controlled as one device.

### WLED

Enter the WLED controller’s IP or hostname, such as `http://wled.local`, and connect. No token is required. Add another connection for each controller. This version offers controller-level controls, not individual segment mapping.

### First song

Allow Spotify window capture in macOS when prompted, then open Spotify’s artwork player. Keep that window open and switch on **Follow Spotify**. Use the light selectors to decide which lights participate. Pause sync before choosing a manual colour you want to keep.

### Troubleshooting

- **Can’t paste?** The app supports standard Mac Edit shortcuts: ⌘C, ⌘V, ⌘X, and ⌘A. Restart the updated app if an older copy is still running.
- **Home Assistant cannot connect:** use the base URL without `/lovelace`, verify the token, and confirm the entity starts with `light.`.
- **Hue or Nanoleaf pairing fails:** enable pairing again and retry promptly. Your Mac and device must be able to reach each other on the network.
- **Spotify colours don’t change:** check Screen Recording permission, restart if macOS requests it, and ensure the artwork view is open.

### Current release status

Nebula is an early community release. Automated tests exercise provider requests, but they are not a substitute for testing every physical lighting model. Colour controls require colour-capable hardware. The warm return currently uses an RGB approximation. LIFX and direct Matter support are not included. Hue’s local self-signed HTTPS certificate is currently accepted without certificate verification; use it only on a trusted local network.

## How Spotify sync works

Nebula listens for Spotify playback events and captures a small image of Spotify’s own window with ScreenCaptureKit. The image stays in memory. A visual detector verifies the artwork layout, finds its dominant background colour, waits for a stable sample, and fans the colour out to all selected lights. Backup checks catch missed events.

When the artwork view closes, Nebula can restore a warm glow, apply a custom colour, or leave the last colour. Manual controls remain available even while Spotify sync is paused.

## Privacy and security


- Credentials are stored in macOS Keychain, not the repository or logs.
- Window images are analyzed in memory and never written to disk.
- Local API requests do not follow redirects, helping prevent credential forwarding.
- The embedded interface cannot navigate to external webpages.
- Logs contain status and RGB values, not screenshots or tokens.

## Tests

```sh
python -m unittest discover -v
```

The suite covers artwork detection, event scheduling, warm restoration, configuration safety, multiple-light discovery, and provider command payloads.

## Project layout

- `nebula.py` — native menu-bar shell and interface bridge
- `nebula_ui/index.html` — self-contained interface
- `providers.py` — Home Assistant, Hue, Nanoleaf, and WLED adapters
- `sync.py` — Spotify capture and multi-light colour engine
- `visual.py` — artwork validation and colour extraction
- `events.py` — Spotify event scheduling
- `window_capture.py` — private ScreenCaptureKit window capture

## Contributing

Issues, forks, branches, and pull requests are welcome. Contributors may make
their own changes in a fork or branch and submit a pull request. The upstream
`main` branch is maintained by the project owner; pull requests are reviewed
before anything is merged. Please include tests for provider or engine changes
and avoid committing real addresses, entity IDs, tokens, logs, build outputs,
or local configuration.

## References

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Philips Hue developer portal](https://developers.meethue.com/)
- [Nanoleaf OpenAPI](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/overview)
- [WLED JSON API](https://kno.wled.ge/interfaces/json-api/)
- [LIFX LAN protocol](https://lan.developer.lifx.com/) (planned provider)

## License

Nebula uses the [Nebula Source Available License](LICENSE). Personal,
non-commercial use and modification are allowed. Selling Nebula, bundling it
in a paid product or service, or commercially redistributing it requires prior
written permission from Just Verhagen.
