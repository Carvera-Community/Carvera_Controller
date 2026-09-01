// Opaque fixture-plate mesh (lit albedo + metallic + roughness).

---vertex
$HEADER$

attribute vec3 v_pos;
attribute vec3 v_normal;
attribute vec4 v_color;

uniform mat4 center_offset;
uniform mat4 view_mat;
uniform mat4 proj_mat;
uniform mat4 rotation_mat;
uniform vec3 model_offset;

varying vec3 normal_vec;
varying vec4 bed_color;
varying vec3 view_pos;

void main()
{
    vec4 local = vec4(v_pos + model_offset, 1.0);
    vec4 rotated = rotation_mat * local;
    vec4 world = center_offset * rotated;
    vec4 eye_pos = view_mat * world;
    view_pos = eye_pos.xyz;
    normal_vec = (view_mat * rotation_mat * vec4(v_normal, 0.0)).xyz;
    bed_color = v_color;
    tex_coord0 = vec2(0.0);
    gl_Position = proj_mat * eye_pos;
}

---fragment
$HEADER$

varying vec3 normal_vec;
varying vec4 bed_color;
varying vec3 view_pos;

uniform float metallic;
uniform float roughness;

void main()
{
    vec3 n = normalize(normal_vec);
    vec3 light = normalize(vec3(0.35, 0.55, 1.0));
    float ndl = abs(dot(n, light));

    vec3 albedo = bed_color.rgb;
    float metal = clamp(metallic, 0.0, 1.0);
    float rough = clamp(roughness, 0.04, 1.0);
    vec3 f0 = mix(vec3(0.04), albedo, metal);
    float wrap = 0.18 + 0.82 * ndl;
    vec3 diffuse = albedo * (1.0 - metal) * wrap;

    vec3 view_dir = normalize(-view_pos);
    if (dot(n, view_dir) < 0.0) {
        n = -n;
    }
    vec3 half_vec = normalize(light + view_dir);
    float ndh = max(dot(n, half_vec), 0.0);
    float ndv = max(dot(n, view_dir), 0.0);

    float spec_exp = min(exp2(10.0 * (1.0 - rough)), 256.0);
    float spec = pow(ndh, spec_exp);
    float fresnel_w = pow(clamp(1.0 - ndv, 0.0, 1.0), 5.0);
    vec3 fresnel = f0 + (vec3(1.0) - f0) * fresnel_w;
    vec3 specular = fresnel * spec;

    vec3 metal_fill = f0 * (0.32 + 0.68 * ndl) + f0 * fresnel_w * 0.45;
    vec3 color = diffuse + mix(vec3(0.0), metal_fill, metal) + specular;
    gl_FragColor = vec4(color, 1.0) * texture2D(texture0, tex_coord0);
}
