/* Voxel stock: cubes of material grouped into chunks. A cube is either there
 * or gone. Handles undercuts and A-axis rotation that the heightmap cannot.
 *
 * For every move we find the chunks the tool could touch, skip the ones that are
 * obviously out of reach, and delete every remaining cube whose center is inside the tool.
 */
#include "stock_carve_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SC_MAX_DA 2.0 /* split a move if A turns more than this many degrees */

/* ------------------------------------------------------------------------- */
/* 2D distance between a path and a chunk's footprint                        */
/* ------------------------------------------------------------------------- */

/* Which side of the line a->b the point c is on (the sign), or 0 if it is on the line. */
static double sc_orient(double ax, double ay, double bx, double by, double cx, double cy) {
    return (by - ay) * (cx - bx) - (bx - ax) * (cy - by);
}

/* True if q lies inside the bounding box of p and r. */
static int sc_in_box(double px, double py, double qx, double qy, double rx, double ry) {
    return fmin(px, rx) - 1e-12 <= qx && qx <= fmax(px, rx) + 1e-12 && fmin(py, ry) - 1e-12 <= qy &&
        qy <= fmax(py, ry) + 1e-12;
}

static int sc_opposite_signs(double a, double b) {
    return (a > 0.0 && b < 0.0) || (a < 0.0 && b > 0.0);
}

/* True if segment a-b touches segment c-d. */
static int sc_segments_intersect(
    double ax, double ay, double bx, double by, double cx, double cy, double dx, double dy) {
    double o1 = sc_orient(ax, ay, bx, by, cx, cy);
    double o2 = sc_orient(ax, ay, bx, by, dx, dy);
    double o3 = sc_orient(cx, cy, dx, dy, ax, ay);
    double o4 = sc_orient(cx, cy, dx, dy, bx, by);
    /* Each segment's endpoints are on opposite sides of the other: they cross. */
    if (sc_opposite_signs(o1, o2) && sc_opposite_signs(o3, o4)) {
        return 1;
    }
    /* Otherwise they can still touch if an endpoint lies on the other segment. */
    if (fabs(o1) <= 1e-12 && sc_in_box(ax, ay, cx, cy, bx, by)) {
        return 1;
    }
    if (fabs(o2) <= 1e-12 && sc_in_box(ax, ay, dx, dy, bx, by)) {
        return 1;
    }
    if (fabs(o3) <= 1e-12 && sc_in_box(cx, cy, ax, ay, dx, dy)) {
        return 1;
    }
    return fabs(o4) <= 1e-12 && sc_in_box(cx, cy, bx, by, dx, dy);
}

static double sc_point_to_box(double px, double py, double xmin, double ymin, double xmax, double ymax) {
    double cx = sc_clamp(px, xmin, xmax);
    double cy = sc_clamp(py, ymin, ymax);
    return hypot(px - cx, py - cy);
}

static double sc_point_to_seg(double px, double py, double ax, double ay, double bx, double by) {
    double abx = bx - ax;
    double aby = by - ay;
    double ab_len_sq = abx * abx + aby * aby;
    double t, qx, qy;
    if (ab_len_sq < 1e-18) {
        return hypot(px - ax, py - ay);
    }
    t = sc_clamp(((px - ax) * abx + (py - ay) * aby) / ab_len_sq, 0.0, 1.0);
    qx = ax + t * abx;
    qy = ay + t * aby;
    return hypot(px - qx, py - qy);
}

/* How close a 2D tool path a->b comes to a chunk's XY box. 0 means it overlaps. */
static double sc_segment_box_dist(
    double ax, double ay, double bx, double by, double xmin, double ymin, double xmax, double ymax) {
    double d;
    int e;
    double edges[4][4] = {
        {xmin, ymin, xmax, ymin},
        {xmax, ymin, xmax, ymax},
        {xmax, ymax, xmin, ymax},
        {xmin, ymax, xmin, ymin},
    };
    double corners[4][2] = {{xmin, ymin}, {xmax, ymin}, {xmax, ymax}, {xmin, ymax}};
    /* An end point inside the box, or the path crossing one of its edges, means they overlap. */
    if ((xmin <= ax && ax <= xmax && ymin <= ay && ay <= ymax) ||
        (xmin <= bx && bx <= xmax && ymin <= by && by <= ymax)) {
        return 0.0;
    }
    for (e = 0; e < 4; e++) {
        if (sc_segments_intersect(ax, ay, bx, by, edges[e][0], edges[e][1], edges[e][2], edges[e][3])) {
            return 0.0;
        }
    }
    /* Separate shapes: the closest approach involves an end point of the path or a corner of the box. */
    d = fmin(sc_point_to_box(ax, ay, xmin, ymin, xmax, ymax), sc_point_to_box(bx, by, xmin, ymin, xmax, ymax));
    for (e = 0; e < 4; e++) {
        double pd = sc_point_to_seg(corners[e][0], corners[e][1], ax, ay, bx, by);
        if (pd < d) {
            d = pd;
        }
    }
    return d;
}

/* ------------------------------------------------------------------------- */
/* A axis rotation                                                           */
/* ------------------------------------------------------------------------- */

/* Y/Z bounds of a box after rotating it around X (the box is given by its Y/Z extent; X is unaffected). */
static void sc_rotated_yz_bounds(
    double min_y,
    double min_z,
    double max_y,
    double max_z,
    double c,
    double s,
    double *o_min_y,
    double *o_min_z,
    double *o_max_y,
    double *o_max_z) {
    double ys[4], zs[4];
    int i, j, k = 0;
    for (i = 0; i < 2; i++) {
        for (j = 0; j < 2; j++) {
            sc_rotate_yz_cs(i ? max_y : min_y, j ? max_z : min_z, c, s, &ys[k], &zs[k]);
            k++;
        }
    }
    *o_min_y = ys[0];
    *o_max_y = ys[0];
    *o_min_z = zs[0];
    *o_max_z = zs[0];
    for (i = 1; i < 4; i++) {
        if (ys[i] < *o_min_y) {
            *o_min_y = ys[i];
        }
        if (ys[i] > *o_max_y) {
            *o_max_y = ys[i];
        }
        if (zs[i] < *o_min_z) {
            *o_min_z = zs[i];
        }
        if (zs[i] > *o_max_z) {
            *o_max_z = zs[i];
        }
    }
}

/* ------------------------------------------------------------------------- */
/* Chunk bookkeeping                                                         */
/* ------------------------------------------------------------------------- */

/* Chunks loaded so far in this batch. */
typedef struct ScChunkTable {
    ScChunkRec *items;
    int n;
    int cap;
} ScChunkTable;

/* Load a chunk from the host once, then reuse it for the rest of this batch.
 * Returns NULL if the host reports the chunk as empty.
 */
static ScChunkRec *sc_chunk_get(ScChunkTable *table, ScGetChunkFn get_chunk, void *ctx, int cx, int cy, int cz) {
    int i;
    ScChunkRec *rec;
    uint8_t *data = NULL;
    int solid = 0;
    int was_full = 0;
    for (i = 0; i < table->n; i++) {
        if (table->items[i].cx == cx && table->items[i].cy == cy && table->items[i].cz == cz) {
            return &table->items[i];
        }
    }
    if (!get_chunk(ctx, cx, cy, cz, &data, &solid, &was_full) || data == NULL) {
        return NULL;
    }
    if (table->n >= table->cap) {
        int cap = table->cap ? table->cap * 2 : 32;
        ScChunkRec *grown = (ScChunkRec *)realloc(table->items, (size_t)cap * sizeof(ScChunkRec));
        if (grown == NULL) {
            return NULL;
        }
        table->items = grown;
        table->cap = cap;
    }
    rec = &table->items[table->n++];
    rec->cx = cx;
    rec->cy = cy;
    rec->cz = cz;
    rec->data = data;
    rec->solid = solid;
    rec->was_full = was_full;
    rec->hits = 0;
    return rec;
}

/* Remove every cube in the chunk (padding cubes outside the grid were already empty). */
static void sc_chunk_clear_all(ScChunkRec *rec, int cs, int *removed) {
    size_t n = (size_t)cs * (size_t)cs * (size_t)cs;
    if (rec->solid > 0) {
        if (removed != NULL) {
            *removed += rec->solid;
        }
        rec->hits += rec->solid;
        rec->solid = 0;
    }
    memset(rec->data, 0, n);
}

/* Cube index range along one axis (in chunks) for a world-space interval [lo, hi].
 * Returns 0 if the interval starts beyond the end of the grid.
 */
static int sc_chunk_span(double lo, double hi, double origin, const ScVoxelGrid *grid, int n_cubes, int *c0, int *c1) {
    int i0 = (int)floor((lo - origin) / grid->voxel);
    int i1 = (int)floor((hi - origin) / grid->voxel);
    if (i0 < 0) {
        i0 = 0;
    }
    if (i1 > n_cubes - 1) {
        i1 = n_cubes - 1;
    }
    if (i0 > n_cubes - 1) {
        return 0;
    }
    *c0 = i0 / grid->chunk;
    *c1 = i1 / grid->chunk;
    return 1;
}

/* ------------------------------------------------------------------------- */
/* Carving one move at a fixed A angle                                       */
/* ------------------------------------------------------------------------- */

/* Everything the chunk tests of one fixed-angle move share. */
typedef struct ScVoxelPass {
    const ScVoxelGrid *grid;
    ScSegTool seg;
    int rotate; /* A is not zero: cubes are rotated into the tool's frame before testing */
    double cos_a, sin_a;
    double tip_z_lo, tip_z_hi; /* range of tip heights during the move, with a margin of one cube */
    double xy_reject;          /* chunks farther than this from the path in XY can't be touched */
    int allow_full_clear;      /* a fully covered chunk may be emptied without testing each cube */
    ScChunkTable *table;
    ScGetChunkFn get_chunk;
    void *ctx;
    int *removed; /* optional cubes deleted this move; NULL skips counting */
} ScVoxelPass;

/* True when every in-bounds cube center of this chunk sits inside a plain-cylinder sweep.
 * The swept volume is convex, so checking the 8 corners of the box of cube centers is enough.
 * Ball / V tools and a rotating A axis must not use this shortcut.
 */
static int sc_chunk_fully_inside_const_r(const ScVoxelGrid *grid, int cx, int cy, int cz, const ScSegTool *seg) {
    int cs = grid->chunk;
    double vs = grid->voxel;
    int nx_local = grid->nx - cx * cs;
    int ny_local = grid->ny - cy * cs;
    int nz_local = grid->nz - cz * cs;
    double x0, y0, z0, x1, y1, z1;
    int i;
    if (nx_local > cs) {
        nx_local = cs;
    }
    if (ny_local > cs) {
        ny_local = cs;
    }
    if (nz_local > cs) {
        nz_local = cs;
    }
    if (nx_local <= 0 || ny_local <= 0 || nz_local <= 0) {
        return 0;
    }
    /* Box of in-bounds cube centers (padding outside nx/ny/nz is ignored). */
    x0 = grid->min_x + ((double)(cx * cs) + 0.5) * vs;
    y0 = grid->min_y + ((double)(cy * cs) + 0.5) * vs;
    z0 = grid->min_z + ((double)(cz * cs) + 0.5) * vs;
    x1 = grid->min_x + ((double)(cx * cs + nx_local - 1) + 0.5) * vs;
    y1 = grid->min_y + ((double)(cy * cs + ny_local - 1) + 0.5) * vs;
    z1 = grid->min_z + ((double)(cz * cs + nz_local - 1) + 0.5) * vs;
    for (i = 0; i < 8; i++) {
        double x = (i & 1) ? x1 : x0;
        double y = (i & 2) ? y1 : y0;
        double z = (i & 4) ? z1 : z0;
        if (!sc_seg_tool_contains(seg, x, y, z)) {
            return 0;
        }
    }
    return 1;
}

/* Cheap test to rule out chunks the tool can't reach: wrong height, or too far from the path in XY. */
static int sc_chunk_in_reach(const ScVoxelPass *pass, int cx, int cy, int cz) {
    const ScVoxelGrid *grid = pass->grid;
    double chunk_len = grid->chunk * grid->voxel;
    double ox = grid->min_x + (double)cx * grid->chunk * grid->voxel;
    double oy = grid->min_y + (double)cy * grid->chunk * grid->voxel;
    double oz = grid->min_z + (double)cz * grid->chunk * grid->voxel;
    /* Chunk box seen from the tool's frame (only Y and Z change when A rotates). */
    double box_y0 = oy;
    double box_y1 = oy + chunk_len;
    double box_z0 = oz;
    double box_z1 = oz + chunk_len;
    double path_dist;
    if (pass->rotate) {
        sc_rotated_yz_bounds(
            box_y0, box_z0, box_y1, box_z1, pass->cos_a, -pass->sin_a, &box_y0, &box_z0, &box_y1, &box_z1);
    }
    if (box_z1 < pass->tip_z_lo || box_z0 > pass->tip_z_hi) {
        return 0;
    }
    path_dist = sc_segment_box_dist(
        pass->seg.p0x, pass->seg.p0y, pass->seg.p1x, pass->seg.p1y, ox, box_y0, ox + chunk_len, box_y1);
    return path_dist <= pass->xy_reject;
}

/* Delete every cube of the chunk whose center is inside the tool. */
static void sc_carve_chunk_cubes(const ScVoxelPass *pass, ScChunkRec *rec, int cx, int cy, int cz) {
    const ScVoxelGrid *grid = pass->grid;
    int cs = grid->chunk;
    double vs = grid->voxel;
    int ix, iy, iz;
    for (ix = 0; ix < cs; ix++) {
        int gx = cx * cs + ix;
        if (gx >= grid->nx) {
            continue;
        }
        for (iy = 0; iy < cs; iy++) {
            int gy = cy * cs + iy;
            if (gy >= grid->ny) {
                continue;
            }
            for (iz = 0; iz < cs; iz++) {
                int gz = cz * cs + iz;
                size_t idx;
                double x, y, z;
                if (gz >= grid->nz) {
                    continue;
                }
                idx = ((size_t)ix * (size_t)cs + (size_t)iy) * (size_t)cs + (size_t)iz;
                if (!rec->data[idx]) {
                    continue;
                }
                x = grid->min_x + ((double)gx + 0.5) * vs;
                y = grid->min_y + ((double)gy + 0.5) * vs;
                z = grid->min_z + ((double)gz + 0.5) * vs;
                if (pass->rotate) {
                    /* Test in the tool's frame: unspin the cube by -A. */
                    sc_rotate_yz_cs(y, z, pass->cos_a, -pass->sin_a, &y, &z);
                }
                if (!sc_seg_tool_contains(&pass->seg, x, y, z)) {
                    continue;
                }
                rec->data[idx] = 0;
                rec->solid -= 1;
                rec->hits += 1;
                if (pass->removed != NULL) {
                    *pass->removed += 1;
                }
                if (rec->solid < 0) {
                    rec->solid = 0;
                }
            }
        }
    }
}

/* Carve one move at a fixed A angle. Skip chunks that can't possibly touch the tool. */
static void sc_carve_constant_a(
    const ScVoxelGrid *grid,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double angle,
    const ScProfile *profile,
    ScChunkTable *table,
    ScGetChunkFn get_chunk,
    void *ctx,
    int *removed) {
    double vs = grid->voxel;
    double pad = profile->max_r + vs;
    /* World-space box around everything the tool can touch during the move. */
    double minx = fmin(p0x, p1x) - pad;
    double miny = fmin(p0y, p1y) - pad;
    double minz = fmin(p0z, p1z) - pad;
    double maxx = fmax(p0x, p1x) + pad;
    double maxy = fmax(p0y, p1y) + pad;
    double maxz = fmax(p0z, p1z) + profile->flute_z + pad;
    int cx0, cy0, cz0, cx1, cy1, cz1;
    int cx, cy, cz;
    ScVoxelPass pass;

    pass.grid = grid;
    sc_seg_tool_init(&pass.seg, p0x, p0y, p0z, p1x, p1y, p1z, profile);
    pass.rotate = fabs(angle) > 1e-9;
    pass.cos_a = 1.0;
    pass.sin_a = 0.0;
    pass.tip_z_lo = fmin(p0z, p1z) - vs;
    pass.tip_z_hi = fmax(p0z, p1z) + profile->flute_z + vs;
    pass.xy_reject = profile->max_r + vs;
    /* A plain cylinder at A = 0 sweeps a convex shape, so a fully covered chunk can be emptied at once. */
    pass.allow_full_clear = (!pass.rotate && profile->const_r > 0.0);
    pass.table = table;
    pass.get_chunk = get_chunk;
    pass.ctx = ctx;
    pass.removed = removed;

    if (pass.rotate) {
        double rad = angle * (M_PI / 180.0);
        pass.cos_a = cos(rad);
        pass.sin_a = sin(rad);
        /* The search box is in the tool's frame; spin it into the stock's frame to find the chunks. */
        sc_rotated_yz_bounds(miny, minz, maxy, maxz, pass.cos_a, pass.sin_a, &miny, &minz, &maxy, &maxz);
    }

    if (!sc_chunk_span(minx, maxx, grid->min_x, grid, grid->nx, &cx0, &cx1) ||
        !sc_chunk_span(miny, maxy, grid->min_y, grid, grid->ny, &cy0, &cy1) ||
        !sc_chunk_span(minz, maxz, grid->min_z, grid, grid->nz, &cz0, &cz1)) {
        return;
    }
    for (cx = cx0; cx <= cx1; cx++) {
        for (cy = cy0; cy <= cy1; cy++) {
            for (cz = cz0; cz <= cz1; cz++) {
                ScChunkRec *rec;
                if (cx < 0 || cy < 0 || cz < 0 || cx >= grid->ncx || cy >= grid->ncy || cz >= grid->ncz) {
                    continue;
                }
                if (!sc_chunk_in_reach(&pass, cx, cy, cz)) {
                    continue;
                }
                rec = sc_chunk_get(table, get_chunk, ctx, cx, cy, cz);
                if (rec == NULL || rec->solid <= 0 || rec->data == NULL) {
                    continue;
                }
                if (pass.allow_full_clear && sc_chunk_fully_inside_const_r(grid, cx, cy, cz, &pass.seg)) {
                    sc_chunk_clear_all(rec, grid->chunk, pass.removed);
                    continue;
                }
                sc_carve_chunk_cubes(&pass, rec, cx, cy, cz);
            }
        }
    }
}

/* Carve one move. A move that turns the A axis a lot is cut into pieces, each at its own fixed angle. */
static void sc_carve_segment(
    const ScVoxelGrid *grid,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1,
    const ScProfile *profile,
    ScChunkTable *table,
    ScGetChunkFn get_chunk,
    void *ctx,
    int *removed) {
    double da = a1 - a0;
    if (fabs(da) > SC_MAX_DA) {
        int n = (int)ceil(fabs(da) / SC_MAX_DA);
        int i;
        if (n < 1) {
            n = 1;
        }
        for (i = 0; i < n; i++) {
            double t0 = (double)i / (double)n;
            double t1 = (double)(i + 1) / (double)n;
            double ang = a0 + 0.5 * (t0 + t1) * da; /* the piece's middle angle */
            double dx = p1x - p0x;
            double dy = p1y - p0y;
            double dz = p1z - p0z;
            sc_carve_constant_a(
                grid,
                p0x + t0 * dx,
                p0y + t0 * dy,
                p0z + t0 * dz,
                p0x + t1 * dx,
                p0y + t1 * dy,
                p0z + t1 * dz,
                ang,
                profile,
                table,
                get_chunk,
                ctx,
                removed);
        }
        return;
    }
    sc_carve_constant_a(grid, p0x, p0y, p0z, p1x, p1y, p1z, a0, profile, table, get_chunk, ctx, removed);
}

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
    double *volumes) {
    ScChunkTable table;
    int i;
    if (touched) {
        *touched = NULL;
    }
    if (n_touched) {
        *n_touched = 0;
    }
    if (grid == NULL || profile == NULL || nseg <= 0 || get_chunk == NULL) {
        return 0;
    }
    if (profile->max_r <= 0.0 && profile->flute_z <= 0.0) {
        return 0;
    }
    memset(&table, 0, sizeof(table));
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        double angle_start = a0 ? a0[i] : 0.0;
        double angle_end = a1 ? a1[i] : 0.0;
        int removed = 0;
        sc_carve_segment(grid, a[0], a[1], a[2], b[0], b[1], b[2], angle_start, angle_end, profile, &table, get_chunk, ctx, volumes != NULL ? &removed : NULL);
        if (volumes != NULL) {
            double edge = grid->voxel;
            volumes[i] = (double)removed * edge * edge * edge;
        }
    }
    if (touched) {
        *touched = table.items;
    } else {
        free(table.items);
    }
    if (n_touched) {
        *n_touched = table.n;
    }
    return 0;
}
