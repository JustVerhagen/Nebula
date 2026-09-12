# Nebula

Nebula is a private, open-source macOS menu-bar app that turns Spotify artwork into room-wide colour. It also gives you a fast, independent control panel for every connected light—no Home Assistant dashboard required.

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
| Nanoleaf | Device address and OpenAPI token | Local REST API |
| WLED | Device address | Local JSON API |

Nebula’s provider interface lives in `providers.py`. New systems implement discovery plus one `set_state` method, keeping the Spotify engine independent from device-specific APIs.

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

Issues and pull requests are welcome. Please include tests for provider or engine changes and avoid committing real addresses, entity IDs, tokens, logs, build outputs, or local configuration.

## References

- [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/)
- [Philips Hue developer portal](https://developers.meethue.com/)
- [Nanoleaf OpenAPI](https://nanoleaf.atlassian.net/wiki/spaces/nlapid/overview)
- [WLED JSON API](https://kno.wled.ge/interfaces/json-api/)
- [LIFX LAN protocol](https://lan.developer.lifx.com/) (planned provider)

## License

MIT. See [LICENSE](LICENSE).
