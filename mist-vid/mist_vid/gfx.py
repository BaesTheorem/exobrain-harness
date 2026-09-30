"""GPU compositor core (moderngl, OpenGL 4.1 on Apple Silicon).

Image-space convention everywhere: uv.y = 0 is the TOP row. Uploaded numpy images
(row 0 = top) and FBO textures agree with it, and readback returns top-down rows,
so nothing is flipped. gl-transitions assume GL's bottom-up uv, so their wrapper
flips y on the way in and out.
"""
from __future__ import annotations

import os
import re

import moderngl
import numpy as np

from . import grades

from .paths import GL_TRANSITIONS as TRANSITIONS

HERE = os.path.dirname(os.path.abspath(__file__))
OWN_TRANSITIONS = os.path.join(HERE, "transitions")

VS = """#version 330
in vec2 p; out vec2 uv;
void main(){ uv = p*0.5+0.5; gl_Position = vec4(p,0.0,1.0); }"""

NOISE = """
float hash12(vec2 p){ vec3 p3 = fract(vec3(p.xyx) * .1031); p3 += dot(p3, p3.yzx + 33.33); return fract((p3.x + p3.y) * p3.z); }
float vnoise(vec2 p){ vec2 i=floor(p), f=fract(p); vec2 u=f*f*(3.0-2.0*f);
  return mix(mix(hash12(i),hash12(i+vec2(1,0)),u.x), mix(hash12(i+vec2(0,1)),hash12(i+vec2(1,1)),u.x), u.y); }
float fbm(vec2 p){ float a=0.5, s=0.0; for(int i=0;i<5;i++){ s+=a*vnoise(p); p*=2.03; a*=0.5; } return s; }
"""

CLIP_FS = """#version 330
in vec2 uv; out vec4 o;
uniform sampler2D src; uniform sampler3D lut;
uniform vec2 canvas; uniform vec4 pic; uniform vec2 srcsize;
uniform float zoom; uniform vec2 center; uniform float rot; uniform vec2 weave; uniform int hflip;
uniform float exposure; uniform float sat; uniform float contrast; uniform float lutmix;
uniform vec3 tint; uniform float flash; uniform float mono; uniform float fade; uniform float blur;
vec3 grade(vec3 col){
  col *= exp2(exposure);
  vec3 lc = clamp(col, 0.0, 1.0);
  vec3 g = texture(lut, lc * (32.0/33.0) + 0.5/33.0).rgb;
  col = mix(col, g, lutmix);
  float y = dot(col, vec3(0.2126, 0.7152, 0.0722));
  col = mix(vec3(y), col, sat);
  col = (col - 0.5) * contrast + 0.5;
  col = mix(col, vec3(y) * vec3(1.08, 0.95, 0.77), mono);
  col *= tint;
  col = mix(col, vec3(1.0), flash);
  return col * (1.0 - fade);
}
void main(){
  vec2 px = uv * canvas;
  vec2 q = (px - pic.xy) / pic.zw;
  if (q.x < 0.0 || q.y < 0.0 || q.x > 1.0 || q.y > 1.0) { o = vec4(0.0); return; }
  vec2 dp = (q - 0.5) * pic.zw + weave;
  float c = cos(-rot), s = sin(-rot);
  dp = vec2(c*dp.x - s*dp.y, s*dp.x + c*dp.y) / zoom;
  float cover = max(pic.z / srcsize.x, pic.w / srcsize.y);
  vec2 sp = center * srcsize + dp / cover;
  vec2 suv = sp / srcsize;
  if (hflip == 1) suv.x = 1.0 - suv.x;
  suv = clamp(suv, vec2(0.5)/srcsize, vec2(1.0) - vec2(0.5)/srcsize);
  vec3 col;
  if (blur > 0.01) {
    vec3 acc = vec3(0.0); float wsum = 0.0;
    for (int i = -3; i <= 3; i++) for (int j = -3; j <= 3; j++) {
      float w = exp(-float(i*i + j*j) / 8.0);
      acc += texture(src, suv + vec2(i, j) * blur / srcsize).rgb * w; wsum += w; }
    col = acc / wsum;
  } else col = texture(src, suv).rgb;
  o = vec4(grade(col), 1.0);
}"""

SPRITE_VS = """#version 330
in vec2 p; out vec2 tuv;
uniform vec4 rect; uniform vec2 canvas; uniform float angle;
void main(){
  tuv = p*0.5+0.5;
  vec2 center = rect.xy + rect.zw*0.5;
  vec2 d = (p*0.5) * rect.zw;
  float c = cos(angle), s = sin(angle);
  d = vec2(c*d.x - s*d.y, s*d.x + c*d.y);
  vec2 px = center + d;
  gl_Position = vec4(px / canvas * 2.0 - 1.0, 0.0, 1.0);
}"""

SPRITE_FS = """#version 330
in vec2 tuv; out vec4 o;
uniform sampler2D sprite; uniform sampler2D spec; uniform float opacity; uniform vec3 color_mul;
uniform float reveal; uniform float soft; uniform float seed; uniform vec2 rdir; uniform float nscale;
uniform float sweep; uniform float sweep_amt;
""" + NOISE + """
void main(){
  vec4 c = texture(sprite, tuv);
  c.rgb *= color_mul;
  if (sweep_amt > 0.0) {
    float band = exp(-pow(tuv.x + (tuv.y - 0.5) * 0.35 - sweep, 2.0) / 0.0035);
    c.rgb += texture(spec, tuv).r * band * sweep_amt * vec3(1.0, 0.93, 0.75);
  }
  c.rgb *= c.a;
  float m = 1.0;
  if (reveal >= 0.0) {
    float g = dot(tuv - 0.5, rdir) + 0.5;
    float n = fbm(tuv * vec2(nscale, nscale*0.5) + seed);
    float v = g * 0.72 + n * 0.28;
    float r = reveal * (1.0 + 2.0*soft) - soft;
    m = smoothstep(v - soft, v + soft, r);
  }
  o = c * opacity * m;
}"""

EXTRACT_FS = """#version 330
in vec2 uv; out vec4 o; uniform sampler2D tex; uniform float thr; uniform float knee;
void main(){ vec3 c = texture(tex, uv).rgb; float br = max(c.r, max(c.g, c.b));
  float soft = clamp(br - thr + knee, 0.0, 2.0*knee); soft = soft*soft/(4.0*knee + 1e-4);
  float contrib = max(soft, br - thr) / max(br, 1e-4);
  o = vec4(c * contrib, 1.0); }"""

DOWN_FS = """#version 330
in vec2 uv; out vec4 o; uniform sampler2D tex; uniform vec2 texel;
void main(){ vec3 a = texture(tex, uv + texel*vec2(-1,-1)).rgb + texture(tex, uv + texel*vec2(1,-1)).rgb
  + texture(tex, uv + texel*vec2(-1,1)).rgb + texture(tex, uv + texel*vec2(1,1)).rgb;
  vec3 b = texture(tex, uv).rgb;
  o = vec4(a*0.125 + b*0.5, 1.0); }"""

UP_FS = """#version 330
in vec2 uv; out vec4 o; uniform sampler2D tex; uniform sampler2D prev; uniform vec2 texel; uniform float w;
void main(){ vec3 s = texture(tex, uv).rgb*4.0
  + (texture(tex, uv+texel*vec2(-1,0)).rgb + texture(tex, uv+texel*vec2(1,0)).rgb + texture(tex, uv+texel*vec2(0,-1)).rgb + texture(tex, uv+texel*vec2(0,1)).rgb)*2.0
  + (texture(tex, uv+texel*vec2(-1,-1)).rgb + texture(tex, uv+texel*vec2(1,-1)).rgb + texture(tex, uv+texel*vec2(-1,1)).rgb + texture(tex, uv+texel*vec2(1,1)).rgb);
  o = vec4(s/16.0 * w + texture(prev, uv).rgb, 1.0); }"""

COPY_FS = """#version 330
in vec2 uv; out vec4 o; uniform sampler2D tex; uniform float gain;
void main(){ o = vec4(texture(tex, uv).rgb * gain, 1.0); }"""

MIX_FS = """#version 330
in vec2 uv; out vec4 o; uniform sampler2D a; uniform sampler2D b; uniform float t; uniform int mode;
void main(){ vec3 x = texture(a, uv).rgb, y = texture(b, uv).rgb; vec3 r;
  if (mode == 0) r = mix(x, y, t);
  else if (mode == 1) r = x + y*t;
  else if (mode == 2) r = 1.0 - (1.0 - x) * (1.0 - clamp(y,0.0,1.0)*t);
  else if (mode == 3) { vec3 s = 1.0 - (1.0 - x) * (1.0 - clamp(y,0.0,1.0)); float l = dot(y, vec3(0.3,0.5,0.2)); r = mix(x, s, t * smoothstep(0.05, 0.6, l)); }
  else r = mix(x, x*y, t);
  o = vec4(r, 1.0); }"""

FINISH_FS = """#version 330
in vec2 uv; out vec4 o;
uniform sampler2D comp; uniform sampler2D bloom; uniform sampler2D halo; uniform sampler2D grain;
uniform vec2 canvas; uniform float bloom_amt; uniform float halo_amt; uniform float grain_amt; uniform float vig_amt;
uniform float fade; uniform vec3 fade_color; uniform float bars; uniform vec2 goff; uniform float seed; uniform float flicker;
""" + NOISE + """
void main(){
  vec3 col = texture(comp, uv).rgb;
  col += texture(bloom, uv).rgb * bloom_amt;
  vec3 h = texture(halo, uv).rgb;
  col += h * vec3(1.0, 0.36, 0.14) * halo_amt;
  vec2 d = (uv - 0.5) * vec2(canvas.x/canvas.y, 1.0);
  float v = smoothstep(1.05, 0.28, length(d));
  col *= mix(1.0, v, vig_amt);
  col *= flicker;
  float y = dot(clamp(col,0.0,1.0), vec3(0.2126, 0.7152, 0.0722));
  float g = texture(grain, uv * canvas / 512.0 + goff).r;
  float amp = grain_amt * (0.30 + 0.70 * 4.0 * y * (1.0 - y));
  col += vec3(g) * amp;
  col = mix(col, fade_color, fade);
  if (uv.y < bars || uv.y > 1.0 - bars) col = vec3(0.0);
  col += (hash12(uv * canvas + seed * 13.1) - 0.5) / 255.0;
  o = vec4(clamp(col, 0.0, 1.0), 1.0);
}"""


def _parse_default(typ: str, val: str):
    val = val.strip().rstrip(";")
    nums = [float(x) for x in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", val)]
    if typ in ("float",):
        return nums[0] if nums else 0.0
    if typ in ("int",):
        return int(nums[0]) if nums else 0
    if typ == "bool":
        return "true" in val
    if typ.startswith(("vec", "ivec")):
        n = int(typ[-1])
        if len(nums) == 1:
            nums = nums * n
        out = tuple(nums[:n])
        return tuple(int(x) for x in out) if typ.startswith("ivec") else out
    return None


class GFX:
    def __init__(self, w: int = 1920, h: int = 1080, src_w: int = 1920, src_h: int = 1040):
        self.W, self.H, self.SW, self.SH = w, h, src_w, src_h
        self.ctx = moderngl.create_context(standalone=True, require=330)
        self.quad = self.ctx.buffer(np.array([-1, -1, 1, -1, -1, 1, 1, 1], dtype="f4").tobytes())
        self.progs = {}
        self.vaos = {}
        for name, fs in (("clip", CLIP_FS), ("extract", EXTRACT_FS), ("down", DOWN_FS), ("up", UP_FS),
                         ("copy", COPY_FS), ("mix", MIX_FS), ("finish", FINISH_FS)):
            self._prog(name, VS, fs)
        self._prog("sprite", SPRITE_VS, SPRITE_FS)
        self.luts = {}
        self.src_tex = [self.ctx.texture((src_w, src_h), 3) for _ in range(4)]
        for t in self.src_tex:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.card_tex = [self.ctx.texture((w, h), 3) for _ in range(2)]
        for t in self.card_tex:
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = False
        self.layers = [self._fbo(w, h) for _ in range(6)]
        self.final = self.ctx.simple_framebuffer((w, h), components=4)
        # bloom chain
        self.bloom_chain = []
        bw, bh = w // 2, h // 2
        for _ in range(6):
            self.bloom_chain.append(self._fbo(bw, bh))
            bw, bh = max(1, bw // 2), max(1, bh // 2)
        self.bloom_up = [self._fbo(f[1].width, f[1].height) for f in self.bloom_chain]
        self.halo_chain = [self._fbo(w // 4, h // 4), self._fbo(w // 8, h // 8), self._fbo(w // 16, h // 16)]
        self.halo_up = [self._fbo(f[1].width, f[1].height) for f in self.halo_chain]
        self.black = self._fbo(8, 8)
        self.black[0].use()
        self.ctx.clear(0, 0, 0, 1)
        self.grain = self._make_grain()
        self.trans = {}
        self.sprites = {}
        self.paper_tex = None

    def set_paper(self, rgb: np.ndarray):
        h, w = rgb.shape[:2]
        t = self.ctx.texture((w, h), 3, np.ascontiguousarray((np.clip(rgb, 0, 1) * 255).astype(np.uint8)).tobytes())
        t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        t.repeat_x = t.repeat_y = True
        self.paper_tex = t

    # --- plumbing ---------------------------------------------------------
    def _prog(self, name, vs, fs):
        p = self.ctx.program(vertex_shader=vs, fragment_shader=fs)
        self.progs[name] = p
        self.vaos[name] = self.ctx.simple_vertex_array(p, self.quad, "p")
        return p

    def _fbo(self, w, h):
        t = self.ctx.texture((w, h), 4, dtype="f2")
        t.filter = (moderngl.LINEAR, moderngl.LINEAR)
        t.repeat_x = t.repeat_y = False
        return self.ctx.framebuffer(color_attachments=[t]), t

    def _make_grain(self):
        rng = np.random.default_rng(7)
        import cv2
        texs = []
        for _ in range(6):
            n = rng.standard_normal((512, 512)).astype(np.float32)
            n = cv2.GaussianBlur(np.pad(n, 8, mode="wrap"), (0, 0), 0.65)[8:-8, 8:-8]
            n /= n.std() + 1e-6
            t = self.ctx.texture((512, 512), 1, n.tobytes(), dtype="f4")
            t.repeat_x = t.repeat_y = True
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            texs.append(t)
        return texs

    def lut(self, name):
        if name not in self.luts:
            data = grades.lut(name)
            t = self.ctx.texture3d((grades.N, grades.N, grades.N), 3, data.tobytes(), dtype="f4")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            t.repeat_x = t.repeat_y = t.repeat_z = False
            self.luts[name] = t
        return self.luts[name]

    def set(self, prog, **kw):
        p = self.progs[prog] if isinstance(prog, str) else prog
        for k, v in kw.items():
            if k in p:
                p[k].value = v
        return p

    def draw(self, name, target, textures=(), **uniforms):
        target[0].use() if isinstance(target, tuple) else target.use()
        p = self.progs[name]
        for i, (uname, tex) in enumerate(textures):
            tex.use(i)
            if uname in p:
                p[uname].value = i
        self.set(p, **uniforms)
        self.vaos[name].render(moderngl.TRIANGLE_STRIP)

    # --- stages -----------------------------------------------------------
    def upload(self, slot: int, frame: np.ndarray):
        self.src_tex[slot].write(np.ascontiguousarray(frame).tobytes())
        return self.src_tex[slot]

    def clip(self, layer: int, slot: int, pic, look: dict, tex=None):
        """Draw source texture `slot` (or `tex`) into layer FBO with transform + grade."""
        fbo = self.layers[layer]
        fbo[0].use()
        self.ctx.clear(0, 0, 0, 0)
        src = tex if tex is not None else self.src_tex[slot]
        self.draw("clip", fbo, [("src", src), ("lut", self.lut(look.get("grade", "storybook")))],
                  canvas=(self.W, self.H), pic=tuple(pic), srcsize=(src.width, src.height),
                  zoom=float(look.get("zoom", 1.0)), center=tuple(look.get("center", (0.5, 0.5))),
                  rot=float(look.get("rot", 0.0)), weave=tuple(look.get("weave", (0.0, 0.0))),
                  hflip=int(look.get("hflip", 0)),
                  exposure=float(look.get("exposure", 0.0)), sat=float(look.get("sat", 1.0)),
                  contrast=float(look.get("contrast", 1.0)), lutmix=float(look.get("lutmix", 1.0)),
                  tint=tuple(look.get("tint", (1.0, 1.0, 1.0))), flash=float(look.get("flash", 0.0)),
                  mono=float(look.get("mono", 0.0)), fade=float(look.get("fade", 0.0)),
                  blur=float(look.get("blur", 0.0)))
        return fbo

    def transition(self, name: str, a, b, progress: float, target, params: dict | None = None):
        if name not in self.trans:
            path = os.path.join(OWN_TRANSITIONS, name + ".glsl")
            if not os.path.exists(path):
                path = os.path.join(TRANSITIONS, name + ".glsl")
            srcs = open(path).read()
            defaults = {}
            for m in re.finditer(r"uniform\s+(\w+)\s+(\w+)\s*;\s*//\s*=\s*([^\n]+)", srcs):
                defaults[m.group(2)] = _parse_default(m.group(1), m.group(3))
            fs = ("#version 330\nin vec2 uv; out vec4 o;\nuniform sampler2D from_tex; uniform sampler2D to_tex;\n"
                  "uniform float progress; uniform float ratio; uniform sampler2D paper;\n"
                  "vec4 getFromColor(vec2 p){ return texture(from_tex, vec2(p.x, 1.0 - p.y)); }\n"
                  "vec4 getToColor(vec2 p){ return texture(to_tex, vec2(p.x, 1.0 - p.y)); }\n"
                  + srcs.replace("texture2D(", "texture(") +
                  "\nvoid main(){ o = transition(vec2(uv.x, 1.0 - uv.y)); }\n")
            prog = self.ctx.program(vertex_shader=VS, fragment_shader=fs)
            vao = self.ctx.simple_vertex_array(prog, self.quad, "p")
            self.trans[name] = (prog, vao, defaults)
        prog, vao, defaults = self.trans[name]
        target[0].use()
        a[1].use(0)
        b[1].use(1)
        if "from_tex" in prog:
            prog["from_tex"].value = 0
        if "to_tex" in prog:
            prog["to_tex"].value = 1
        paper = self.paper_tex
        if "paper" in prog and paper is not None:
            paper.use(2)
            prog["paper"].value = 2
        vals = dict(defaults)
        vals.update(params or {})
        vals["progress"] = float(progress)
        vals["ratio"] = self.W / self.H
        for k, v in vals.items():
            if k in prog and v is not None:
                try:
                    prog[k].value = v
                except Exception:
                    pass
        vao.render(moderngl.TRIANGLE_STRIP)
        return target

    def mix(self, a, b, t, target, mode=0):
        self.draw("mix", target, [("a", a[1]), ("b", b[1])], t=float(t), mode=int(mode))
        return target

    def sprite_tex(self, key, rgba: np.ndarray):
        if key not in self.sprites:
            h, w = rgba.shape[:2]
            t = self.ctx.texture((w, h), 4, np.ascontiguousarray(rgba).tobytes())
            t.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            t.build_mipmaps()
            t.repeat_x = t.repeat_y = False
            self.sprites[key] = t
        return self.sprites[key]

    def spec_tex(self, key, spec: np.ndarray):
        k = ("spec", key)
        if k not in self.sprites:
            h, w = spec.shape[:2]
            t = self.ctx.texture((w, h), 1, np.ascontiguousarray(spec.astype(np.float32)).tobytes(), dtype="f4")
            t.filter = (moderngl.LINEAR, moderngl.LINEAR)
            self.sprites[k] = t
        return self.sprites[k]

    def sprite(self, target, tex, rect, opacity=1.0, blend="normal", angle=0.0, reveal=-1.0, soft=0.06,
               seed=0.0, rdir=(1.0, 0.0), color_mul=(1.0, 1.0, 1.0), nscale=6.0, spec=None, sweep=0.0,
               sweep_amt=0.0):
        target[0].use()
        ctx = self.ctx
        ctx.enable(moderngl.BLEND)
        if blend == "add":
            ctx.blend_func = moderngl.ONE, moderngl.ONE
        elif blend == "screen":
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_COLOR
        elif blend == "multiply":
            ctx.blend_func = moderngl.DST_COLOR, moderngl.ONE_MINUS_SRC_ALPHA
        else:
            ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        tex.use(0)
        (spec if spec is not None else self.black[1]).use(1)
        p = self.progs["sprite"]
        p["sprite"].value = 0
        if "spec" in p:
            p["spec"].value = 1
        self.set(p, rect=tuple(float(x) for x in rect), canvas=(self.W, self.H), angle=float(angle),
                 opacity=float(opacity), reveal=float(reveal), soft=float(soft), seed=float(seed),
                 rdir=tuple(rdir), color_mul=tuple(color_mul), nscale=float(nscale), sweep=float(sweep),
                 sweep_amt=float(sweep_amt if spec is not None else 0.0))
        self.vaos["sprite"].render(moderngl.TRIANGLE_STRIP)
        ctx.disable(moderngl.BLEND)

    def bloom(self, src, thr=0.72, knee=0.25):
        """Returns (bloom_tex, halo_tex) for the composite in `src`."""
        c0 = self.bloom_chain[0]
        self.draw("extract", c0, [("tex", src[1])], thr=float(thr), knee=float(knee))
        for i in range(1, len(self.bloom_chain)):
            prev = self.bloom_chain[i - 1]
            self.draw("down", self.bloom_chain[i], [("tex", prev[1])],
                      texel=(1.0 / prev[1].width, 1.0 / prev[1].height))
        # upsample: start from the smallest
        last = self.bloom_chain[-1]
        self.draw("copy", self.bloom_up[-1], [("tex", last[1])], gain=1.0)
        for i in range(len(self.bloom_chain) - 2, -1, -1):
            lower = self.bloom_up[i + 1]
            self.draw("up", self.bloom_up[i], [("tex", lower[1]), ("prev", self.bloom_chain[i][1])],
                      texel=(1.0 / lower[1].width, 1.0 / lower[1].height), w=1.0)
        bloom = self.bloom_up[0]
        # halation: brighter threshold, wide, from the chain's lower mips
        self.draw("extract", self.halo_chain[0], [("tex", src[1])], thr=0.82, knee=0.12)
        for i in range(1, len(self.halo_chain)):
            prev = self.halo_chain[i - 1]
            self.draw("down", self.halo_chain[i], [("tex", prev[1])],
                      texel=(1.0 / prev[1].width, 1.0 / prev[1].height))
        self.draw("copy", self.halo_up[-1], [("tex", self.halo_chain[-1][1])], gain=1.0)
        for i in range(len(self.halo_chain) - 2, -1, -1):
            lower = self.halo_up[i + 1]
            self.draw("up", self.halo_up[i], [("tex", lower[1]), ("prev", self.halo_chain[i][1])],
                      texel=(1.0 / lower[1].width, 1.0 / lower[1].height), w=1.0)
        return bloom, self.halo_up[0]

    def finish(self, comp, bloom, halo, frame_i, fin: dict):
        rng = np.random.default_rng(frame_i * 7919 + 13)
        g = self.grain[frame_i % len(self.grain)]
        self.final.use()
        p = self.progs["finish"]
        comp[1].use(0)
        bloom[1].use(1)
        halo[1].use(2)
        g.use(3)
        p["comp"].value, p["bloom"].value, p["halo"].value, p["grain"].value = 0, 1, 2, 3
        self.set(p, canvas=(self.W, self.H), bloom_amt=float(fin.get("bloom", 0.22)),
                 halo_amt=float(fin.get("halo", 0.10)), grain_amt=float(fin.get("grain", 0.035)),
                 vig_amt=float(fin.get("vignette", 0.35)), fade=float(fin.get("fade", 0.0)),
                 fade_color=tuple(fin.get("fade_color", (0.0, 0.0, 0.0))), bars=float(fin.get("bars", 20 / 1080)),
                 goff=(float(rng.random()), float(rng.random())), seed=float(frame_i % 997),
                 flicker=float(fin.get("flicker", 1.0)))
        self.vaos["finish"].render(moderngl.TRIANGLE_STRIP)
        return self.final.read(components=3)
