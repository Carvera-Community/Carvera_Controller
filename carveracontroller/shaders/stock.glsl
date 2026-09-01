// Translucent stock block (AABB) with simple diffuse shading.
// Drawn in two passes (back faces, then front) for correct translucency.
// Wireframe edges use the same shader with a solid edge color (no lighting).

---vertex
$HEADER$

attribute vec3 v_pos;
attribute vec3 v_normal;
attribute vec4 v_color;

uniform mat4 center_offset;
uniform mat4 view_mat;
uniform mat4 proj_mat;
uniform mat4 rotation_mat;

varying vec3 normal_vec;
varying vec4 stock_color;

void main()
{
    vec4 rotated = rotation_mat * vec4(v_pos, 1.0);
    vec4 world = center_offset * rotated;
    vec4 eye_pos = view_mat * world;
    normal_vec = (view_mat * rotation_mat * vec4(v_normal, 0.0)).xyz;
    stock_color = v_color;
    tex_coord0 = vec2(0.0);
    gl_Position = proj_mat * eye_pos;
}

---fragment
$HEADER$

varying vec3 normal_vec;
varying vec4 stock_color;

uniform float use_lighting;

void main()
{
    vec3 color = stock_color.rgb;
    if (use_lighting > 0.5) {
        vec3 n = normalize(normal_vec);
        float shade = 0.40 + 0.60 * abs(dot(n, normalize(vec3(0.35, 0.55, 1.0))));
        color = color * shade;
    }
    gl_FragColor = vec4(color, stock_color.a) * texture2D(texture0, tex_coord0);
}
