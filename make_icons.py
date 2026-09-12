"""Render our geometric Saturn mark into PNG, SVG and macOS icon assets."""
from pathlib import Path
import math
from PIL import Image, ImageDraw

ROOT = Path(__file__).parent / 'nebula_ui'


def draw_mark(size, background):
    image = Image.new('RGBA', (size, size), background)
    draw = ImageDraw.Draw(image)
    scale = size / 100
    width = round(5.5 * scale)
    def ellipse(rx, ry, angle=0):
        theta = math.radians(angle)
        points = []
        for i in range(361):
            t = math.radians(i)
            x, y = rx*math.cos(t), ry*math.sin(t)
            points.append(((50+x*math.cos(theta)-y*math.sin(theta))*scale,
                           (50+x*math.sin(theta)+y*math.cos(theta))*scale))
        draw.line(points, fill='white', width=width, joint='curve')
    ellipse(23, 23)
    ellipse(41, 12, -28)
    return image


if __name__ == '__main__':
    ROOT.mkdir(exist_ok=True)
    mark = draw_mark(1024, (0, 0, 0, 0))
    mark.resize((80, 80), Image.Resampling.LANCZOS).save(ROOT / 'menu.png')
    logo = draw_mark(1024, (0, 0, 0, 255))
    logo.save(ROOT / 'logo.png')
    logo.save(ROOT / 'Nebula.icns')
    shape = '<g fill="none" stroke="white" stroke-width="5.5"><circle cx="50" cy="50" r="23"/><ellipse cx="50" cy="50" rx="41" ry="12" transform="rotate(-28 50 50)"/></g>'
    for name, backdrop in [('logo.svg', '<rect width="100" height="100" fill="black"/>'), ('menu.svg', '')]:
        (ROOT / name).write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'+backdrop+shape+'</svg>')
