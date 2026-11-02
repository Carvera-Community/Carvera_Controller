/* Native stock carving: remove material from the stock as the cutter moves, and
 * turn the remaining stock into triangle meshes for display.
 *
 * "Stock" is the block of material being machined. Three models are available,
 * each trading accuracy for speed:
 *   heightmap   - one leftover top Z per XY cell (fast, but no undercuts)
 *   cylindrical - one leftover radius per (X, angle) cell, for rotary / lathe-style work
 *   voxel       - 3D cubes, handles undercuts and a spinning A axis
 *
 * The "tool profile" is the cutter's side view: its radius at each height above the tip.
 * Each carve call receives a batch of moves, where a move is the tip travelling p0 -> p1.
 *
 * C99 only: no NumPy headers, no OpenMP, no VLAs.
 */
#ifndef CARVERA_STOCK_CARVE_H
#define CARVERA_STOCK_CARVE_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

#define SC_INF 1.0e30
#define SC_OUTSIDE (-1.0e30) /* heightmap cell that holds no stock */

/* ------------------------------------------------------------------------- */
/* Tool shape                                                                */
/* ------------------------------------------------------------------------- */

typedef struct ScProfile {
    const double *zs; /* heights above the tip, bottom to top */
    const double *rs; /* tool radius at each height */
    int n;
    double max_r;   /* widest radius: cells farther away than this can't be touched */
    double flute_z; /* cutting length (last z sample) */
    double const_r; /* the radius if the tool is a plain cylinder (end mill), else < 0 */
    int mono_r;     /* 1 if the radius never shrinks going up the tool */
} ScProfile;

/* Fill the derived fields (max_r, const_r, ...) from the raw sample arrays. */
void sc_profile_prepare(ScProfile *p, const double *zs, const double *rs, int n);

/* ------------------------------------------------------------------------- */
/* Laser decal: engraving marks painted on top of the stock                  */
/* ------------------------------------------------------------------------- */

/* Optional log of which decal texels changed, so the host only re-uploads those.
 * If the log fills up, `overflow` is set and the host must refresh everything.
 */
typedef struct ScLaserDirty {
    int32_t *iu;
    int32_t *iv;
    int cap; /* capacity of iu / iv */
    int n;   /* entries used */
    int overflow;
} ScLaserDirty;

/* A 2D intensity image in world space. `u` is X. `v` is Y on flat stock, or the angle
 * in degrees around the rotation axis on cylindrical stock.
 */
typedef struct ScLaserDecal {
    uint8_t *intensity; /* nx * nv texels, 0 = untouched */
    int nx;
    int nv;
    double cell_u;
    double cell_v;
    double origin_u;
    double origin_v;
    int wrap_v;      /* 1 when v is an angle that wraps around */
    double v_period; /* length of one turn in v (360 for degrees) */
    double v_scale;  /* converts a v distance to mm, so beams stay round on cylinders */
    ScLaserDirty *dirty; /* optional; NULL skips logging */
} ScLaserDecal;

/* Optional "is there stock here?" test so a beam does not paint empty air.
 * kind 0: no test. 1: heightmap top Z. 2: cylindrical leftover radius.
 * `z_or_r` on each paint segment is the beam Z (heightmap) or min tool radius (cylindrical).
 */
typedef struct ScLaserOcc {
    int kind;
    const float *data;
    int nx;
    int nv;
    double min_x;
    double min_y;
    double cell;
    double d_theta; /* angle step in degrees (cylindrical) */
    double period;
} ScLaserOcc;

/* ------------------------------------------------------------------------- */
/* Heightmap and cylindrical carving                                         */
/* ------------------------------------------------------------------------- */

/* What a carve call reports back. Every field is optional. */
typedef struct ScCarveOutputs {
    uint8_t *changed_mask; /* set to 1 for every cell that was lowered */
    uint8_t *tile_mask;    /* set to 1 for every tile (tile x tile cells) that contains a lowered cell */
    int tile;              /* tile edge length, in cells */
    int tile_stride;       /* tiles along the second grid axis: tile (tx, ty) lives at tx * tile_stride + ty */
    ScLaserDecal *laser;   /* engraving to wipe wherever the stock was cut */
    int *laser_changed;    /* set to 1 if any laser texel was wiped */
} ScCarveOutputs;

/* Grid of leftover top heights, indexed [ix * ny + iy]. Cell centers sit at min + (i + 0.5) * cell. */
typedef struct ScHeightGrid {
    float *heights;
    int nx, ny;
    double min_x, min_y;
    double min_z; /* the cut never goes below this */
    double cell;
} ScHeightGrid;

/* Grid of leftover radii around the A axis, indexed [ix * n_theta + itheta]. Angle bin i covers
 * [i * d_theta, (i + 1) * d_theta) degrees; sin_t / cos_t hold the sin / cos of each bin's angle.
 */
typedef struct ScCylGrid {
    float *radii;
    int nx, n_theta;
    double min_x;
    double cell;
    double d_theta;
    double axis_y, axis_z; /* where the rotation axis sits (it is parallel to X) */
    double stock_radius;
    const double *sin_t;
    const double *cos_t;
} ScCylGrid;

/* Lower the leftover heights for moves p0[i] -> p1[i] (each one is x, y, z). Returns 0. */
int sc_heightmap_carve(
    const ScHeightGrid *grid,
    const double *p0,
    const double *p1,
    int nseg,
    const ScProfile *profile,
    const ScCarveOutputs *out,
    double *volumes);

/* Lower the leftover radii. a0[i] / a1[i] are the A-axis angles (degrees) at the two ends of move i.
 * Returns 0, or -1 if memory ran out.
 */
int sc_cylindrical_carve(
    const ScCylGrid *grid,
    const double *p0,
    const double *p1,
    const double *a0,
    const double *a1,
    int nseg,
    const ScProfile *profile,
    const ScCarveOutputs *out,
    double *volumes);

/* ------------------------------------------------------------------------- */
/* Laser painting                                                            */
/* ------------------------------------------------------------------------- */

/* Paint each segment as its own capsule (a thick line with round ends). Segments with burn == 0 are skipped.
 * `allow`, when set, is a uint8 window that restricts painting to its non-zero texels; its [0, 0]
 * lies at decal index (allow_u0, allow_v0). It only applies to the first segment.
 * Returns 0. Sets *changed when a texel is raised.
 */
int sc_laser_paint(
    ScLaserDecal *map,
    const double *u0,
    const double *v0,
    const double *u1,
    const double *v1,
    const uint8_t *burn,
    const double *z_or_r,
    int nseg,
    double radius,
    const uint8_t *allow,
    int allow_u0,
    int allow_v0,
    int allow_rows,
    int allow_cols,
    const ScLaserOcc *occ,
    int *changed);

/* Zero a capsule per segment (a mill passing over an engraving erases it on the voxel stock). */
int sc_laser_clear_capsules(
    ScLaserDecal *map,
    const double *u0,
    const double *v0,
    const double *u1,
    const double *v1,
    int nseg,
    double radius,
    int *changed);

/* Zero the laser texels whose centers fall inside one cell of a (coarser) stock grid.
 * The stock cell is (ix, coarse_iv). `wrap_v` selects cylindrical vs planar clearing.
 * `coarse_nv` is the stock angle-bin count used only on the wrap path; <= 0 is one bin.
 */
void sc_laser_clear_coarse_cell(
    ScLaserDecal *laser,
    int ix,
    int coarse_iv,
    double coarse_origin_u,
    double coarse_origin_v,
    double coarse_du,
    double coarse_dv,
    int coarse_nv,
    int *changed);

/* ------------------------------------------------------------------------- */
/* Meshing                                                                   */
/* ------------------------------------------------------------------------- */

/* One Kivy mesh: 12 floats per vertex (pos, normal, color, uv), uint16 indices. */
typedef struct ScMeshPart {
    float *verts;
    uint16_t *indices;
    int nverts;
    int nindices;
} ScMeshPart;

/* A mesh can need more vertices than a uint16 index can address, so the result is a list of parts. */
typedef struct ScMeshBatch {
    ScMeshPart *parts;
    int nparts;
    int cap;
} ScMeshBatch;

void sc_mesh_batch_free(ScMeshBatch *batch);

/* Weld a heightmap window. `patch` is the (gw+2) by (gh+2) halo around cells
 * [0, gw) x [0, gh), row-major, matching NumPy C order. Flat corners share
 * vertices; steps keep crisp per-cell tops with a vertical skirt for every
 * height difference, so the shell is watertight.
 * Returns 0, or -1 on allocation failure.
 */
int sc_mesh_heightmap(
    const float *patch,
    int gw,
    int gh,
    int x0,
    int y0,
    int grid_nx,
    int grid_ny,
    double origin_x,
    double origin_y,
    double min_z,
    double cell,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out);

/* Weld a cylindrical shell. `radii` is (nx, n_theta) starting at global X
 * index `ix0` of a field `nx_total` wide. Caps are separate vertices so their
 * ±X normals are not welded into the radial shell. Returns 0, or -1.
 */
int sc_mesh_cylinder(
    const float *radii,
    int nx,
    int n_theta,
    int ix0,
    int nx_total,
    double min_x,
    double cell,
    double axis_y,
    double axis_z,
    const double *sin_t,
    const double *cos_t,
    double floor_r,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out);

/* Greedy exposed faces of one voxel chunk.
 * `occ` NULL means every in-bounds voxel is solid. `valid` NULL means all are
 * in bounds. For each of the six chunk sides (+X, -X, +Y, -Y, +Z, -Z), face_mode says what lies
 * beyond the chunk: 0 empty, 1 solid, 2 `faces[i]`, a uint8 (cs, cs) occupancy of the neighbor's
 * touching layer. Returns 0, or -1.
 */
int sc_mesh_voxel_chunk(
    const uint8_t *occ,
    const uint8_t *valid,
    int cs,
    const int face_mode[6],
    const uint8_t *const faces[6],
    double ox,
    double oy,
    double oz,
    double voxel,
    double cr,
    double cg,
    double cb,
    double ca,
    ScMeshBatch *out);

/* ------------------------------------------------------------------------- */
/* Voxel carving                                                             */
/* ------------------------------------------------------------------------- */

/* Voxel grid layout. Cubes are grouped into chunks of `chunk`^3 that the host loads on demand. */
typedef struct ScVoxelGrid {
    double min_x, min_y, min_z;
    double voxel;      /* cube edge length */
    int chunk;         /* cubes per chunk edge */
    int nx, ny, nz;    /* grid size in cubes */
    int ncx, ncy, ncz; /* grid size in chunks */
} ScVoxelGrid;

/* One loaded chunk. `data` has chunk^3 bytes, 1 = the cube still holds material. */
typedef struct ScChunkRec {
    int cx, cy, cz;
    uint8_t *data;
    int solid;    /* cubes still holding material */
    int was_full; /* 1 if the chunk started fully solid */
    int hits;     /* cubes removed during this batch */
} ScChunkRec;

/* Ask the host for a chunk. Return 1 and fill data/solid/was_full, or 0 if the chunk is empty. */
typedef int (*ScGetChunkFn)(void *ctx, int cx, int cy, int cz, uint8_t **data, int *solid, int *was_full);

/* Delete cubes inside the tool. `get_chunk` loads chunk occupancy from the host.
 * On return `*touched` lists every chunk that was loaded (free it with free()).
 * Returns 0.
 */
int sc_voxel_carve(
    const ScVoxelGrid *grid,
    const double *p0,
    const double *p1,
    const double *a0,
    const double *a1,
    int nseg,
    const ScProfile *profile,
    ScGetChunkFn get_chunk,
    void *ctx,
    ScChunkRec **touched,
    int *n_touched,
    double *volumes);

#ifdef __cplusplus
}
#endif

#endif
