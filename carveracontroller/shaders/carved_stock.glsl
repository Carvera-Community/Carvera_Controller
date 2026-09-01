// Carved voxel chunk surface (lit opaque fill with height tint / material BRDF).

---vertex
$HEADER$

attribute vec3 v_pos;
attribute vec3 v_normal;
attribute vec4 v_color;

uniform mat4 center_offset;
uniform mat4 view_mat;
uniform mat4 proj_mat;
uniform mat4 rotation_mat;
uniform float vertex_scale;

varying vec3 normal_vec;
varying vec4 voxel_color;
varying float world_z;
varying vec3 stock_pos;
varying vec3 stock_n;
varying vec3 view_pos;

void main()
{
    vec3 scaled_pos = v_pos * vertex_scale;
    stock_pos = scaled_pos;
    stock_n = v_normal;
    vec4 rotated = rotation_mat * vec4(scaled_pos, 1.0);
    vec4 world = center_offset * rotated;
    vec4 eye_pos = view_mat * world;
    view_pos = eye_pos.xyz;
    normal_vec = (view_mat * rotation_mat * vec4(v_normal, 0.0)).xyz;
    voxel_color = v_color;
    // Height tint after A rotation so "up" stays machine Z, not stock-local Z.
    world_z = rotated.z;
    tex_coord0 = vec2(0.0);
    gl_Position = proj_mat * eye_pos;
}

---fragment
$HEADER$

varying vec3 normal_vec;
varying vec4 voxel_color;
varying float world_z;
varying vec3 stock_pos;
varying vec3 stock_n;
varying vec3 view_pos;

uniform float stock_z_min;
uniform float stock_z_max;
uniform sampler2D texture1;
uniform float laser_enabled;
uniform float laser_mode;
uniform vec2 stock_xy_min;
uniform vec2 stock_xy_span;
uniform vec2 axis_yz;
uniform vec3 surface_color;
uniform vec3 interior_color;
uniform float use_two_tone;
uniform float use_height_tint;
uniform float surface_z_eps;
uniform float cylindrical_skin;
uniform float stock_radius;
uniform float metallic;
uniform float interior_metallic;
uniform float roughness;
uniform float interior_roughness;

void main()
{
    vec3 n = normalize(normal_vec);
    vec3 light = normalize(vec3(0.35, 0.55, 1.0));
    // Two-sided diffuse so voxel pocket walls still read.
    float ndl = abs(dot(n, light));

    float is_surface = 1.0;
    vec3 base = surface_color;
    if (use_two_tone > 0.5) {
        float nlen = max(length(stock_n), 1e-6);
        if (cylindrical_skin > 0.5) {
            // Rotary: OD is the skin / end caps stay core
            vec2 d = stock_pos.yz - axis_yz;
            float r = length(d);
            float cap = step(0.35, abs(stock_n.x) / nlen);
            float outward = step(0.0, dot(stock_n.yz, d));
            float at_od = step(stock_radius - surface_z_eps, r);
            is_surface = (1.0 - cap) * outward * at_od;
        } else {
            // Thin layer at stock_z_max (PCB copper ~0.035 mm / bicolor skin).
            // stock_pos is unrotated so A-axis playback keeps foil on the stock face.
            float up_face = step(0.35, stock_n.z / nlen);
            float at_top = step(stock_z_max - surface_z_eps, stock_pos.z);
            is_surface = up_face * at_top;
        }
        base = mix(interior_color, surface_color, is_surface);
    }

    vec3 albedo = base;
    if (use_height_tint > 0.5) {
        // Darker toward stock bottom so coplanar pocket floors separate by depth.
        float z_span = max(stock_z_max - stock_z_min, 1e-6);
        float t = clamp((world_z - stock_z_min) / z_span, 0.0, 1.0);
        vec3 low = base * vec3(0.52, 0.48, 0.42);
        vec3 high = base * vec3(1.08, 1.05, 0.98);
        albedo = mix(low, high, t);
    }

    float metal = clamp(mix(interior_metallic, metallic, is_surface), 0.0, 1.0);
    float rough = clamp(mix(interior_roughness, roughness, is_surface), 0.04, 1.0);
    vec3 f0 = mix(vec3(0.04), albedo, metal);
    float wrap = 0.18 + 0.82 * ndl;
    vec3 diffuse = albedo * (1.0 - metal) * wrap;

    // Specular is single-sided; flip so the normal faces the camera.
    vec3 view_dir = normalize(-view_pos);
    if (dot(n, view_dir) < 0.0) {
        n = -n;
    }
    vec3 half_vec = normalize(light + view_dir);
    float ndh = max(dot(n, half_vec), 0.0);
    float ndv = max(dot(n, view_dir), 0.0);

    // Cap exponent so mediump GLES2 pow() stays stable even on glossy material
    float spec_exp = min(exp2(10.0 * (1.0 - rough)), 256.0);
    float spec = pow(ndh, spec_exp);
    float fresnel_w = pow(clamp(1.0 - ndv, 0.0, 1.0), 5.0);
    vec3 fresnel = f0 + (vec3(1.0) - f0) * fresnel_w;
    vec3 specular = fresnel * spec;

    // Prevents metals from becoming black off the top-down light
    vec3 metal_fill = f0 * (0.32 + 0.68 * ndl) + f0 * fresnel_w * 0.45;

    vec3 color = diffuse + mix(vec3(0.0), metal_fill, metal) + specular;
    if (laser_enabled > 0.5) {
        vec2 uv;
        float facing;
        if (laser_mode < 0.5) {
            uv = (stock_pos.xy - stock_xy_min) / max(stock_xy_span, vec2(1e-6));
            facing = step(0.35, stock_n.z / max(length(stock_n), 1e-6));
        } else {
            vec2 d = stock_pos.yz - axis_yz;
            float theta = atan(d.x, d.y);
            uv.x = (stock_pos.x - stock_xy_min.x) / max(stock_xy_span.x, 1e-6);
            uv.y = theta * 0.15915494309;  // 1/(2π)
            if (uv.y < 0.0) {
                uv.y += 1.0;
            }
            facing = step(0.0, dot(stock_n.yz, d));
        }
        float burn = texture2D(texture1, uv).r * facing;
        color = mix(color, color * vec3(0.22, 0.20, 0.18), burn);
    }
    gl_FragColor = vec4(color, voxel_color.a) * texture2D(texture0, tex_coord0);
}
