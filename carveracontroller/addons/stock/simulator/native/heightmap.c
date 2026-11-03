/* Heightmap stock: one leftover Z per XY cell. Carving only ever lowers that
 * value. Cannot represent undercuts - that's what the voxel carver is for.
 *
 * For every move, we look at each cell the tool could reach and work out how low the tool
 * gets above that cell's center. If that is below the cell's current height, the cell is lowered.
 */
#include "stock_carve_internal.h"

#include <math.h>

/* Flag the tile containing cell (ix, iy) as changed. */
static void sc_mark_tile(const ScCarveOutputs *out, int ix, int iy) {
    int tx;
    int ty;
    if (out->tile_mask == NULL || out->tile <= 0) {
        return;
    }
    tx = ix / out->tile;
    ty = iy / out->tile;
    out->tile_mask[tx * out->tile_stride + ty] = 1;
}

/* Lowest Z the tool reaches above the point (wx, wy) when the tip is a fraction `t` (0..1) along the move. */
static double sc_cut_z_at(const ScSegTool *seg, double t, double wx, double wy) {
    const ScProfile *profile = seg->profile;
    double ddx = wx - (seg->p0x + t * seg->dx);
    double ddy = wy - (seg->p0y + t * seg->dy);
    double dist_sq = ddx * ddx + ddy * ddy;
    double dist;
    double z_rel;
    /* Callers pick `t` where the point is just inside the tool's widest radius. Rounding can
     * push it a hair outside, so cap the distance at max_r to sample the tool's outer edge instead. */
    if (dist_sq > profile->max_r * profile->max_r) {
        dist = profile->max_r;
    } else {
        dist = sqrt(dist_sq);
    }
    z_rel = sc_sample_z_for_radius(profile, dist);
    return (seg->p0z + t * seg->dz) + z_rel;
}

/* Lowest Z the tool reaches above the cell center (wx, wy) during the whole move,
 * or INFINITY if the tool never gets close enough to touch it.
 */
static double sc_cell_cut_z(const ScSegTool *seg, double wx, double wy) {
    const ScProfile *profile = seg->profile;
    double max_r = profile->max_r;
    double r_cov = max_r + 1e-9;
    double r_cov_sq = r_cov * r_cov;
    double t_proj, px, py, dist_perp_sq, delta_t;
    double t_lo, t_hi, t_mid;
    double cut, cut_hi, cut_mid;

    if (seg->xy_len_sq < 1e-18) {
        /* No XY travel (a plunge, or the tool is parked): the lowest tip position is the deepest one. */
        double dist = hypot(wx - seg->p0x, wy - seg->p0y);
        double tip_z = seg->p0z < seg->p1z ? seg->p0z : seg->p1z;
        return tip_z + sc_sample_z_for_radius(profile, dist);
    }

    /* Find the stretch [t_lo, t_hi] of the move where the cell is within the tool's reach.
     * t_proj is where the tool axis passes closest to the cell. */
    t_proj = ((wx - seg->p0x) * seg->dx + (wy - seg->p0y) * seg->dy) / seg->xy_len_sq;
    px = wx - (seg->p0x + t_proj * seg->dx);
    py = wy - (seg->p0y + t_proj * seg->dy);
    dist_perp_sq = px * px + py * py;
    if (dist_perp_sq > r_cov_sq) {
        return INFINITY; /* the path passes too far away */
    }
    delta_t = sqrt((r_cov_sq - dist_perp_sq) / seg->xy_len_sq);
    t_lo = fmax(t_proj - delta_t, 0.0);
    t_hi = fmin(t_proj + delta_t, 1.0);
    if (t_lo > t_hi) {
        return INFINITY; /* the reach starts after the move ends (or ended before it began) */
    }

    if (profile->const_r >= 0.0) {
        /* End mill: its flat bottom is as deep as the tip, so the deepest point is where the tip is lowest. */
        double t_z = seg->dz >= 0.0 ? t_lo : t_hi;
        return (seg->p0z + t_z * seg->dz) + profile->zs[0];
    }

    /* Ball / V-bit: the depth varies with distance to the axis, so check both ends of the reach
     * and the point of closest approach, and keep the deepest. */
    t_mid = sc_clamp(t_proj, 0.0, 1.0);
    cut = sc_cut_z_at(seg, t_lo, wx, wy);
    cut_hi = sc_cut_z_at(seg, t_hi, wx, wy);
    cut_mid = sc_cut_z_at(seg, t_mid, wx, wy);
    if (cut_hi < cut) {
        cut = cut_hi;
    }
    if (cut_mid < cut) {
        cut = cut_mid;
    }
    return cut;
}

/* Carve one move into the leftover-height grid. */
static void sc_heightmap_one(const ScHeightGrid *grid, const ScSegTool *seg, const ScCarveOutputs *out, double *volume) {
    double cell = grid->cell;
    double pad;
    int ix0, iy0, ix1, iy1, ix, iy;
    if (seg->profile->max_r <= 0.0) {
        return;
    }
    /* Only visit cells the tool could possibly reach: the move's bounding box, grown by the tool radius. */
    pad = seg->profile->max_r + cell;
    ix0 = (int)floor(((fmin(seg->p0x, seg->p1x) - pad) - grid->min_x) / cell);
    iy0 = (int)floor(((fmin(seg->p0y, seg->p1y) - pad) - grid->min_y) / cell);
    ix1 = (int)floor(((fmax(seg->p0x, seg->p1x) + pad) - grid->min_x) / cell);
    iy1 = (int)floor(((fmax(seg->p0y, seg->p1y) + pad) - grid->min_y) / cell);
    if (!sc_clip_range(&ix0, &ix1, grid->nx) || !sc_clip_range(&iy0, &iy1, grid->ny)) {
        return;
    }
    for (ix = ix0; ix <= ix1; ix++) {
        double wx = grid->min_x + ((double)ix + 0.5) * cell;
        for (iy = iy0; iy <= iy1; iy++) {
            double wy = grid->min_y + ((double)iy + 0.5) * cell;
            float *height = &grid->heights[ix * grid->ny + iy];
            double h = (double)(*height);
            double cut;
            if (!(h > SC_OUTSIDE * 0.5)) {
                continue; /* this cell holds no stock */
            }
            cut = sc_cell_cut_z(seg, wx, wy);
            if (cut < grid->min_z) {
                cut = grid->min_z;
            }
            if (!isfinite(cut) || !(cut < h)) {
                continue; /* untouched, or already lower than the tool reaches */
            }
            if ((float)cut < *height) {
                if (volume != NULL) {
                    double drop = h - (double)(float)cut;
                    if (drop > 0.0) {
                        *volume += drop * cell * cell;
                    }
                }
                *height = (float)cut;
            }
            if (out->changed_mask != NULL) {
                out->changed_mask[ix * grid->ny + iy] = 1;
            }
            if (out->laser != NULL) {
                sc_laser_clear_coarse_cell(
                    out->laser, ix, iy, grid->min_x, grid->min_y, cell, cell, 0, out->laser_changed);
            }
            sc_mark_tile(out, ix, iy);
        }
    }
}

int sc_heightmap_carve(
    const ScHeightGrid *grid,
    const double *p0,
    const double *p1,
    int nseg,
    const ScProfile *profile,
    const ScCarveOutputs *out,
    double *volumes) {
    static const ScCarveOutputs no_outputs = {0};
    int i;
    if (grid == NULL || grid->heights == NULL || profile == NULL || nseg <= 0 || grid->nx <= 0 || grid->ny <= 0) {
        return 0;
    }
    if (out == NULL) {
        out = &no_outputs;
    }
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        ScSegTool seg;
        sc_seg_tool_init(&seg, a[0], a[1], a[2], b[0], b[1], b[2], profile);
        if (volumes != NULL) {
            volumes[i] = 0.0;
        }
        sc_heightmap_one(grid, &seg, out, volumes != NULL ? &volumes[i] : NULL);
    }
    return 0;
}
