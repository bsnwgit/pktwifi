"""
app/wifi/rf.py
--------------
RF modelling for anything that reasons about the air rather than the
inventory: where a radio sits in the spectrum, which Wi-Fi generation a
client is speaking, and how healthy its signal is.

All of it exists to keep vendor shapes out of the API. A collector reports a
primary channel and whatever PHY string its controller uses ("ng",
"802.11ax", "11ac"); the API hands the frontend frequencies and generations
instead, so no page ever needs a channel plan or a vendor's naming scheme.
"""
from __future__ import annotations

BANDS = ("2.4GHz", "5GHz", "6GHz")


# ── Channel plans ─────────────────────────────────────────────────────────────

def channel_center_mhz(band: str, channel: int) -> int | None:
    """Centre frequency of a 20 MHz channel, or None if the band has no such channel."""
    if band == "2.4GHz":
        if channel == 14:
            return 2484
        return 2407 + 5 * channel if 1 <= channel <= 13 else None
    if band == "5GHz":
        return 5000 + 5 * channel if 32 <= channel <= 177 else None
    if band == "6GHz":
        if channel == 2:  # the one 6 GHz channel off the 5 MHz raster
            return 5935
        return 5950 + 5 * channel if 1 <= channel <= 233 else None
    return None


# Bonded 5 GHz blocks, as the lowest 20 MHz channel in each. A radio's primary
# can be any channel inside its block, so the block — not the primary — is
# what sets the span on air: an 80 MHz radio on channel 64 covers 52–64.
_5G_BLOCKS = {
    40:  (36, 44, 52, 60, 100, 108, 116, 124, 132, 140, 149, 157, 165, 173),
    80:  (36, 52, 100, 116, 132, 149, 165),
    160: (36, 100, 149),
}


def occupied_span(band: str, channel: int | None, width_mhz: int | None) -> dict | None:
    """The slice of spectrum a radio occupies, or None if it cannot be placed.

    Two flags travel with the span so a drawing can say how sure it is:
      width_reported  False when the collector sent no width and 20 MHz was
                      assumed.
      approximate     True when the channel plan cannot pin the position
                      down: 2.4 GHz at 40 MHz (no collector reports which side
                      the secondary channel is on), 6 GHz at 320 MHz (two
                      overlapping plans), or a channel/width pair the band's
                      plan does not contain.
    """
    if band not in BANDS or channel is None:
        return None
    try:
        channel = int(channel)
    except (TypeError, ValueError):
        return None
    center = channel_center_mhz(band, channel)
    if center is None:
        return None

    width = int(width_mhz) if width_mhz else 20
    lo = center - 10
    approximate = False

    if width != 20:
        n = width // 20
        if band == "2.4GHz":
            # Above for 1–7 and below from 8 keeps the pair inside the band,
            # so it is the likelier layout — but it is still a guess.
            lo = center - 10 if channel <= 7 else center + 10 - width
            approximate = True
        elif band == "5GHz":
            start = next(
                (s for s in _5G_BLOCKS.get(width, ()) if s <= channel <= s + 4 * (n - 1)),
                None,
            )
            if start is None:
                lo, approximate = center - width // 2, True
            else:
                lo = channel_center_mhz(band, start) - 10
        elif width in (40, 80, 160, 320) and channel != 2 and (channel - 1) % 4 == 0:
            # 6 GHz blocks tile the band from channel 1 in powers of two.
            index = (channel - 1) // 4
            lo = channel_center_mhz(band, 1 + 4 * (index // n * n)) - 10
            approximate = width == 320
        else:
            lo, approximate = center - width // 2, True

    return {
        "lo_mhz": lo,
        "hi_mhz": lo + width,
        "width_mhz": width,
        "width_reported": bool(width_mhz),
        "approximate": approximate,
    }


# Display range, the 20 MHz channels drawn as ticks, and which of those get a
# label regardless of how narrow the lane is drawn.
_AXES = {
    "2.4GHz": (2400, 2495, list(range(1, 15)), (1, 6, 11)),
    "5GHz":   (5150, 5895, [*range(36, 65, 4), *range(100, 145, 4), *range(149, 178, 4)],
               (36, 52, 64, 100, 116, 132, 149, 165)),
    "6GHz":   (5925, 7125, list(range(1, 234, 4)), (1, 33, 65, 97, 129, 161, 193, 225)),
}


def band_axis(band: str) -> dict | None:
    """Frequency range and channel ticks for one band's spectrum lane."""
    if band not in _AXES:
        return None
    lo, hi, channels, labelled = _AXES[band]
    return {
        "band": band,
        "lo_mhz": lo,
        "hi_mhz": hi,
        "ticks": [
            {"channel": ch, "mhz": channel_center_mhz(band, ch), "major": ch in labelled}
            for ch in channels
        ],
    }


# ── Wi-Fi generations ─────────────────────────────────────────────────────────
# Controllers name a client's PHY in their own dialect: UniFi sends "ng"/"na"
# for 802.11n on 2.4/5 GHz, others "802.11ax" or "11ac". Grouping by generation
# answers the question this field is actually asked — how much of the estate
# is talking to current hardware.

def wifi_generation(protocol: str | None) -> str:
    if not protocol:
        return "Unknown"
    p = str(protocol).strip().lower().replace("802.11", "").replace(" ", "")
    if p.startswith("11"):
        p = p[2:]
    for marker, label in (("be", "Wi-Fi 7"), ("ax", "Wi-Fi 6"), ("ac", "Wi-Fi 5")):
        if marker in p:
            return label
    if p in ("n", "ng", "na"):
        return "Wi-Fi 4"
    if p in ("a", "b", "g"):
        return "Legacy"
    return "Other"


# ── Client signal ─────────────────────────────────────────────────────────────
# The same cut-offs the Client Signal Health widget uses, so the Dashboard and
# a NOC wall never disagree about which clients are struggling.
SIGNAL_GOOD_DBM = -65
SIGNAL_FAIR_DBM = -75


def signal_class(rssi_dbm: float) -> str:
    if rssi_dbm >= SIGNAL_GOOD_DBM:
        return "good"
    if rssi_dbm >= SIGNAL_FAIR_DBM:
        return "fair"
    return "poor"
