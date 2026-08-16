// cardioid.cpp - renders a multi-colored cardioid to a PNG.
//
// The picture is built from two things that happen to be the same curve:
//
//   1. The "times table" string art: join point t on a circle to point 2t,
//      for a few thousand t. Every chord is tangent to a cardioid, so the
//      envelope of the whole web is the curve, drawn by the gaps.
//   2. The analytic envelope of that family, which works out to
//         P(t) = (2/3)(cos t, sin t) + (1/3)(cos 2t, sin 2t)
//      (a unit-circle epicycloid). Derived by solving F = dF/dt = 0 for the
//      chord line x*cos(3t/2) + y*sin(3t/2) = cos(t/2).
//
// Color is hue swept around the parameter, blended additively, then bloomed
// and tone mapped. Only dependency is zlib, for PNG deflate + crc32.
//
//   c++ -O2 -std=c++17 cardioid.cpp -lz -o cardioid && ./cardioid
//
// Options: --size N  --lines N  --mult K  --spin DEG  --exposure F  --out PATH
// (--mult 3 gives a nephroid, 4 a three-cusped curve, and so on.)

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <string>
#include <vector>

#include <zlib.h>

namespace {

constexpr double kPi = 3.14159265358979323846;

struct Vec {
    double x = 0, y = 0;
};

struct Rgb {
    double r = 0, g = 0, b = 0;
};

// h in degrees, s and v in [0,1].
Rgb hsv(double h, double s, double v) {
    h = std::fmod(std::fmod(h, 360.0) + 360.0, 360.0) / 60.0;
    double c = v * s;
    double x = c * (1 - std::fabs(std::fmod(h, 2.0) - 1));
    double m = v - c;
    switch (static_cast<int>(h)) {
        case 0: return {c + m, x + m, m};
        case 1: return {x + m, c + m, m};
        case 2: return {m, c + m, x + m};
        case 3: return {m, x + m, c + m};
        case 4: return {x + m, m, c + m};
        default: return {c + m, m, x + m};
    }
}

// Linear-light float canvas. Everything is drawn additively, like light.
class Canvas {
public:
    Canvas(int w, int h) : w_(w), h_(h), px_(static_cast<size_t>(w) * h * 3, 0.f) {}

    int width() const { return w_; }
    int height() const { return h_; }

    // Bilinear splat, so lines land smooth without a separate AA pass.
    void splat(double x, double y, Rgb c) {
        int x0 = static_cast<int>(std::floor(x));
        int y0 = static_cast<int>(std::floor(y));
        double fx = x - x0, fy = y - y0;
        for (int dy = 0; dy < 2; ++dy) {
            int yi = y0 + dy;
            if (yi < 0 || yi >= h_) continue;
            double wy = dy ? fy : 1 - fy;
            for (int dx = 0; dx < 2; ++dx) {
                int xi = x0 + dx;
                if (xi < 0 || xi >= w_) continue;
                double w = wy * (dx ? fx : 1 - fx);
                float* p = &px_[(static_cast<size_t>(yi) * w_ + xi) * 3];
                p[0] += static_cast<float>(c.r * w);
                p[1] += static_cast<float>(c.g * w);
                p[2] += static_cast<float>(c.b * w);
            }
        }
    }

    // Constant brightness per unit length, so long chords do not go dim.
    void line(Vec a, Vec b, Rgb c, double intensity) {
        constexpr double kSamplesPerPixel = 1.7;
        double len = std::hypot(b.x - a.x, b.y - a.y);
        int steps = std::max(2, static_cast<int>(std::ceil(len * kSamplesPerPixel)));
        double e = intensity / kSamplesPerPixel;
        for (int i = 0; i <= steps; ++i) {
            double t = static_cast<double>(i) / steps;
            splat(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t, {c.r * e, c.g * e, c.b * e});
        }
    }

    float* row(int y) { return &px_[static_cast<size_t>(y) * w_ * 3]; }
    const float* row(int y) const { return &px_[static_cast<size_t>(y) * w_ * 3]; }

    // Box downsample by an integer factor (the supersampling resolve).
    Canvas resolve(int factor) const {
        Canvas out(w_ / factor, h_ / factor);
        double inv = 1.0 / (factor * factor);
        for (int y = 0; y < out.h_; ++y) {
            for (int x = 0; x < out.w_; ++x) {
                double acc[3] = {0, 0, 0};
                for (int sy = 0; sy < factor; ++sy) {
                    const float* src = &px_[(static_cast<size_t>(y * factor + sy) * w_ + x * factor) * 3];
                    for (int sx = 0; sx < factor; ++sx) {
                        acc[0] += src[sx * 3 + 0];
                        acc[1] += src[sx * 3 + 1];
                        acc[2] += src[sx * 3 + 2];
                    }
                }
                float* dst = &out.px_[(static_cast<size_t>(y) * out.w_ + x) * 3];
                for (int k = 0; k < 3; ++k) dst[k] = static_cast<float>(acc[k] * inv);
            }
        }
        return out;
    }

    // Cheap bloom: a few separable box blurs approximate a gaussian halo.
    void bloom(int radius, int passes, double amount) {
        std::vector<float> glow = px_;
        std::vector<float> tmp(px_.size());
        for (int p = 0; p < passes; ++p) {
            blurAxis(glow, tmp, radius, true);
            blurAxis(tmp, glow, radius, false);
        }
        for (size_t i = 0; i < px_.size(); ++i) px_[i] += static_cast<float>(glow[i] * amount);
    }

private:
    void blurAxis(const std::vector<float>& src, std::vector<float>& dst, int r, bool horizontal) const {
        int outer = horizontal ? h_ : w_;
        int inner = horizontal ? w_ : h_;
        double norm = 1.0 / (2 * r + 1);
        for (int o = 0; o < outer; ++o) {
            auto at = [&](int i) -> size_t {
                int x = horizontal ? i : o;
                int y = horizontal ? o : i;
                return (static_cast<size_t>(y) * w_ + x) * 3;
            };
            double sum[3] = {0, 0, 0};
            for (int i = -r; i <= r; ++i) {
                size_t s = at(std::clamp(i, 0, inner - 1));
                for (int k = 0; k < 3; ++k) sum[k] += src[s + k];
            }
            for (int i = 0; i < inner; ++i) {
                size_t d = at(i);
                for (int k = 0; k < 3; ++k) dst[d + k] = static_cast<float>(sum[k] * norm);
                size_t add = at(std::clamp(i + r + 1, 0, inner - 1));
                size_t sub = at(std::clamp(i - r, 0, inner - 1));
                for (int k = 0; k < 3; ++k) sum[k] += src[add + k] - src[sub + k];
            }
        }
    }

    int w_, h_;
    std::vector<float> px_;
};

void push32(std::vector<uint8_t>& v, uint32_t x) {
    v.push_back(static_cast<uint8_t>(x >> 24));
    v.push_back(static_cast<uint8_t>(x >> 16));
    v.push_back(static_cast<uint8_t>(x >> 8));
    v.push_back(static_cast<uint8_t>(x));
}

void writeChunk(std::FILE* f, const char* type, const std::vector<uint8_t>& data) {
    std::vector<uint8_t> head;
    push32(head, static_cast<uint32_t>(data.size()));
    std::fwrite(head.data(), 1, head.size(), f);
    std::fwrite(type, 1, 4, f);
    std::fwrite(data.data(), 1, data.size(), f);
    uLong crc = crc32(0L, reinterpret_cast<const Bytef*>(type), 4);
    if (!data.empty()) crc = crc32(crc, data.data(), static_cast<uInt>(data.size()));
    std::vector<uint8_t> tail;
    push32(tail, static_cast<uint32_t>(crc));
    std::fwrite(tail.data(), 1, tail.size(), f);
}

bool writePng(const std::string& path, int w, int h, const std::vector<uint8_t>& rgb) {
    // One filter byte (0 = None) in front of every scanline, then deflate.
    std::vector<uint8_t> raw;
    raw.reserve(static_cast<size_t>(h) * (1 + w * 3));
    for (int y = 0; y < h; ++y) {
        raw.push_back(0);
        const uint8_t* src = &rgb[static_cast<size_t>(y) * w * 3];
        raw.insert(raw.end(), src, src + static_cast<size_t>(w) * 3);
    }

    uLongf zlen = compressBound(static_cast<uLong>(raw.size()));
    std::vector<uint8_t> z(zlen);
    if (compress2(z.data(), &zlen, raw.data(), static_cast<uLong>(raw.size()), 9) != Z_OK) return false;
    z.resize(zlen);

    std::FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return false;
    const uint8_t sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    std::fwrite(sig, 1, 8, f);

    std::vector<uint8_t> ihdr;
    push32(ihdr, static_cast<uint32_t>(w));
    push32(ihdr, static_cast<uint32_t>(h));
    ihdr.insert(ihdr.end(), {8, 2, 0, 0, 0});  // 8-bit, truecolor, no interlace
    writeChunk(f, "IHDR", ihdr);
    writeChunk(f, "IDAT", z);
    writeChunk(f, "IEND", {});
    std::fclose(f);
    return true;
}

struct Options {
    int size = 1400;
    int lines = 560;
    double mult = 2.0;   // the "times table" multiplier
    // The cusp sits opposite the spin direction, so -90 stands the curve up as
    // a valentine: dimple at the top, point at the bottom.
    double spin = -90.0;
    double ink = 5.0;  // scales chord brightness; too high and the hues wash to white
    double exposure = 2.0;
    std::string out = "cardioid.png";
};

}  // namespace

int main(int argc, char** argv) {
    Options opt;
    for (int i = 1; i < argc; ++i) {
        std::string a = argv[i];
        auto next = [&]() -> std::string { return i + 1 < argc ? argv[++i] : ""; };
        if (a == "--size") opt.size = std::stoi(next());
        else if (a == "--lines") opt.lines = std::stoi(next());
        else if (a == "--mult") opt.mult = std::stod(next());
        else if (a == "--spin") opt.spin = std::stod(next());
        else if (a == "--ink") opt.ink = std::stod(next());
        else if (a == "--exposure") opt.exposure = std::stod(next());
        else if (a == "--out") opt.out = next();
        else {
            std::fprintf(stderr, "usage: %s [--size N] [--lines N] [--mult K] [--spin DEG]"
                                 " [--ink F] [--exposure F] [--out PATH]\n", argv[0]);
            return 2;
        }
    }

    constexpr int kSuper = 2;  // supersample factor
    const int dim = opt.size * kSuper;
    Canvas canvas(dim, dim);

    const double cx = dim * 0.5;
    const double cy = dim * 0.5;
    const double radius = dim * 0.385;
    const double spin = opt.spin * kPi / 180.0;

    // World space is y-up; the canvas is y-down. Rotate, scale, flip on the way in.
    auto toPixel = [&](Vec v) -> Vec {
        double x = v.x * std::cos(spin) - v.y * std::sin(spin);
        double y = v.x * std::sin(spin) + v.y * std::cos(spin);
        return {cx + x * radius, cy - y * radius};
    };
    auto onCircle = [](double t) -> Vec { return {std::cos(t), std::sin(t)}; };

    // 1. The chord web. Its envelope is the curve; the color sweeps with t.
    for (int i = 0; i < opt.lines; ++i) {
        double t = 2 * kPi * i / opt.lines;
        Vec a = toPixel(onCircle(t));
        Vec b = toPixel(onCircle(opt.mult * t));
        // Two offset hues per chord give the web a shot-silk shimmer.
        double hue = t * 180.0 / kPi + 205.0;
        canvas.line(a, b, hsv(hue, 0.95, 1.0), 0.011 * opt.ink);
        canvas.line(a, b, hsv(hue + 45.0, 0.85, 1.0), 0.005 * opt.ink);
    }

    // 2. The rim the chords hang from, kept faint.
    {
        const int segs = 3000;
        for (int i = 0; i < segs; ++i) {
            double t0 = 2 * kPi * i / segs, t1 = 2 * kPi * (i + 1) / segs;
            canvas.line(toPixel(onCircle(t0)), toPixel(onCircle(t1)),
                        hsv(t0 * 180.0 / kPi + 205.0, 0.45, 1.0), 0.22);
        }
    }

    // 3. The analytic envelope, drawn bright on top. For multiplier k the
    //    envelope of the chord family is the epicycloid
    //      P(t) = k/(k+1) * (cos t, sin t) + 1/(k+1) * (cos kt, sin kt),
    //    which for k = 2 is the cardioid.
    {
        const int segs = 6000;
        const double w0 = opt.mult / (opt.mult + 1.0);
        const double w1 = 1.0 / (opt.mult + 1.0);
        auto envelope = [&](double t) -> Vec {
            Vec a = onCircle(t);
            Vec b = onCircle(opt.mult * t);
            return {w0 * a.x + w1 * b.x, w0 * a.y + w1 * b.y};
        };
        for (int i = 0; i < segs; ++i) {
            double t0 = 2 * kPi * i / segs, t1 = 2 * kPi * (i + 1) / segs;
            Rgb c = hsv(t0 * 180.0 / kPi + 205.0, 0.62, 1.0);
            canvas.line(toPixel(envelope(t0)), toPixel(envelope(t1)), c, 0.85);
            // A whiter core inside the colored stroke.
            canvas.line(toPixel(envelope(t0)), toPixel(envelope(t1)),
                        {c.r * 0.35 + 0.65, c.g * 0.35 + 0.65, c.b * 0.35 + 0.65}, 0.30);
        }
    }

    Canvas img = canvas.resolve(kSuper);
    img.bloom(/*radius=*/std::max(2, opt.size / 300), /*passes=*/2, /*amount=*/0.30);

    // Composite over a deep vignetted background, tone map, then gamma encode.
    const int w = img.width(), h = img.height();
    std::vector<uint8_t> rgb(static_cast<size_t>(w) * h * 3);
    for (int y = 0; y < h; ++y) {
        const float* src = img.row(y);
        for (int x = 0; x < w; ++x) {
            double nx = (x - w * 0.5) / (w * 0.5);
            double ny = (y - h * 0.5) / (h * 0.5);
            double d = std::min(1.0, std::hypot(nx, ny));
            double fade = 1.0 - d * d;
            double bg[3] = {0.014 * fade + 0.003, 0.008 * fade + 0.002, 0.034 * fade + 0.008};

            for (int k = 0; k < 3; ++k) {
                double v = src[x * 3 + k] + bg[k];
                v = 1.0 - std::exp(-v * opt.exposure);          // filmic-ish rolloff
                v = std::pow(std::clamp(v, 0.0, 1.0), 1.0 / 2.2);  // to sRGB
                rgb[(static_cast<size_t>(y) * w + x) * 3 + k] =
                    static_cast<uint8_t>(std::lround(v * 255.0));
            }
        }
    }

    if (!writePng(opt.out, w, h, rgb)) {
        std::fprintf(stderr, "failed to write %s\n", opt.out.c_str());
        return 1;
    }
    std::printf("wrote %s (%dx%d, %d chords, mult %g)\n", opt.out.c_str(), w, h, opt.lines, opt.mult);
    return 0;
}
