"""Build the ArchUpdater empty-state illustration scenes in Blender.

Creates three looping 90-frame scenes (AU_Pronto, AU_Controllo, AU_Rete) and the
still "up to date" scene (AU_Aggiornato). Run through render_illustrations.py, or
exec() it inside Blender and call build_all().
All animation uses simple driver expressions, so it works without enabling
Python auto-execution.
"""
import math

import bmesh
import bpy
from mathutils import Vector

FRAMES = 90
R = 14.0  # planet radius


# ---------------------------------------------------------------- helpers
def new_scene(name, exposure):
    if name in bpy.data.scenes:
        bpy.data.scenes.remove(bpy.data.scenes[name])
    sc = bpy.data.scenes.new(name)
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'GPU'
    sc.cycles.samples = 96
    sc.cycles.use_denoising = True
    sc.render.resolution_x = sc.render.resolution_y = 440
    sc.render.fps = 30
    sc.frame_start, sc.frame_end = 1, FRAMES
    sc.view_settings.view_transform = 'AgX'
    sc.view_settings.look = 'AgX - Punchy'
    sc.view_settings.exposure = exposure
    sc.render.image_settings.file_format = 'PNG'
    col = bpy.data.collections.new(f"{name}_Objects")
    sc.collection.children.link(col)
    return sc, col


def drive(idb, path, expr, index=-1):
    fc = idb.driver_add(path, index) if index >= 0 else idb.driver_add(path)
    fc.driver.type = 'SCRIPTED'
    fc.driver.expression = expr
    return fc


def principled(name, color, rough=0.35, metal=0.0, coat=0.0, emission=None, estr=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    p = m.node_tree.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (*color, 1)
    p.inputs["Roughness"].default_value = rough
    p.inputs["Metallic"].default_value = metal
    p.inputs["Coat Weight"].default_value = coat
    if emission:
        p.inputs["Emission Color"].default_value = (*emission, 1)
        p.inputs["Emission Strength"].default_value = estr
    return m


def add(col, ob):
    col.objects.link(ob)
    return ob


def mesh_object(col, name, build, mats=(), smooth=True, loc=(0, 0, 0)):
    me = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(me)
    bm.free()
    if smooth:
        for poly in me.polygons:
            poly.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    ob.location = loc
    for m in mats:
        ob.data.materials.append(m)
    return add(col, ob)


def sphere(col, name, radius, loc, mats=(), segs=96, rings=48):
    return mesh_object(col, name, lambda bm: bmesh.ops.create_uvsphere(
        bm, u_segments=segs, v_segments=rings, radius=radius), mats, loc=loc)


def box(col, name, size, loc, mat, bevel=0.03):
    def build(bm):
        bmesh.ops.create_cube(bm, size=1.0)
        bmesh.ops.scale(bm, vec=size, verts=bm.verts)
    ob = mesh_object(col, name, build, [mat], smooth=False, loc=loc)
    if bevel:
        b = ob.modifiers.new("Bevel", 'BEVEL')
        b.width = bevel
        b.segments = 3
        ob.modifiers.new("WN", 'WEIGHTED_NORMAL')
    return ob


def lathe(col, name, profile, segs, mats, mat_fn=None, loc=(0, 0, 0)):
    def build(bm):
        rings = [[bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z))
                  for i in range(segs)] for r, z in profile]
        for j in range(len(rings) - 1):
            for i in range(segs):
                f = bm.faces.new((rings[j][i], rings[j][(i + 1) % segs],
                                  rings[j + 1][(i + 1) % segs], rings[j + 1][i]))
                if mat_fn:
                    f.material_index = mat_fn(f.calc_center_median())
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return mesh_object(col, name, build, mats, loc=loc)


def beam_between(col, name, a, b, t, mat):
    a, b = Vector(a), Vector(b)
    d = b - a
    ob = box(col, name, (1, 1, 1), (a + b) / 2, mat, bevel=0)
    ob.rotation_mode = 'QUATERNION'
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    ob.scale = (t, t, d.length)
    return ob


def track(ob, target):
    c = ob.constraints.new('TRACK_TO')
    c.target = target
    c.track_axis = 'TRACK_NEGATIVE_Z'
    c.up_axis = 'UP_Y'


# ---------------------------------------------------------------- shared environment
def build_world(name):
    world = bpy.data.worlds.new(name)
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    out = N('ShaderNodeOutputWorld')
    bg = N('ShaderNodeBackground')
    L(bg.outputs[0], out.inputs[0])
    coord = N('ShaderNodeTexCoord')
    sep = N('ShaderNodeSeparateXYZ')
    L(coord.outputs['Window'], sep.inputs[0])
    grad = N('ShaderNodeValToRGB')
    grad.color_ramp.elements[0].color = (0.004, 0.010, 0.040, 1)
    grad.color_ramp.elements[1].color = (0.020, 0.055, 0.190, 1)
    L(sep.outputs['Y'], grad.inputs[0])
    vor = N('ShaderNodeTexVoronoi')
    vor.inputs['Scale'].default_value = 110
    L(coord.outputs['Window'], vor.inputs['Vector'])
    star = N('ShaderNodeMapRange')
    star.inputs['From Min'].default_value = 0.06
    star.inputs['From Max'].default_value = 0.0
    L(vor.outputs['Distance'], star.inputs['Value'])
    cell = N('ShaderNodeSeparateColor')
    L(vor.outputs['Color'], cell.inputs[0])

    def math_node(op, a=None, b=None, vb=None):
        n = N('ShaderNodeMath')
        n.operation = op
        if a is not None:
            L(a, n.inputs[0])
        if b is not None:
            L(b, n.inputs[1])
        elif vb is not None:
            n.inputs[1].default_value = vb
        return n

    keep = math_node('GREATER_THAN', cell.outputs[0], vb=0.72)
    tval = N('ShaderNodeValue')
    tval.label = "AU_Time"
    drive(tval.outputs[0], "default_value", f"(frame - 1) / {FRAMES}")
    ph = math_node('ADD', tval.outputs[0], cell.outputs[1])
    ang = math_node('MULTIPLY', ph.outputs[0], vb=2 * math.pi)
    sn = math_node('SINE', ang.outputs[0])
    tw = N('ShaderNodeMapRange')
    tw.inputs['From Min'].default_value = -1
    tw.inputs['To Min'].default_value = 0.25
    L(sn.outputs[0], tw.inputs['Value'])
    m1 = math_node('MULTIPLY', star.outputs[0], keep.outputs[0])
    m2 = math_node('MULTIPLY', m1.outputs[0], tw.outputs[0])
    m3 = math_node('MULTIPLY', m2.outputs[0], vb=12.0)
    comb = N('ShaderNodeCombineColor')
    L(math_node('MULTIPLY', m3.outputs[0], vb=0.75).outputs[0], comb.inputs[0])
    L(math_node('MULTIPLY', m3.outputs[0], vb=0.85).outputs[0], comb.inputs[1])
    L(m3.outputs[0], comb.inputs[2])
    mix = N('ShaderNodeMix')
    mix.data_type = 'RGBA'
    mix.blend_type = 'ADD'
    mix.inputs['Factor'].default_value = 1.0
    L(grad.outputs[0], mix.inputs[6])
    L(comb.outputs[0], mix.inputs[7])
    L(mix.outputs[2], bg.inputs['Color'])
    return world


def build_planet(col, prefix):
    planet = sphere(col, f"{prefix}_Planet", R, (0, 0, -R), segs=192, rings=96)
    m = bpy.data.materials.new(f"{prefix}_PlanetMat")
    m.use_nodes = True
    nt = m.node_tree
    N, L = nt.nodes.new, nt.links.new
    p = nt.nodes["Principled BSDF"]
    tc = N('ShaderNodeTexCoord')
    noise = N('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 0.22
    noise.inputs['Detail'].default_value = 8
    noise.inputs['Roughness'].default_value = 0.55
    L(tc.outputs['Object'], noise.inputs['Vector'])
    ramp = N('ShaderNodeValToRGB')
    ramp.color_ramp.elements[0].position = 0.50
    ramp.color_ramp.elements[0].color = (0.018, 0.16, 0.75, 1)
    ramp.color_ramp.elements[1].position = 0.53
    ramp.color_ramp.elements[1].color = (0.004, 0.028, 0.20, 1)
    L(noise.outputs['Fac'], ramp.inputs[0])
    L(ramp.outputs[0], p.inputs['Base Color'])
    bump = N('ShaderNodeBump')
    bump.inputs['Strength'].default_value = 0.25
    L(noise.outputs['Fac'], bump.inputs['Height'])
    L(bump.outputs['Normal'], p.inputs['Normal'])
    p.inputs['Roughness'].default_value = 0.85
    p.inputs['Specular IOR Level'].default_value = 0.2
    p.inputs['Coat Weight'].default_value = 0.05
    planet.data.materials.append(m)

    atm = sphere(col, f"{prefix}_Atmosphere", R * 1.012, (0, 0, -R), segs=192, rings=96)
    am = bpy.data.materials.new(f"{prefix}_AtmosphereMat")
    am.use_nodes = True
    nt = am.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    o = N('ShaderNodeOutputMaterial')
    lw = N('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.25
    pw = N('ShaderNodeMath')
    pw.operation = 'POWER'
    pw.inputs[1].default_value = 3.2
    L(lw.outputs['Facing'], pw.inputs[0])
    em = N('ShaderNodeEmission')
    em.inputs['Color'].default_value = (0.30, 0.62, 1.0, 1)
    em.inputs['Strength'].default_value = 5.0
    tr = N('ShaderNodeBsdfTransparent')
    mix = N('ShaderNodeMixShader')
    L(pw.outputs[0], mix.inputs[0])
    L(tr.outputs[0], mix.inputs[1])
    L(em.outputs[0], mix.inputs[2])
    L(mix.outputs[0], o.inputs[0])
    atm.data.materials.append(am)
    atm.visible_shadow = False


def build_camera_and_lights(col, prefix, cam_loc, target_loc, key=1900, fill=900):
    target = add(col, bpy.data.objects.new(f"{prefix}_CamTarget", None))
    target.location = target_loc
    cam = add(col, bpy.data.objects.new(f"{prefix}_Cam", bpy.data.cameras.new(f"{prefix}_Cam")))
    cam.data.lens = 50
    cam.location = cam_loc
    track(cam, target)
    light_target = add(col, bpy.data.objects.new(f"{prefix}_LightTarget", None))
    light_target.location = (0, 0, 2.35)
    for name, loc, energy, color, size in (
        ("Key", (-7, -9, 9), key, (1.0, 0.96, 0.92), 5),
        ("Rim", (6, 8, 6), 2200, (0.35, 0.6, 1.0), 4),
        ("Fill", (3, -12, 2.5), fill, (0.6, 0.7, 1.0), 6),
    ):
        ld = bpy.data.lights.new(f"{prefix}_{name}", 'AREA')
        ld.energy, ld.color, ld.size = energy, color, size
        ob = add(col, bpy.data.objects.new(f"{prefix}_{name}", ld))
        ob.location = loc
        ob.visible_glossy = False
        track(ob, light_target)
    return cam


# ---------------------------------------------------------------- state 1: rocket on the pad
def smooth_profile(pts, n=8):
    out = []
    P = [pts[0]] + pts + [pts[-1]]
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = map(Vector, (P[i - 1], P[i], P[i + 1], P[i + 2]))
        for k in range(n):
            t = k / n
            out.append(tuple(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                                    + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)))
    out.append(pts[-1])
    return out


def build_ringed_planet(col, prefix, loc):
    small = sphere(col, f"{prefix}_SmallPlanet", 1.25, loc,
                   [principled(f"{prefix}_SmallPlanetMat", (0.22, 0.30, 0.65), rough=0.6)], 64, 32)

    def ring(bm):
        outer = bmesh.ops.create_circle(bm, cap_ends=False, radius=1.9 * 1.3, segments=96)['verts']
        inner = bmesh.ops.create_circle(bm, cap_ends=False, radius=1.45 * 1.3, segments=96)['verts']
        for i in range(96):
            bm.faces.new((outer[i], outer[(i + 1) % 96], inner[(i + 1) % 96], inner[i]))
    rg = mesh_object(col, f"{prefix}_Ring", ring,
                     [principled(f"{prefix}_RingMat", (0.55, 0.65, 0.95), rough=0.5,
                                 emission=(0.4, 0.55, 1.0), estr=0.6)], smooth=False, loc=small.location)
    rg.rotation_euler = (math.radians(14), 0.38, 0)


def build_rocket(col, prefix):
    """Rocket standing with its nozzle at z=0.55; returns the parent empty."""
    white = principled(f"{prefix}_Hull", (1.0, 1.0, 1.0), rough=0.28, coat=0.6)
    blue = principled(f"{prefix}_Blue", (0.03, 0.22, 0.85), rough=0.3, coat=0.5)
    metal = principled(f"{prefix}_Metal", (0.35, 0.38, 0.45), rough=0.35, metal=1.0)
    glass = principled(f"{prefix}_Glass", (0.05, 0.25, 0.9), rough=0.05, coat=1.0,
                       emission=(0.15, 0.45, 1.0), estr=1.2)

    base = 0.55
    body_pts = [(0.001, base + 0.40), (0.40, base + 0.40), (0.50, base + 0.70), (0.57, base + 1.30),
                (0.58, base + 2.00), (0.53, base + 2.65), (0.40, base + 3.15), (0.22, base + 3.50),
                (0.001, base + 3.72)]

    def body_mat(c):
        return 1 if c.z > base + 2.95 or base + 0.62 < c.z < base + 0.80 else 0
    rocket = add(col, bpy.data.objects.new(f"{prefix}_Rocket", None))
    parts = [
        lathe(col, f"{prefix}_RocketBody", smooth_profile(body_pts), 128, [white, blue], body_mat),
        lathe(col, f"{prefix}_Nozzle", [(0.26, base + 0.42), (0.30, base + 0.25), (0.40, base + 0.02),
                                        (0.37, base), (0.27, base + 0.22), (0.22, base + 0.42)], 96, [metal]),
    ]
    wz = base + 2.05

    def torus(bm, major=0.20, minor=0.045, mseg=64, nseg=16):
        # window ring in the XZ plane, facing the camera (-Y)
        grid = [[bm.verts.new(((major + minor * math.cos(b)) * math.cos(a), minor * math.sin(b),
                               (major + minor * math.cos(b)) * math.sin(a)))
                 for b in (2 * math.pi * j / nseg for j in range(nseg))]
                for a in (2 * math.pi * i / mseg for i in range(mseg))]
        for i in range(mseg):
            for j in range(nseg):
                bm.faces.new((grid[i][j], grid[(i + 1) % mseg][j], grid[(i + 1) % mseg][(j + 1) % nseg],
                              grid[i][(j + 1) % nseg]))
    parts.append(mesh_object(col, f"{prefix}_WindowRing", torus, [metal], loc=(0, -0.565, wz)))
    gl = sphere(col, f"{prefix}_WindowGlass", 0.19, (0, -0.53, wz), [glass], 48, 24)
    gl.scale = (1, 0.35, 1)
    parts.append(gl)

    outline = [(0.45, base + 0.45), (1.05, base + 0.05), (1.10, base), (1.05, base + 0.42), (0.52, base + 1.35)]
    for k in range(4):
        def fin(bm, th=0.05):
            top = [bm.verts.new((x, th, z)) for x, z in outline]
            bot = [bm.verts.new((x, -th, z)) for x, z in outline]
            bm.faces.new(top)
            bm.faces.new(list(reversed(bot)))
            n = len(outline)
            for i in range(n):
                bm.faces.new((top[i], bot[i], bot[(i + 1) % n], top[(i + 1) % n]))
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        f = mesh_object(col, f"{prefix}_Fin{k}", fin, [blue], smooth=False)
        f.rotation_euler = (0, 0, math.radians(45 + 90 * k))
        bev = f.modifiers.new("Bevel", 'BEVEL')
        bev.width = 0.035
        bev.segments = 3
        f.modifiers.new("WN", 'WEIGHTED_NORMAL')
        parts.append(f)
    for p in parts:
        p.parent = rocket
    return rocket


def build_pronto():
    sc, col = new_scene("AU_Pronto", 0.1)
    sc.world = build_world("AU_Pronto_Space")
    build_planet(col, "AU_Pronto")
    sc.camera = build_camera_and_lights(col, "AU_Pronto", (0, -15.0, 3.2), (0, 0, 2.35))

    build_ringed_planet(col, "AU_Pronto", (4.6, 14, 7.9))
    build_rocket(col, "AU_Pronto")

    pad = principled("AU_Pronto_Pad", (0.16, 0.19, 0.28), rough=0.45, metal=0.6)
    pad2 = principled("AU_Pronto_Pad2", (0.24, 0.28, 0.40), rough=0.4, metal=0.6)
    steel = principled("AU_Pronto_Gantry", (0.30, 0.36, 0.55), rough=0.35, metal=0.9)
    for name, r, h, z, m in (("PadBase", 1.9, 0.30, -0.12, pad), ("PadTop", 1.15, 0.20, 0.18, pad2),
                             ("PadRing", 0.55, 0.17, 0.38, pad)):
        def cyl(bm, r=r, h=h, z=z):
            bmesh.ops.create_cone(bm, cap_ends=True, segments=96, radius1=r, radius2=r, depth=h)
            bmesh.ops.translate(bm, verts=bm.verts, vec=(0, 0, z + h / 2))
        ob = mesh_object(col, f"AU_Pronto_{name}", cyl, [m], smooth=False)
        b = ob.modifiers.new("Bevel", 'BEVEL')
        b.width = 0.03
        b.segments = 3
        b.limit_method = 'ANGLE'
        ob.modifiers.new("WN", 'WEIGHTED_NORMAL')

    tx, ty, w, H = -1.75, 0.35, 0.55, 4.3
    corners = [(tx - w / 2, ty - w / 2), (tx + w / 2, ty - w / 2), (tx + w / 2, ty + w / 2), (tx - w / 2, ty + w / 2)]
    tower = add(col, bpy.data.objects.new("AU_Pronto_Tower", None))
    beams = [beam_between(col, f"AU_Pronto_TowerV{i}", (x, y, 0.15), (x, y, H), 0.07, steel)
             for i, (x, y) in enumerate(corners)]
    z, k = 0.15, 0
    while z + 0.5 <= H + 1e-6:
        for i in range(4):
            (x0, y0), (x1, y1) = corners[i], corners[(i + 1) % 4]
            a, b = ((x0, y0, z), (x1, y1, z + 0.5)) if k % 2 else ((x1, y1, z), (x0, y0, z + 0.5))
            beams.append(beam_between(col, f"AU_Pronto_TowerX{k}_{i}", a, b, 0.035, steel))
            beams.append(beam_between(col, f"AU_Pronto_TowerH{k}_{i}", (x0, y0, z + 0.5), (x1, y1, z + 0.5),
                                      0.04, steel))
        z += 0.5
        k += 1
    beams.append(beam_between(col, "AU_Pronto_Arm1", (tx + w / 2, ty - 0.1, 3.05), (-0.55, 0.0, 3.05), 0.09, steel))
    beams.append(beam_between(col, "AU_Pronto_Arm2", (tx + w / 2, ty + 0.1, 2.75), (-0.62, 0.0, 3.0), 0.04, steel))
    for b in beams:
        b.parent = tower

    beacon_mat = principled("AU_Pronto_BeaconMat", (1.0, 0.1, 0.08), emission=(1.0, 0.12, 0.08), estr=14)
    sphere(col, "AU_Pronto_Beacon", 0.09, (tx, ty, H + 0.1), [beacon_mat], 32, 16)
    drive(beacon_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"], "default_value",
          "0.3 + 14 * (sin((frame - 1) * 0.20944) > 0)")
    bl = bpy.data.lights.new("AU_Pronto_BeaconLight", 'POINT')
    bl.color = (1, 0.15, 0.1)
    bl.shadow_soft_size = 0.05
    add(col, bpy.data.objects.new("AU_Pronto_BeaconLight", bl)).location = (tx, ty - 0.2, H + 0.1)
    drive(bl, "energy", "0.5 + 25 * (sin((frame - 1) * 0.20944) > 0)")

    vap = bpy.data.materials.new("AU_Pronto_Vapor")
    vap.use_nodes = True
    nt = vap.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    o = N('ShaderNodeOutputMaterial')
    vol = N('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (0.85, 0.89, 1.0, 1)
    info = N('ShaderNodeObjectInfo')
    tc = N('ShaderNodeTexCoord')
    grad = N('ShaderNodeTexGradient')
    grad.gradient_type = 'SPHERICAL'
    L(tc.outputs['Object'], grad.inputs['Vector'])
    sepc = N('ShaderNodeSeparateColor')
    L(info.outputs['Color'], sepc.inputs[0])
    d2 = N('ShaderNodeMath')
    d2.operation = 'MULTIPLY'
    d2.inputs[1].default_value = 9.0
    L(sepc.outputs[0], d2.inputs[0])
    dens = N('ShaderNodeMath')
    dens.operation = 'MULTIPLY'
    L(grad.outputs['Fac'], dens.inputs[0])
    L(d2.outputs[0], dens.inputs[1])
    noise = N('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 3.0
    L(tc.outputs['Object'], noise.inputs['Vector'])
    d3 = N('ShaderNodeMath')
    d3.operation = 'MULTIPLY'
    L(dens.outputs[0], d3.inputs[0])
    L(noise.outputs['Fac'], d3.inputs[1])
    L(d3.outputs[0], vol.inputs['Density'])
    L(vol.outputs[0], o.inputs['Volume'])
    for side in (-1, 1):
        for j in range(4):
            off = j / 4 + (0.125 if side > 0 else 0)
            ob = mesh_object(col, f"AU_Pronto_Puff{side}_{j}",
                             lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0), [vap])
            ob.visible_shadow = False
            ob.location[1] = -0.25 - 0.15 * j
            x = f"((frame - 1) / 45 + {off})"
            k = f"({x} - floor({x}))"
            drive(ob, "location", f"{side} * (0.75 + 2.0 * {k})", 0)
            drive(ob, "location", f"0.42 + 0.55 * {k}", 2)
            for axis in range(3):
                drive(ob, "scale", f"0.22 + 0.55 * {k}", axis)
            drive(ob, "color", f"pow(sin(3.14159 * {k}), 1.5)", 0)
    return sc


# ---------------------------------------------------------------- states 2 and 5: satellite
def build_satellite(col, prefix, tip_expr, tip_color):
    foil = bpy.data.materials.new(f"{prefix}_Foil")
    foil.use_nodes = True
    nt = foil.node_tree
    p = nt.nodes["Principled BSDF"]
    p.inputs["Base Color"].default_value = (0.95, 0.55, 0.08, 1)
    p.inputs["Metallic"].default_value = 0.55
    p.inputs["Roughness"].default_value = 0.32
    p.inputs["Coat Weight"].default_value = 0.3
    vn = nt.nodes.new('ShaderNodeTexVoronoi')
    vn.inputs['Scale'].default_value = 9
    bp = nt.nodes.new('ShaderNodeBump')
    bp.inputs['Strength'].default_value = 0.6
    nt.links.new(vn.outputs['Distance'], bp.inputs['Height'])
    nt.links.new(bp.outputs['Normal'], p.inputs['Normal'])
    white = principled(f"{prefix}_Hull", (1.0, 1.0, 1.0), rough=0.28, coat=0.6)
    metal = principled(f"{prefix}_Metal", (0.35, 0.38, 0.45), rough=0.35, metal=1.0)

    cell = bpy.data.materials.new(f"{prefix}_SolarCell")
    cell.use_nodes = True
    nt = cell.node_tree
    p = nt.nodes["Principled BSDF"]
    br = nt.nodes.new('ShaderNodeTexBrick')
    br.offset = 0.0
    br.squash = 1.0
    br.inputs['Color1'].default_value = (0.02, 0.10, 0.55, 1)
    br.inputs['Color2'].default_value = (0.03, 0.14, 0.70, 1)
    br.inputs['Mortar'].default_value = (0.55, 0.65, 0.85, 1)
    br.inputs['Scale'].default_value = 7.0
    br.inputs['Mortar Size'].default_value = 0.025
    br.inputs['Brick Width'].default_value = 0.5
    br.inputs['Row Height'].default_value = 0.5
    tc = nt.nodes.new('ShaderNodeTexCoord')
    nt.links.new(tc.outputs['UV'], br.inputs['Vector'])
    nt.links.new(br.outputs['Color'], p.inputs['Base Color'])
    p.inputs['Roughness'].default_value = 0.18
    p.inputs['Metallic'].default_value = 0.4
    p.inputs['Coat Weight'].default_value = 0.8

    sat = add(col, bpy.data.objects.new(f"{prefix}_Satellite", None))
    parts = [box(col, f"{prefix}_SatBody", (0.9, 0.9, 1.05), (0, 0, 0), foil, 0.05),
             box(col, f"{prefix}_SatTop", (0.95, 0.95, 0.12), (0, 0, 0.585), white),
             box(col, f"{prefix}_SatBottom", (0.95, 0.95, 0.12), (0, 0, -0.585), white)]
    for side in (-1, 1):
        parts.append(box(col, f"{prefix}_SatArm{side}", (0.75, 0.07, 0.07), (side * 0.82, 0, 0), metal, 0.01))
        for k in range(2):
            x = side * (1.25 + 0.68 * k + 0.34)
            pnl = box(col, f"{prefix}_Panel{side}_{k}", (0.64, 0.035, 0.95), (x, 0, 0), cell, 0.008)
            uv = pnl.data.uv_layers.new()
            for loop in pnl.data.loops:
                v = pnl.data.vertices[loop.vertex_index].co
                uv.data[loop.index].uv = (v.x / 0.64 + 0.5, v.z / 0.95 + 0.5)
            parts.append(pnl)
            parts.append(box(col, f"{prefix}_PanelFrame{side}_{k}", (0.66, 0.02, 0.97), (x, 0.012, 0), metal, 0.005))
    for name, prof, segs, loc in (
        ("Dish", [(0.0, 0.0), (0.18, 0.012), (0.34, 0.05), (0.48, 0.12), (0.56, 0.18)], 64, (0, 0, -0.95)),
        ("Feed", [(0.0, -0.18), (0.05, -0.12), (0.03, 0.0)], 24, (0, 0, -0.95)),
    ):
        ob = lathe(col, f"{prefix}_{name}", prof, segs, [white if name == "Dish" else metal], loc=loc)
        sol = ob.modifiers.new("Solid", 'SOLIDIFY')
        sol.thickness = 0.03
        if name == "Dish":
            ob.rotation_euler = (math.pi, 0, 0)
        parts.append(ob)
    parts.append(box(col, f"{prefix}_DishMast", (0.06, 0.06, 0.32), (0, 0, -0.76), metal, 0.0))
    parts.append(box(col, f"{prefix}_Antenna", (0.025, 0.025, 0.6), (0.22, 0.1, 0.94), metal, 0.0))
    tip_mat = principled(f"{prefix}_TipMat", tip_color, emission=tip_color, estr=1)
    parts.append(sphere(col, f"{prefix}_AntennaTip", 0.05, (0.22, 0.1, 1.26), [tip_mat], 24, 12))
    drive(tip_mat.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"], "default_value", tip_expr)
    for ob in parts:
        ob.parent = sat
    sat.location = (0, 0, 4.25)
    sat.rotation_euler = (math.radians(14), 0, 0)
    return sat


def build_controllo():
    sc, col = new_scene("AU_Controllo", 0.1)
    sc.world = build_world("AU_Controllo_Space")
    build_planet(col, "AU_Controllo")
    sc.camera = build_camera_and_lights(col, "AU_Controllo", (0, -12.5, 3.3), (0, 0, 2.7))
    sat = build_satellite(col, "AU_Controllo", "0.4 + 12 * (sin((frame - 1) * 0.41888) > 0.3)", (1.0, 0.55, 0.08))
    drive(sat, "location", "4.25 + 0.07 * sin((frame - 1) * 0.069813)", 2)
    drive(sat, "rotation_euler", "0.42 + 0.06 * sin((frame - 1) * 0.069813 + 1.0)", 2)

    segs, rings = 96, 24
    top_z, bot_z, r0, r1 = 3.05, -0.05, 0.14, 1.7

    def cone(bm):
        vs = []
        for j in range(rings + 1):
            t = j / rings
            z, r = top_z + (bot_z - top_z) * t, r0 + (r1 - r0) * t
            vs.append([bm.verts.new((r * math.cos(2 * math.pi * i / segs), r * math.sin(2 * math.pi * i / segs), z))
                       for i in range(segs)])
        for j in range(rings):
            for i in range(segs):
                bm.faces.new((vs[j][i], vs[j][(i + 1) % segs], vs[j + 1][(i + 1) % segs], vs[j + 1][i]))
    beam = mesh_object(col, "AU_Controllo_Beam", cone)
    beam.visible_shadow = False
    drive(beam, "location", "0.07 * sin((frame - 1) * 0.069813)", 2)

    bmat = bpy.data.materials.new("AU_Controllo_BeamMat")
    bmat.use_nodes = True
    nt = bmat.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new

    def math_node(op, a=None, b=None, va=None, vb=None):
        n = N('ShaderNodeMath')
        n.operation = op
        if a is not None:
            L(a, n.inputs[0])
        elif va is not None:
            n.inputs[0].default_value = va
        if b is not None:
            L(b, n.inputs[1])
        elif vb is not None:
            n.inputs[1].default_value = vb
        return n
    o = N('ShaderNodeOutputMaterial')
    tc = N('ShaderNodeTexCoord')
    sep = N('ShaderNodeSeparateXYZ')
    L(tc.outputs['Object'], sep.inputs[0])
    tv = N('ShaderNodeValue')
    drive(tv.outputs[0], "default_value", f"(frame - 1) / {FRAMES}")
    ph = math_node('ADD', math_node('MULTIPLY', sep.outputs['Z'], vb=1.6).outputs[0],
                   math_node('MULTIPLY', tv.outputs[0], vb=3.0).outputs[0])
    ab = math_node('ABSOLUTE', math_node('SUBTRACT', math_node('FRACT', ph.outputs[0]).outputs[0], vb=0.5).outputs[0])
    sh = math_node('POWER', math_node('SUBTRACT', None, ab.outputs[0], va=1.0).outputs[0], vb=18.0)
    mr = N('ShaderNodeMapRange')
    L(sep.outputs['Z'], mr.inputs['Value'])
    mr.inputs['From Min'].default_value = -0.05
    mr.inputs['From Max'].default_value = 3.05
    mr.inputs['To Min'].default_value = 0.35
    mr.inputs['To Max'].default_value = 1.0
    lw = N('ShaderNodeLayerWeight')
    lw.inputs['Blend'].default_value = 0.6
    base = math_node('MULTIPLY', math_node('POWER', lw.outputs['Facing'], vb=1.5).outputs[0], vb=0.5)
    tot = math_node('ADD', base.outputs[0], math_node('MULTIPLY', sh.outputs[0], vb=2.2).outputs[0])
    fade = math_node('MULTIPLY', tot.outputs[0], mr.outputs[0])
    em = N('ShaderNodeEmission')
    em.inputs['Color'].default_value = (0.35, 0.65, 1.0, 1)
    L(fade.outputs[0], em.inputs['Strength'])
    tr = N('ShaderNodeBsdfTransparent')
    sh_add = N('ShaderNodeAddShader')
    L(tr.outputs[0], sh_add.inputs[0])
    L(em.outputs[0], sh_add.inputs[1])
    L(sh_add.outputs[0], o.inputs['Surface'])
    beam.data.materials.append(bmat)

    spot = bpy.data.lights.new("AU_Controllo_ScanSpot", 'SPOT')
    spot.energy, spot.color = 900, (0.35, 0.65, 1.0)
    spot.spot_size, spot.spot_blend, spot.shadow_soft_size = math.radians(60), 0.8, 0.4
    add(col, bpy.data.objects.new("AU_Controllo_ScanSpot", spot)).location = (0, 0, 3.0)
    return sc


def build_rete():
    sc, col = new_scene("AU_Rete", -0.1)
    sc.world = build_world("AU_Rete_Space")
    build_planet(col, "AU_Rete")
    sc.camera = build_camera_and_lights(col, "AU_Rete", (0, -12.5, 3.3), (0, 0, 2.7), key=1100, fill=500)
    sat = build_satellite(col, "AU_Rete", "0.2 + 6 * pow(0.5 + 0.5 * sin((frame - 1) * 0.069813), 4)",
                          (1.0, 0.12, 0.08))
    drive(sat, "location", "4.25 + 0.10 * sin((frame - 1) * 0.069813)", 2)
    drive(sat, "rotation_euler", "0.10 * sin((frame - 1) * 0.069813 + 2.0)", 1)
    drive(sat, "rotation_euler", "0.42 + 0.16 * sin((frame - 1) * 0.069813 + 1.0)", 2)
    for i, r in enumerate((0.55, 0.9, 1.25)):
        cu = bpy.data.curves.new(f"AU_Rete_Signal{i}", 'CURVE')
        cu.dimensions = '3D'
        cu.bevel_depth = 0.028
        cu.bevel_resolution = 4
        cu.use_fill_caps = True
        sp = cu.splines.new('POLY')
        n = 40
        sp.points.add(n - 1)
        for k in range(n):
            a = math.radians(-145 + 110 * k / (n - 1))
            sp.points[k].co = (r * math.cos(a), 0, -1.05 + r * math.sin(a), 1)
        ob = add(col, bpy.data.objects.new(f"AU_Rete_Signal{i}", cu))
        ob.parent = sat
        ob.visible_shadow = False
        m = bpy.data.materials.new(f"AU_Rete_SignalMat{i}")
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        o = nt.nodes.new('ShaderNodeOutputMaterial')
        em = nt.nodes.new('ShaderNodeEmission')
        em.inputs['Color'].default_value = (0.55, 0.65, 0.85, 1)
        tr = nt.nodes.new('ShaderNodeBsdfTransparent')
        mix = nt.nodes.new('ShaderNodeMixShader')
        nt.links.new(tr.outputs[0], mix.inputs[1])
        nt.links.new(em.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], o.inputs[0])
        lit = f"(floor(4 * (frame - 1) / {FRAMES}) >= {i + 1})"
        drive(em.inputs['Strength'], "default_value", f"0.15 + 4 * {lit}")
        drive(mix.inputs[0], "default_value", f"0.25 + 0.75 * {lit}")
        ob.data.materials.append(m)
    return sc


# ---------------------------------------------------------------- "up to date": rocket in flight (still image)
def build_aggiornato():
    sc, col = new_scene("AU_Aggiornato", 0.1)
    sc.frame_end = 1
    sc.cycles.samples = 256
    sc.world = build_world("AU_Aggiornato_Space")
    build_planet(col, "AU_Aggiornato")
    sc.camera = build_camera_and_lights(col, "AU_Aggiornato", (0, -15.0, 4.0), (0, 0, 3.4))
    build_ringed_planet(col, "AU_Aggiornato", (-4.8, 14, 8.4))
    lift = 3.0
    build_rocket(col, "AU_Aggiornato").location = (0, 0, lift)
    nozzle_z = 0.55 + lift

    def flame_material(name, inner, outer, strength):
        m = bpy.data.materials.new(name)
        m.use_nodes = True
        nt = m.node_tree
        nt.nodes.clear()
        N, L = nt.nodes.new, nt.links.new
        o = N('ShaderNodeOutputMaterial')
        tc = N('ShaderNodeTexCoord')
        sep = N('ShaderNodeSeparateXYZ')
        L(tc.outputs['Object'], sep.inputs[0])
        t = N('ShaderNodeMapRange')  # 0 at the nozzle, 1 at the flame tip
        t.inputs['From Min'].default_value = 0.0
        t.inputs['From Max'].default_value = -1.0
        L(sep.outputs['Z'], t.inputs['Value'])
        ramp = N('ShaderNodeValToRGB')
        ramp.color_ramp.elements[0].color = (*inner, 1)
        ramp.color_ramp.elements[1].position = 1.0
        ramp.color_ramp.elements[1].color = (*outer, 1)
        L(t.outputs[0], ramp.inputs[0])
        em = N('ShaderNodeEmission')
        L(ramp.outputs[0], em.inputs['Color'])
        em.inputs['Strength'].default_value = strength
        fade = N('ShaderNodeMath')
        fade.operation = 'SUBTRACT'
        fade.inputs[0].default_value = 1.0
        L(t.outputs[0], fade.inputs[1])
        mix = N('ShaderNodeMixShader')
        L(fade.outputs[0], mix.inputs[0])
        L(N('ShaderNodeBsdfTransparent').outputs[0], mix.inputs[1])
        L(em.outputs[0], mix.inputs[2])
        L(mix.outputs[0], o.inputs['Surface'])
        return m

    for name, radius, length, inner, outer, strength in (
        ("FlameOuter", 0.38, 1.9, (1.0, 0.55, 0.12), (1.0, 0.18, 0.02), 14.0),
        ("FlameCore", 0.22, 1.0, (1.0, 0.95, 0.80), (1.0, 0.65, 0.20), 30.0),
    ):
        prof = [(radius * (1 - (k / 16) ** 1.6) + 0.001, -length * k / 16) for k in range(17)]
        ob = lathe(col, f"AU_Aggiornato_{name}", prof, 64,
                   [flame_material(f"AU_Aggiornato_{name}Mat", inner, outer, strength)],
                   loc=(0, 0, nozzle_z))
        ob.scale = (1, 1, length)  # object Z spans 0..-1 for the material ramp
        for v in ob.data.vertices:
            v.co.z /= length
        ob.visible_shadow = False

    glow = bpy.data.lights.new("AU_Aggiornato_FlameGlow", 'POINT')
    glow.energy, glow.color, glow.shadow_soft_size = 260, (1.0, 0.55, 0.2), 0.3
    add(col, bpy.data.objects.new("AU_Aggiornato_FlameGlow", glow)).location = (0, -0.6, nozzle_z - 0.5)

    smoke = bpy.data.materials.new("AU_Aggiornato_Smoke")
    smoke.use_nodes = True
    nt = smoke.node_tree
    nt.nodes.clear()
    N, L = nt.nodes.new, nt.links.new
    o = N('ShaderNodeOutputMaterial')
    vol = N('ShaderNodeVolumePrincipled')
    vol.inputs['Color'].default_value = (0.80, 0.85, 1.0, 1)
    tc = N('ShaderNodeTexCoord')
    grad = N('ShaderNodeTexGradient')
    grad.gradient_type = 'SPHERICAL'
    L(tc.outputs['Object'], grad.inputs['Vector'])
    noise = N('ShaderNodeTexNoise')
    noise.inputs['Scale'].default_value = 2.5
    L(tc.outputs['Object'], noise.inputs['Vector'])
    info = N('ShaderNodeObjectInfo')
    sepc = N('ShaderNodeSeparateColor')
    L(info.outputs['Color'], sepc.inputs[0])
    d1 = N('ShaderNodeMath')
    d1.operation = 'MULTIPLY'
    L(grad.outputs['Fac'], d1.inputs[0])
    L(noise.outputs['Fac'], d1.inputs[1])
    d2 = N('ShaderNodeMath')
    d2.operation = 'MULTIPLY'
    L(d1.outputs[0], d2.inputs[0])
    L(sepc.outputs[0], d2.inputs[1])
    L(d2.outputs[0], vol.inputs['Density'])
    L(vol.outputs[0], o.inputs['Volume'])
    import random
    rnd = random.Random(4)
    for i in range(9):
        k = i / 8
        z = nozzle_z - 1.75 - 0.36 * i
        if z < 0.15:
            break
        ob = mesh_object(col, f"AU_Aggiornato_Smoke{i}",
                         lambda bm: bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0), [smoke])
        ob.location = (rnd.uniform(-0.2, 0.2) * (1 + 2 * k), 0.2, z)
        ob.scale = (0.35 + 1.1 * k ** 1.3,) * 3
        ob.color = (9 * (1 - 0.6 * k), 0, 0, 1)
        ob.visible_shadow = False
    return sc


def invalid_drivers():
    bad = []
    for coll in (bpy.data.objects, bpy.data.lights, bpy.data.materials, bpy.data.worlds):
        for idb in coll:
            if not idb.name.startswith("AU_"):
                continue
            owner = idb.node_tree if getattr(idb, "node_tree", None) else idb
            ad = owner.animation_data
            for fc in (ad.drivers if ad else []):
                if not (fc.driver.is_valid and fc.driver.is_simple_expression):
                    bad.append(f"{idb.name}: {fc.driver.expression}")
    return bad


def build_all():
    scenes = [build_pronto(), build_controllo(), build_rete(), build_aggiornato()]
    return {"scenes": [s.name for s in scenes], "invalid_drivers": invalid_drivers()}
