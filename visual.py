"""Recognise Spotify's artwork player from a small, in-memory window image.

No macOS full-screen flag, hidden UI button labels, OCR, or cloud requests.
The deliberately conservative check accepts smooth, uneven surrounding backgrounds
and a roughly square cover near the centre. Ambiguous layouts are skipped.
"""
from collections import Counter
import colorsys
import math
import statistics


def distance(a, b):
    return math.sqrt(sum((x-y)**2 for x, y in zip(a, b)))


def median(pixels):
    return tuple(round(statistics.median(c)) for c in zip(*pixels))


def dominant_color(samples):
    """Choose the largest nearby colour family, ignoring isolated accents/text."""
    bins = Counter(tuple(c // 24 for c in color) for color in samples)
    centre = median(samples)
    seeds = [tuple(c*24+12 for c in key) for key in bins]
    groups = [[color for color in samples if distance(color, seed) <= 42] for seed in seeds]
    cluster = max(groups, key=lambda group: (len(group), -distance(median(group), centre)) if group else (0, 0))
    rgb = median(cluster or samples)
    hue, saturation, value = colorsys.rgb_to_hsv(*(c/255 for c in rgb))
    # Preserve already-muted backgrounds; gently soften very vivid colours.
    return tuple(round(c*255) for c in colorsys.hsv_to_rgb(hue, min(saturation, .75), value))


def inspect_artwork(image):
    image = image.convert('RGB')
    image.thumbnail((320, 240))
    w, h = image.size
    if w < 100 or h < 65:
        return None, 'Spotify window is too small'
    pixels = image.load()
    # Sample away from the artwork and controls. Colours may vary widely;
    # only local texture (text, lists, panels) counts against this layout.
    points = [(round(w*x), round(h*y))
              for x in (.04, .08, .12, .88, .92, .96)
              for y in (.18, .24, .30, .36, .42, .48, .54, .60, .66)]
    samples = [pixels[x, y] for x, y in points]
    smooth = sum(max(distance(pixels[x, y], pixels[x+dx, y+dy])
                     for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1))) <= 18
                 for x, y in points)
    if smooth / len(points) < .85:
        return None, 'Waiting for artwork mode: surrounding area contains too much interface detail'
    background = dominant_color(samples)
    # Find substantial artwork, excluding bottom track text/player controls.
    # Estimate each row's background from BOTH sides. This removes vertical
    # and horizontal gradients before looking for the square cover.
    rows_to_scan = range(round(h*.12), round(h*.82))
    row_edges = {y: (median([pixels[round(w*x), y] for x in (.04, .08, .12)]),
                     median([pixels[round(w*x), y] for x in (.88, .92, .96)]))
                 for y in rows_to_scan}
    marked = []
    for y in rows_to_scan:
        left_bg, right_bg = row_edges[y]
        for x in range(round(w*.16), round(w*.84)):
            mix = min(1, max(0, (x/w-.08)/.84))
            expected = tuple(a+(b-a)*mix for a, b in zip(left_bg, right_bg))
            if distance(pixels[x, y], expected) > 30:
                marked.append((x, y))
    if len(marked) < w*h*.025:
        return None, 'Waiting for artwork mode: no distinct album cover found'
    # Ignore isolated pixels, cursor edges and faint shadows when finding bounds.
    columns = {}
    rows = {}
    for x, y in marked:
        columns[x] = columns.get(x, 0) + 1
        rows[y] = rows.get(y, 0) + 1
    xs = [x for x, count in columns.items() if count >= h*.09]
    ys = [y for y, count in rows.items() if count >= w*.035]
    if not xs or not ys:
        return None, 'Waiting for artwork mode: album cover is unclear'
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    cover_w, cover_h = right-left+1, bottom-top+1
    square = .78 <= cover_w/cover_h <= 1.24
    centered = abs((left+right)/2-w/2) <= w*.07
    substantial = cover_h >= h*.24 and cover_w >= w*.10
    if not (square and centered and substantial):
        return None, 'Waiting for artwork mode: centred square cover not found'
    return background, 'Artwork mode detected'
