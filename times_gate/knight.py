"""Daylight's resting knight: a shaded knight under a tree in a gentle, exactly periodic summer breeze.

Drawn together with Codex. All marks are drawn at native 128px resolution; no file or reference input.
"""
from functools import lru_cache
import math
import random
from PIL import Image, ImageDraw
from .pixel import (
    INK, NAVY, SLATE, STEEL, FOG, MIST, SNOW, LEMON, AMBER,
    EMBER, RUST, WOOD, BARK, CLAY, CREAM, PINE, FOREST,
    SKY, LEAF, GRASS,
)

N = 16


def _plate(d, points, fill=STEEL):
    d.polygon(points, fill=fill)
    d.line(points + [points[0]], fill=INK, width=1)


def _pine(d, x, base, h, light, dark):
    d.line((x, base-h, x, base), fill=dark)
    for j in range(4):
        y = base-h + j*h//5
        w = 2+j*h//12
        d.polygon([(x, y), (x-w, y+h//3), (x+w, y+h//3)], fill=light)
        d.line((x+1, y+3, x+w, y+h//3), fill=dark)
        if h > 20:
            d.line((x-w+2, y+h//3-1, x-1, y+h//3-1), fill=light)


def _background():
    im = Image.new('RGB', (128, 128), SKY)
    d = ImageDraw.Draw(im)
    # Separate cloud banks, stepped into puffs rather than a dither stripe.
    for x,y,r in [(100,25,10),(113,22,10),(122,31,12),(94,36,8),(108,35,12)]:
        d.ellipse((x-r,y-r,x+r,y+r), fill=MIST)
    for x,y,r in [(102,22,9),(112,20,9),(120,28,10),(97,32,7),(109,31,9)]:
        d.ellipse((x-r,y-r,x+r,y+r), fill=CREAM)
    d.rectangle((91,38,127,41), fill=CREAM)
    d.line((96,42,127,42), fill=MIST)
    d.polygon([(92,32),(95,29),(97,30),(96,34),(102,35),(106,33),(109,35),(106,38),(98,38),(95,36),(91,36)],fill=MIST)
    d.polygon([(115,30),(118,28),(120,30),(119,33),(124,35),(127,35),(127,39),(121,39),(119,36),(114,35)],fill=MIST)
    d.line([(101,16),(105,14),(111,14),(114,16)],fill=SNOW)
    d.line([(119,23),(123,25),(124,28)],fill=SNOW)
    for x,y,r in [(62,44,5),(71,43,7),(79,46,4)]:
        d.ellipse((x-r,y-r//2,x+r,y+r//2), fill=CREAM)
    d.line((57,48,84,48), fill=MIST)
    d.polygon([(26,64),(49,60),(66,64),(84,58),(106,61),(127,56),(127,86),(26,86)], fill=MIST)
    for x,h in [(36,12),(45,18),(55,13),(64,18),(75,15),(86,23),(98,16),(109,20),(121,25)]:
        _pine(d,x,78,h,FOG,MIST)
    d.polygon([(26,83),(56,78),(79,81),(105,76),(127,70),(127,103),(26,103)], fill=GRASS)
    for x,b,h in [(57,85,23),(73,88,27),(88,87,21),(111,83,29),(125,82,36)]:
        _pine(d,x,b,h,FOREST,PINE)
    for x,b,h in [(71,84,23),(108,81,25),(123,79,33)]:
        _pine(d,x,b,h,GRASS,FOREST)
    d.polygon([(0,93),(22,90),(46,92),(67,88),(92,91),(111,85),(127,81),(127,127),(0,127)], fill=LEAF)
    d.polygon([(0,99),(23,96),(46,100),(66,105),(89,111),(127,106),(127,127),(0,127)], fill=GRASS)
    d.polygon([(0,101),(25,93),(45,96),(73,111),(90,115),(80,122),(41,117),(0,119)], fill=FOREST)
    # Ground flecks follow shade and sunlight, with no continuous dither seam.
    rng = random.Random(62)
    for _ in range(560):
        x,y = rng.randrange(128),rng.randrange(87,128)
        if y < 94 and x < 65:
            continue
        c = rng.choice((GRASS, LEAF, LEAF)) if x > 83 or y < 100 else rng.choice((FOREST,GRASS,GRASS))
        d.line((x,y,x+1,y),fill=c)
    for _ in range(68):
        x,y = rng.randrange(37,128),rng.randrange(89,110)
        if x > 88 or y < 98:
            d.point((x,y),LEMON)
    # Trunk is sheltered on the left and warms on the right edge.
    d.polygon([(0,0),(22,0),(18,28),(21,48),(24,71),(27,92),(40,99),(28,103),(12,100),(0,106)],fill=BARK)
    d.polygon([(9,0),(22,0),(18,27),(21,49),(23,76),(27,95),(33,99),(20,97),(15,76),(14,48),(10,29)],fill=WOOD)
    d.polygon([(16,20),(18,22),(17,38),(20,55),(20,75),(24,93),(21,92),(16,72),(16,49),(13,33)],fill=CLAY)
    for pts in [[(6,21),(8,37),(5,51),(8,70),(6,88)],[(12,48),(10,61),(13,77),(12,93)],[(20,58),(19,69),(22,82)],[(6,96),(16,94),(26,98),(33,100)]]:
        d.line(pts,fill=BARK,width=2)
    for x,y in [(17,41),(18,54),(19,63),(20,77),(22,88),(24,94)]:
        d.line((x,y,x+1,y+3),fill=CLAY)
        d.point((x-2,y+4),fill=BARK)
    d.line([(3,73),(7,69),(10,72),(9,77),(5,79),(3,75)],fill=WOOD)
    d.polygon([(8,29),(24,15),(42,8),(62,10),(79,17),(70,17),(56,13),(41,14),(29,22),(15,36)],fill=BARK)
    d.line([(15,25),(32,14),(44,11),(59,12),(72,16)],fill=WOOD,width=3)
    d.line([(36,14),(46,24),(59,27)],fill=WOOD,width=2)
    # Canopy uses angular clusters; inner shade stays steady.
    rng = random.Random(11)
    for _ in range(130):
        x,y = rng.randrange(-9,88),rng.randrange(-8,18)
        if x > 70 and y > 12:
            continue
        r = rng.randrange(2,7)
        c = rng.choice((PINE,FOREST,FOREST,GRASS)) if x<43 else rng.choice((FOREST,GRASS,GRASS,LEAF))
        d.polygon([(x-r,y),(x-r+1,y-r),(x+2,y-r),(x+r,y-1),(x+r-1,y+3),(x,y+r),(x-r,y+2)],fill=c)
    for _ in range(95):
        x,y = rng.randrange(9,87),rng.randrange(0,17)
        d.line((x,y,x+1,y),fill=LEAF if x>46 else GRASS)
    for _ in range(100):
        x,y=rng.randrange(0,83),rng.randrange(0,20)
        if im.getpixel((x,y)) in (tuple(bytes.fromhex(SKY[1:])),tuple(bytes.fromhex(BARK[1:])),tuple(bytes.fromhex(WOOD[1:]))):
            continue
        c=FOREST if x<40 else GRASS
        d.line((x,y,x+2,y),fill=c)
        d.point((x,y+1),fill=PINE if x<35 else FOREST)
    for x,y in [(9,22),(17,21),(25,17),(31,19),(47,19),(58,20),(67,22),(78,19)]:
        d.line((x,y-2,x,y+3),fill=FOREST)
        d.line((x,y,x+2,y),fill=GRASS)
    for x in range(1,28,3):
        y=100+(x%5)
        d.line((x,y,x+1,y-5-x%4),fill=GRASS)
        d.point((x+1,y-5-x%4),fill=LEAF)
    return im


def _knight(d, phase):
    # Far thigh rises to an independent knee; shin drops to the right.
    _plate(d,[(44,83),(49,76),(60,66),(67,67),(69,74),(57,85),(50,91)],SLATE)
    d.polygon([(50,78),(61,68),(64,69),(63,75),(54,84),(49,86)],fill=STEEL)
    d.line([(53,76),(60,70),(63,69)],fill=FOG)
    _plate(d,[(66,73),(74,72),(79,88),(83,97),(87,103),(83,107),(74,98),(69,86)],STEEL)
    d.polygon([(69,76),(72,75),(78,88),(82,98),(85,103),(82,103),(75,95)],fill=FOG)
    d.line([(71,79),(75,90),(80,100)],fill=MIST)
    d.line([(74,78),(78,89),(82,98)],fill=SLATE)
    d.line([(81,102),(84,101),(87,104)],fill=INK)
    d.line([(81,103),(84,102),(86,104)],fill=MIST)
    _plate(d,[(81,104),(87,103),(89,107),(97,110),(96,112),(83,111)],SLATE)
    d.polygon([(84,104),(87,105),(89,108),(94,110),(86,109)],fill=FOG)
    for x,y in [(86,107),(89,109),(92,110)]:
        d.line((x,y,x-1,y+2),fill=STEEL)
    # Near thigh, broad knee cap, tapered greave, segmented sabaton.
    _plate(d,[(39,82),(49,81),(58,87),(60,94),(52,97),(42,91)],STEEL)
    d.polygon([(42,84),(49,84),(57,90),(56,93),(49,91)],fill=FOG)
    d.line([(43,84),(48,84),(55,88)],fill=MIST)
    _plate(d,[(51,91),(55,89),(61,92),(64,97),(61,101),(55,100),(51,96)],FOG)
    d.polygon([(55,94),(60,94),(62,97),(59,99),(55,97)],fill=STEEL)
    d.line((53,93,57,91),fill=MIST)
    _plate(d,[(56,100),(63,97),(69,105),(75,111),(72,115),(63,110)],STEEL)
    d.polygon([(59,100),(63,100),(69,107),(72,111),(69,112),(63,107)],fill=FOG)
    d.line([(60,100),(63,102),(68,108)],fill=MIST)
    d.line([(68,112),(72,110),(74,112)],fill=INK)
    d.line([(69,113),(72,112),(74,113)],fill=MIST)
    _plate(d,[(70,112),(75,110),(78,114),(85,117),(83,119),(73,118),(69,115)],SLATE)
    d.polygon([(73,112),(75,112),(78,115),(83,117),(75,116)],fill=FOG)
    for x,y in [(75,114),(78,115),(81,117)]:
        d.line((x,y,x-1,y+2),fill=STEEL)
    # Cloth and plate skirt conceal hip joins and give the seated body weight.
    _plate(d,[(32,75),(49,74),(56,82),(51,88),(37,87),(31,83)],NAVY)
    _plate(d,[(33,76),(49,76),(51,80),(35,81)],STEEL)
    _plate(d,[(35,81),(51,80),(53,84),(37,85)],SLATE)
    d.line((36,82,48,81),fill=FOG)
    # A reclined, curved breastplate, dark underside and broad reflected light.
    _plate(d,[(31,58),(43,57),(50,62),(52,72),(48,79),(36,80),(30,73),(28,64)],STEEL)
    d.polygon([(33,59),(41,59),(47,63),(47,68),(43,73),(36,74),(32,70),(31,65)],fill=FOG)
    d.line([(33,61),(38,60),(43,61),(46,64)],fill=MIST,width=2)
    d.line([(35,63),(35,66),(37,68)],fill=MIST)
    d.polygon([(48,63),(50,66),(50,72),(46,77),(37,78),(34,75),(43,75),(47,71)],fill=SLATE)
    d.line([(34,76),(38,78),(45,77)],fill=FOG)
    d.line((34,79,48,78),fill=BARK,width=2)
    d.rectangle((42,78,44,79),fill=AMBER)
    # Far shoulder and forearm behind the conspicuous near arm.
    _plate(d,[(45,57),(50,59),(53,65),(50,69),(46,66)],SLATE)
    d.line((48,59,51,63),fill=FOG)
    _plate(d,[(50,64),(54,64),(61,68),(61,72),(55,72),(51,69)],STEEL)
    d.line((53,65,59,68),fill=FOG)
    # Near pauldron: dome and two overlapping lames.
    _plate(d,[(24,61),(26,57),(31,55),(36,56),(41,60),(41,66),(36,69),(27,67)],STEEL)
    d.polygon([(26,60),(29,57),(33,57),(37,59),(39,62),(33,61),(28,63)],fill=MIST)
    d.polygon([(25,63),(31,63),(38,65),(39,67),(33,67),(26,65)],fill=FOG)
    d.line([(25,66),(32,68),(39,67)],fill=INK)
    d.line([(26,68),(32,70),(37,69)],fill=FOG)
    d.line((28,58,31,57),fill=SNOW)
    d.point((26,64),fill=MIST)
    d.point((37,65),fill=MIST)
    _plate(d,[(27,69),(35,70),(37,76),(33,80),(27,77)],SLATE)
    d.polygon([(28,70),(32,71),(33,76),(29,76)],fill=FOG)
    _plate(d,[(29,76),(33,74),(37,77),(37,81),(32,83),(28,80)],STEEL)
    d.line((30,77,33,76),fill=MIST)
    _plate(d,[(34,77),(38,74),(55,69),(59,70),(59,74),(41,81),(36,81)],STEEL)
    d.polygon([(38,76),(43,74),(54,71),(55,73),(42,78),(38,79)],fill=FOG)
    d.line((39,75,52,71),fill=MIST)
    for x,y in ((40,75),(44,74)):
        d.line((x,y,x+1,y+4),fill=SLATE)
    # Knee is visible below the resting hand.
    _plate(d,[(62,65),(67,64),(71,67),(73,72),(70,77),(65,78),(61,74),(60,69)],STEEL)
    d.polygon([(63,67),(67,66),(70,68),(71,71),(65,71),(62,70)],fill=FOG)
    d.line((63,67,67,66),fill=MIST)
    d.line([(63,75),(67,76),(70,74)],fill=SLATE)
    _plate(d,[(55,70),(59,68),(65,68),(68,70),(67,73),(62,74),(57,74),(55,73)],FOG)
    d.line((58,69,63,69),fill=MIST)
    for x in (61,64,66):
        d.line((x,71,x,73),fill=STEEL)
    # Gorget and dark neck gap detach the helm from the shoulder.
    _plate(d,[(33,53),(46,54),(48,58),(41,61),(33,59)],SLATE)
    d.line([(34,57),(41,59),(46,57)],fill=MIST)
    # Helmet dome and brow; visor projects forward and narrows at the chin.
    _plate(d,[(32,48),(32,43),(34,39),(39,36),(45,37),(49,41),(50,46),(46,54),(37,55)],STEEL)
    d.polygon([(34,44),(35,40),(40,38),(44,39),(47,42),(47,44),(39,43)],fill=FOG)
    d.line([(35,42),(37,40),(41,39),(44,40)],fill=MIST)
    d.polygon([(33,46),(37,45),(38,53),(34,52)],fill=SLATE)
    _plate(d,[(39,44),(54,44),(55,46),(52,53),(47,57),(40,54)],SLATE)
    d.line((40,44,53,44),fill=MIST)
    d.line((41,46,53,46),fill=INK)
    d.polygon([(41,48),(53,48),(50,53),(47,55),(41,53)],fill=FOG)
    for x in (43,46,49,52):
        d.line((x,49,x-1,52),fill=NAVY)
    d.line((42,54,47,56),fill=STEEL)
    d.rectangle((36,46,38,49),fill=INK)
    d.point((37,47),fill=MIST)
    # Only the free plume tips bend; the helmet attachment stays fixed.
    a = round(math.sin(phase))
    b = round(2*math.sin(phase-.6))
    c = round(2*math.sin(phase-1.2))
    pts = [(41,37),(38,32),(32,28+a),(27,28+b),(22,30+c),(19,34+c),(18,37+c),(21,36+c),(20,39+c),(24,37+b),(26,34+b),(31,33+a),(36,35),(39,38)]
    d.polygon(pts,fill=RUST)
    d.line(pts+[pts[0]],fill=INK)
    d.polygon([(39,35),(34,30+a),(28,29+b),(24,31+c),(21,35+c),(24,35+b),(28,32+b),(33,32+a),(38,36)],fill=EMBER)
    d.line([(26,29+b),(30,29+a),(35,31),(38,34)],fill=AMBER)


def _sword(d):
    _plate(d,[(99,62),(103,62),(103,107),(101,110),(99,107)],FOG)
    d.line((100,64,100,106),fill=MIST)
    d.line((102,64,102,105),fill=STEEL)
    d.rectangle((99,54,103,62),fill=INK)
    d.rectangle((100,54,102,61),fill=WOOD)
    for y in (56,59):
        d.line((100,y,102,y),fill=CLAY)
    _plate(d,[(92,61),(95,62),(107,62),(110,61),(110,64),(105,65),(96,65),(92,64)],WOOD)
    d.line((95,62,107,62),fill=CLAY)
    d.ellipse((98,50,104,55),fill=INK)
    d.rectangle((100,51,102,54),fill=WOOD)
    d.point((100,51),fill=CLAY)


@lru_cache(maxsize=1)
def knight_frames():
    """Return 16 independent RGB PIL frames, 140ms each (~2.24s loop)."""
    base = _background()
    rng = random.Random(33)
    blades = [(rng.randrange(128),rng.randrange(96,130),rng.randrange(3,9),rng.random()*math.tau) for _ in range(200)]
    blades.sort(key=lambda b:b[1])
    edge = [(rng.randrange(14,90),rng.randrange(13,24),rng.random()*math.tau) for _ in range(45)]
    frames = []
    for f in range(N):
        phase = math.tau*f/N
        im = base.copy()
        d = ImageDraw.Draw(im)
        for x,y,p in edge:
            dx = round(math.sin(phase+p))
            d.line((x+dx,y,x+dx+1,y+2),fill=GRASS if x<50 else LEAF)
            if x>54:
                d.point((x+dx,y),fill=LEMON)
        # Backlit tufts behind the legs, leaving the chest silhouette quiet.
        for x in range(30,128,3):
            y = 94 if x<84 else 100
            lean = round(math.sin(phase-x/13))
            d.line((x,y,x+lean+1,y-4-(x%4)),fill=LEAF)
            if x%9==0:
                d.point((x+lean+1,y-4-(x%4)),fill=LEMON)
        _sword(d)
        _knight(d,phase)
        # Front grass is sparse over the metal, dense around its ground contacts.
        for x,y,h,p in blades:
            if 29<x<96 and y<119:
                continue
            lean = round(1+math.sin(phase-x/15+p*.2))
            c = LEAF if x>85 or (x+y)%3==0 else GRASS
            d.line((x,y,x+lean,y-h),fill=c)
            if (x+y)%7==0:
                d.point((x+lean,y-h),fill=LEMON if x>85 else LEAF)
        for x,y in [(11,115),(23,108),(46,123),(111,115),(119,103)]:
            dx = round(math.sin(phase-x/15))
            d.line((x,y,x+dx,y-5),fill=FOREST)
            fx,fy=x+dx,y-6
            for ox,oy in [(-1,0),(1,0),(0,-1),(0,1)]:
                d.point((fx+ox,fy+oy),fill=CREAM)
            d.point((fx,fy),fill=AMBER)
        # Three slowly suspended loose leaves on closed breeze paths.
        for x,y,p in [(79,29,.2),(114,52,2.5),(14,82,4.3)]:
            lx=x+round(5*math.sin(phase+p))
            ly=y+round(3*math.cos(phase+p))
            d.line((lx,ly,lx+1,ly+round(math.sin(phase+p))),fill=LEAF)
        im.info['duration']=140
        frames.append(im)
    return frames
