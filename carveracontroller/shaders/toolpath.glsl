// G-code toolpath line shader (line_strip with playback trim and visibility filters)

---vertex
$HEADER$
attribute vec3 position;
attribute vec3 color_att;
attribute float type;
attribute float vertex_id;
attribute float distance_id;
attribute float vertex_tool;
attribute float vertex_feed;

uniform mat4 center_offset;
uniform mat4 rotation_mat;
uniform mat4 view_mat;
uniform mat4 proj_mat;

varying vec3 vs_color;
varying float vs_vertex_id;
varying float vs_distance_id;
varying float vs_vertex_type;
varying float vs_vertex_feed;
varying float vs_vertex_z;

void main()
{
    vs_color = color_att;
    vs_vertex_id = vertex_id;
    vs_vertex_type = vertex_tool;
    vs_vertex_feed = vertex_feed;
    vs_vertex_z = position.z;
    vs_distance_id = distance_id;

    tex_coord0 = vec2(0.0);
    vec4 world_pos = vec4(position, 1.0);
    if (vertex_id < 0.0) {
        gl_Position = proj_mat * view_mat * center_offset * world_pos;
    } else {
        gl_Position = proj_mat * view_mat * center_offset * rotation_mat * world_pos;
    }
}

---fragment
$HEADER$

varying vec3 vs_color;
varying float vs_vertex_id;
varying float vs_distance_id;
varying float vs_vertex_type;
varying float vs_vertex_feed;
varying float vs_vertex_z;

// Kivy uniforms are float-only; -1 means show the full toolpath
uniform float display_count;
// 0 = move type, 1 = tool, 2 = feed speed, 3 = Z height
uniform float color_scheme;
uniform float feed_min;
uniform float feed_max;
uniform float z_min;
uniform float z_max;

// Move-type / shared rapid visibility (1 = show, 0 = hide)
uniform float show_rapid;
uniform float show_feed;

// Speed / height bucket bitmasks (bits 0..10); 2047 = all 11 buckets visible
uniform float speed_bucket_bits;
uniform float z_bucket_bits;

// Per-tool filter: up to 24 tool ids packed into 6 vec4s; bit i of tool_bits
// means tool_ids[i] is visible. tool_filter_count == 0 means show all tools.
uniform float tool_filter_count;
uniform float tool_bits;
uniform vec4 tool_ids0;
uniform vec4 tool_ids1;
uniform vec4 tool_ids2;
uniform vec4 tool_ids3;
uniform vec4 tool_ids4;
uniform vec4 tool_ids5;

vec3 tool_palette_color(float idx)
{
    float i = mod(floor(idx + 0.5), 10.0);
    if (abs(i - 0.0) < 0.5) return vec3(0.406684, 0.735902, 0.235489);
    if (abs(i - 1.0) < 0.5) return vec3(0.000000, 0.459774, 0.840728);
    if (abs(i - 2.0) < 0.5) return vec3(0.779915, 0.319537, 0.130857);
    if (abs(i - 3.0) < 0.5) return vec3(0.740127, 0.236840, 0.700182);
    if (abs(i - 4.0) < 0.5) return vec3(0.000000, 0.755849, 0.602221);
    if (abs(i - 5.0) < 0.5) return vec3(0.825216, 0.043248, 0.043248);
    if (abs(i - 6.0) < 0.5) return vec3(0.894806, 0.717161, 0.000000);
    if (abs(i - 7.0) < 0.5) return vec3(0.128923, 0.578319, 0.877916);
    if (abs(i - 8.0) < 0.5) return vec3(0.431518, 0.268501, 0.839063);
    return vec3(0.248716, 0.777237, 0.402157);
}

vec3 speed_colormap(float t)
{
    t = clamp(t, 0.0, 1.0);
    if (t < 0.33) {
        return mix(vec3(0.2, 0.4, 0.9), vec3(0.1, 0.7, 0.5), t / 0.33);
    }
    if (t < 0.66) {
        return mix(vec3(0.1, 0.7, 0.5), vec3(0.95, 0.85, 0.15), (t - 0.33) / 0.33);
    }
    return mix(vec3(0.95, 0.85, 0.15), vec3(0.9, 0.25, 0.2), (t - 0.66) / 0.34);
}

float tool_id_at(int i)
{
    if (i < 4) return tool_ids0[i];
    if (i < 8) return tool_ids1[i - 4];
    if (i < 12) return tool_ids2[i - 8];
    if (i < 16) return tool_ids3[i - 12];
    if (i < 20) return tool_ids4[i - 16];
    return tool_ids5[i - 20];
}

// Extract bit ``index`` from an integer stored in a float.
// Avoid pow(2.0, n): GPU pow is not exact and mis-reads high bits (e.g. bit 10
// of 2047), which hid paths until other bits were toggled.
bool float_bit_enabled(float bits, int index)
{
    float b = floor(bits + 0.5);
    for (int i = 0; i < 24; i++) {
        if (i == index) {
            return mod(b, 2.0) >= 0.5;
        }
        b = floor(b * 0.5);
    }
    return true;
}

bool is_tool_enabled(float vertex_type)
{
    float count = floor(tool_filter_count + 0.1);
    if (count < 0.5) {
        return true;
    }
    float vtype = floor(vertex_type + 0.1);
    for (int i = 0; i < 24; i++) {
        if (float(i) >= count) {
            break;
        }
        if (abs(vtype - floor(tool_id_at(i) + 0.1)) < 0.5) {
            return float_bit_enabled(tool_bits, i);
        }
    }
    // Tools not in the filter list stay visible (fail open).
    return true;
}

bool is_bucket_bit_enabled(float bits, float bucket_index)
{
    int idx = int(floor(bucket_index + 0.1));
    if (idx < 0) {
        idx = 0;
    }
    if (idx > 10) {
        idx = 10;
    }
    return float_bit_enabled(bits, idx);
}

bool is_rapid_move()
{
    // Match speed-scheme rapid detection; do not use interpolated vertex color.
    return vs_vertex_feed < 0.5;
}

void main()
{
    if (display_count > -1.0 && vs_distance_id > display_count) {
        discard;
    }

    if (!is_tool_enabled(vs_vertex_type)) {
        discard;
    }

    // Visibility filters from every color scheme stack (AND). Switching schemes
    // does not clear other schemes' filters. The spinner marks modified schemes
    // with a trailing '*'. Rapid is shared by Move type and Speed.
    bool rapid = is_rapid_move();
    if (rapid) {
        if (show_rapid < 0.5) {
            discard;
        }
    } else {
        if (show_feed < 0.5) {
            discard;
        }
        float feed_span = max(feed_max - feed_min, 1.0);
        float feed_t = clamp((vs_vertex_feed - feed_min) / feed_span, 0.0, 1.0);
        float speed_bucket = floor(feed_t * 10.0 + 0.5);
        if (speed_bucket > 10.0) {
            speed_bucket = 10.0;
        }
        if (!is_bucket_bit_enabled(speed_bucket_bits, speed_bucket)) {
            discard;
        }

        float z_span = z_max - z_min;
        if (z_span < 1e-6) {
            z_span = 1e-6;
        }
        float z_t = clamp((vs_vertex_z - z_min) / z_span, 0.0, 1.0);
        // Height legend: top = higher Z (t=1) as bucket 0, bottom = lower Z as bucket 10.
        float z_bucket = floor((1.0 - z_t) * 10.0 + 0.5);
        if (z_bucket > 10.0) {
            z_bucket = 10.0;
        }
        if (!is_bucket_bit_enabled(z_bucket_bits, z_bucket)) {
            discard;
        }
    }

    vec3 color;
    if (color_scheme < 0.5) {
        color = vs_color;
        // Rapid moves carry red in the vertex color; normalize to solid red
        if (color.r > 0.0) {
            color = vec3(1.0, 0.0, 0.0);
        }
    } else if (color_scheme < 1.5) {
        float tool_num = floor(vs_vertex_type + 0.5);
        float palette_idx = mod(tool_num - 1.0, 10.0);
        color = tool_palette_color(palette_idx);
    } else if (color_scheme < 2.5) {
        if (vs_vertex_feed < 0.5) {
            color = vec3(1.0, 0.0, 0.0);
        } else {
            float span = max(feed_max - feed_min, 1.0);
            float t = clamp((vs_vertex_feed - feed_min) / span, 0.0, 1.0);
            color = speed_colormap(t);
        }
    } else {
        // z_min/z_max are in scaled display units (mm * position_scale), not mm
        float span = z_max - z_min;
        if (span < 1e-6) {
            span = 1e-6;
        }
        float t = clamp((vs_vertex_z - z_min) / span, 0.0, 1.0);
        color = speed_colormap(t);
    }
    gl_FragColor = vec4(color, 1.0) * texture2D(texture0, tex_coord0);
}
