/* simple.glsl

simple diffuse lighting based on laberts cosine law; see e.g.:
    http://en.wikipedia.org/wiki/Lambertian_reflectance
    http://en.wikipedia.org/wiki/Lambert%27s_cosine_law
*/
---VERTEX SHADER-------------------------------------------------------
$HEADER$
// #ifdef GL_ES
//     precision highp float;
// #endif

attribute vec3  v_pos;
attribute vec3  v_normal;

uniform vec3 offset;// = vec3(0,0,0);
uniform mat4 rotation;

// uniform mat4 modelview_mat;
// uniform mat4 projection_mat;

varying vec4 normal_vec;
varying vec4 vertex_pos;

void main (void) {
    //compute vertex position in eye_space and normalize normal vector
    vec4 rot_pos = rotation * vec4(v_pos,1.0);
    vec3 tmp_pos = rot_pos.xyz + offset;
    vec4 pos = modelview_mat * vec4(tmp_pos,1.0);
    vertex_pos = pos;
    normal_vec = vec4(v_normal,0.0);
    gl_Position = projection_mat * pos;
}


---FRAGMENT SHADER-----------------------------------------------------
$HEADER$
// #ifdef GL_ES
//     precision highp float;
// #endif

varying vec4 normal_vec;
varying vec4 vertex_pos;


void main (void){
    float dot_val = dot(normal_vec.xyz,vec3(1.0,1.0,1.0));
    vec3 color= vec3(0.3,0.3,1.0)*abs(dot_val);
    
    gl_FragColor = vec4( color,0.3)*texture2D(texture0, tex_coord0);
}
