/* Cylindrical / rotary stock: leftover radius at each (X, angle) cell.
 *
 * Picture the stock as a cylinder lying along X with the A axis through its middle. Each grid cell is a ray
 * starting at the axis, at some X and some angle. Its value is how far along that ray material is left (the
 * "leftover radius", called `s` below). Carving only ever shrinks it.
 *
 * The A axis spins the stock. Instead we spin the tool the opposite way, so the rays stay fixed. A "pose" is
 * the tool at one A angle.
 *
 * To cut a ray we find the stretch of it that lies inside the tool. If the leftover radius falls inside that
 * stretch (or just below its end), everything from the stretch's entry point outwards is removed, so the
 * leftover radius becomes the entry point.
 */
#include "stock_carve_internal.h"

#include <math.h>
#include <stdlib.h>
#include <string.h>

#define SC_MAX_SLOTS 64 /* max cylinder/cone pieces we keep from one tool profile */

/* ------------------------------------------------------------------------- */
/* Rays and intervals along them                                             */
/* ------------------------------------------------------------------------- */

/* A ray from the rotation axis, in the plane at X = x: the point at distance s is
 * (x, y0 + s * uy, z0 + s * uz). (y0, z0) is where the axis sits for the current pose, and
 * (uy, uz) is the ray's unit direction.
 */
typedef struct ScRay {
    double x;
    double y0, z0;
    double uy, uz;
} ScRay;

/* A range [lo, hi] of distances along a ray. `valid` is 0 when the range is empty. */
typedef struct ScInterval {
    double lo, hi;
    int valid;
} ScInterval;

static void sc_interval_empty(ScInterval *iv) {
    iv->lo = SC_INF;
    iv->hi = -SC_INF;
    iv->valid = 0;
}

static void sc_interval_all(ScInterval *iv) {
    iv->lo = -SC_INF;
    iv->hi = SC_INF;
    iv->valid = 1;
}

static void sc_interval_set(ScInterval *iv, double lo, double hi) {
    iv->lo = lo;
    iv->hi = hi;
    iv->valid = lo <= hi + 1e-9;
}

static int sc_interval_contains(const ScInterval *iv, double s) {
    return iv->valid && s >= iv->lo - 1e-9 && s <= iv->hi + 1e-9;
}

/* Overlap of an XY interval and a Z interval, limited to s >= 0 (we only look outwards from the axis). */
static void sc_interval_intersect(const ScInterval *xy, const ScInterval *z, ScInterval *out) {
    sc_interval_set(out, fmax(fmax(xy->lo, z->lo), 0.0), fmin(xy->hi, z->hi));
}

/* Grow `acc` to also cover `iv`. Gaps between the two are filled in (a bounding interval). */
static void sc_interval_union(ScInterval *acc, const ScInterval *iv) {
    if (!iv->valid || iv->lo > iv->hi + 1e-9) {
        return;
    }
    if (!acc->valid) {
        acc->lo = iv->lo;
        acc->hi = iv->hi;
        acc->valid = 1;
        return;
    }
    if (iv->lo < acc->lo) {
        acc->lo = iv->lo;
    }
    if (iv->hi > acc->hi) {
        acc->hi = iv->hi;
    }
}

/* If the leftover radius s_hi (or the point `probe` below it) is in the interval, cut back to its entry. */
static void sc_hit_from_interval(const ScInterval *iv, double s_hi, double probe, double *new_s, int *hit) {
    double s_probe = fmax(s_hi - probe, 0.0);
    *hit = s_hi >= 0.0 && (sc_interval_contains(iv, s_hi) || sc_interval_contains(iv, s_probe));
    *new_s = *hit ? iv->lo : s_hi;
}

/* Distances s where the ray is between heights z_lo and z_hi (z_lo <= z_hi). */
static void sc_z_slab(const ScRay *ray, double z_lo, double z_hi, ScInterval *out) {
    int z_fixed = fabs(ray->uz) < 1e-12;
    double uz_safe = z_fixed ? 1.0 : ray->uz;
    double s_a = (z_lo - ray->z0) / uz_safe;
    double s_b = (z_hi - ray->z0) / uz_safe;
    if (z_fixed) {
        /* The ray is horizontal: it is either always inside the slab or never. */
        if ((z_lo - 1e-9) <= ray->z0 && ray->z0 <= (z_hi + 1e-9)) {
            sc_interval_all(out);
        } else {
            sc_interval_empty(out);
        }
        return;
    }
    sc_interval_set(out, fmin(s_a, s_b), fmax(s_a, s_b));
}

/* Distances s where the ray is within R of the point (cx, cy) in the XY plane (a disk). */
static void sc_ray_disk(const ScRay *ray, double cx, double cy, double R, ScInterval *out) {
    double ax = ray->x - cx;
    double q = ray->y0 - cy;
    double bud = R * R - ax * ax; /* squared half-width of the disk at this X */
    int u_fixed = fabs(ray->uy) < 1e-12;
    double disc, s_a, s_b;
    if (bud < -1e-12) {
        sc_interval_empty(out); /* the ray's X is outside the disk */
        return;
    }
    if (u_fixed) {
        /* The ray runs along X, so its Y never changes: always inside or never. */
        if (q * q <= bud + 1e-12) {
            sc_interval_all(out);
        } else {
            sc_interval_empty(out);
        }
        return;
    }
    disc = sqrt(fmax(bud, 0.0));
    s_a = (-q - disc) / ray->uy;
    s_b = (-q + disc) / ray->uy;
    sc_interval_set(out, fmin(s_a, s_b), fmax(s_a, s_b));
}

/* Distances s where the ray is within R of the XY segment p0 -> p1 (a "stadium": a rectangle with round ends). */
static void sc_ray_stadium(
    const ScRay *ray, double p0x, double p0y, double p1x, double p1y, double R, ScInterval *out) {
    double dx = p1x - p0x;
    double dy = p1y - p0y;
    double L2 = dx * dx + dy * dy;
    ScInterval part;
    sc_interval_empty(out);

    /* The two round ends. */
    sc_ray_disk(ray, p0x, p0y, R, &part);
    sc_interval_union(out, &part);
    if (L2 >= 1e-18) {
        double g0, g1, lim, alpha, beta;
        ScInterval across, along, strip;
        int strip_ok = 1;
        sc_interval_empty(&across);
        sc_interval_empty(&along);
        sc_ray_disk(ray, p1x, p1y, R, &part);
        sc_interval_union(out, &part);

        /* The straight part is the overlap of two slabs: within R of the infinite line through the segment
         * ("across"), and between the segment's end points ("along"). Both are linear in s. */
        g0 = (ray->x - p0x) * dy - (ray->y0 - p0y) * dx;
        g1 = ray->uy * dx; /* signed distance from the line (times |d|) is g0 - s * g1 */
        lim = R * sqrt(L2);
        if (fabs(g1) < 1e-12) {
            if (fabs(g0) > lim + 1e-12) {
                strip_ok = 0;
            } else {
                sc_interval_all(&across);
            }
        } else {
            double s_a = (g0 - lim) / g1;
            double s_b = (g0 + lim) / g1;
            sc_interval_set(&across, fmin(s_a, s_b), fmax(s_a, s_b));
        }
        alpha = (ray->x - p0x) * dx + (ray->y0 - p0y) * dy; /* position along the segment (times |d|) is alpha + s * beta */
        beta = ray->uy * dy;
        if (fabs(beta) < 1e-12) {
            if (alpha < -1e-12 || alpha > L2 + 1e-12) {
                strip_ok = 0;
            } else {
                sc_interval_all(&along);
            }
        } else if (beta > 0.0) {
            sc_interval_set(&along, (0.0 - alpha) / beta, (L2 - alpha) / beta);
        } else {
            sc_interval_set(&along, (L2 - alpha) / beta, (0.0 - alpha) / beta);
        }
        if (strip_ok) {
            sc_interval_set(&strip, fmax(across.lo, along.lo), fmin(across.hi, along.hi));
            sc_interval_union(out, &strip);
        }
    }
}

/* ------------------------------------------------------------------------- */
/* Where a ray passes through the tool                                       */
/* ------------------------------------------------------------------------- */

/* A ray against a constant-radius flute (a cylinder standing on the Z axis at tool position (tx, ty, tz)).
 * The flute spans heights tz + flute_z0 .. tz + flute_z1.
 */
static void sc_cylinder_interval(
    const ScRay *ray,
    double tx,
    double ty,
    double tz,
    double radius,
    double flute_z0,
    double flute_z1,
    ScInterval *out) {
    double z_lo = tz + flute_z0;
    double z_hi = tz + flute_z1;
    ScInterval xy, z;
    if (z_hi < z_lo) {
        double tmp = z_lo;
        z_lo = z_hi;
        z_hi = tmp;
    }
    sc_ray_disk(ray, tx, ty, radius, &xy);
    sc_z_slab(ray, z_lo, z_hi, &z);
    sc_interval_intersect(&xy, &z, out);
}

/* A constant-radius tool sweeping along the move: the stretch of the ray that lies inside it.
 * Handles horizontal moves and pure plunges. Moves that change XY and Z together are left to the
 * binary search in sc_cut_one (the time window of the sweep depends on both), reported as an empty interval.
 */
static void sc_swept_cylinder_interval(
    const ScRay *ray, const ScSegTool *move, double radius, double flute_z0, double flute_z1, ScInterval *out) {
    double z_lo = flute_z0;
    double z_hi = flute_z1;
    ScInterval xy, z;
    if (z_hi < z_lo) {
        double tmp = z_lo;
        z_lo = z_hi;
        z_hi = tmp;
    }
    sc_interval_empty(out);
    if (radius <= 0.0) {
        return;
    }
    if (move->xy_len_sq < 1e-18) {
        /* Pure plunge: fixed XY, and the flute covers the heights the tip travels through. */
        double tip_lo = move->p0z < move->p1z ? move->p0z : move->p1z;
        double tip_hi = move->p0z > move->p1z ? move->p0z : move->p1z;
        sc_cylinder_interval(ray, move->p0x, move->p0y, tip_lo, radius, z_lo, z_hi + (tip_hi - tip_lo), out);
        return;
    }
    if (fabs(move->dz) >= 1e-12) {
        return;
    }
    /* Horizontal feed: the XY stadium, limited to the flute's height range (the tip height is fixed). */
    sc_ray_stadium(ray, move->p0x, move->p0y, move->p1x, move->p1y, radius, &xy);
    sc_z_slab(ray, move->p0z + z_lo, move->p0z + z_hi, &z);
    sc_interval_intersect(&xy, &z, out);
}

/* Same as sc_cylinder_interval, but the flute tapers linearly from radius ra (at height za) to rb (at zb),
 * which makes it a cone: a V-bit, or one step of a ball nose. The ray can enter and leave a cone twice,
 * so there can be two separate stretches: `first` and `second`.
 */
static void sc_frustum_intervals(
    const ScRay *ray,
    double tx,
    double ty,
    double tz,
    double za,
    double zb,
    double ra,
    double rb,
    ScInterval *first,
    ScInterval *second) {
    double dx = ray->x - tx;
    double q = ray->y0 - ty;
    double dz = zb - za;
    /* Cone radius at distance s along the ray is A + B * s. */
    double k = fabs(dz) < 1e-12 ? 0.0 : (rb - ra) / dz;
    double A = ra + k * (ray->z0 - tz - za);
    double B = k * ray->uz;
    ScInterval z_range, r_range;
    double box_lo, box_hi;
    sc_interval_empty(first);
    sc_interval_empty(second);

    /* The ray has to be within the cone's height range... */
    sc_z_slab(ray, tz + za, tz + zb, &z_range);
    /* ...and where the cone's radius is not negative (the formula above would otherwise mirror the cone). */
    if (fabs(B) < 1e-12) {
        if (A >= -1e-12) {
            sc_interval_all(&r_range);
        } else {
            sc_interval_empty(&r_range);
        }
    } else if (B > 0.0) {
        sc_interval_set(&r_range, -A / B, SC_INF);
    } else {
        sc_interval_set(&r_range, -SC_INF, -A / B);
    }
    box_lo = fmax(fmax(z_range.lo, r_range.lo), 0.0);
    box_hi = fmin(z_range.hi, r_range.hi);
    if (!(box_lo <= box_hi + 1e-9)) {
        return;
    }

    /* Inside the cone's side wall: (distance from the cone axis)^2 <= (cone radius)^2, which is the
     * quadratic cs2 * s^2 + cs1 * s + cs0 <= 0 in s. */
    {
        double cs2 = ray->uy * ray->uy - B * B;
        double cs1 = 2.0 * q * ray->uy - 2.0 * A * B;
        double cs0 = dx * dx + q * q - A * A;
        if (fabs(cs2) < 1e-14) {
            /* The quadratic degenerates into a straight line. */
            double s_lin_lo, s_lin_hi, l_lo, l_hi;
            if (fabs(cs1) < 1e-14) {
                if (cs0 <= 1e-12) {
                    s_lin_lo = -SC_INF;
                    s_lin_hi = SC_INF;
                } else {
                    s_lin_lo = SC_INF;
                    s_lin_hi = -SC_INF;
                }
            } else if (cs1 > 0.0) {
                s_lin_lo = -SC_INF;
                s_lin_hi = -cs0 / cs1;
            } else {
                s_lin_lo = -cs0 / cs1;
                s_lin_hi = SC_INF;
            }
            l_lo = fmax(box_lo, s_lin_lo);
            l_hi = fmin(box_hi, s_lin_hi);
            if (l_lo <= l_hi + 1e-9) {
                sc_interval_set(first, l_lo, l_hi);
            }
        } else {
            double disc_raw = cs1 * cs1 - 4.0 * cs2 * cs0;
            double sqrt_d = sqrt(fmax(disc_raw, 0.0));
            double inv = 0.5 / cs2;
            double r1 = (-cs1 - sqrt_d) * inv;
            double r2 = (-cs1 + sqrt_d) * inv;
            double root_lo = fmin(r1, r2);
            double root_hi = fmax(r1, r2);
            if (cs2 >= 0.0) {
                /* Opens upwards: inside between the two roots (if there are any). */
                if (disc_raw >= -1e-12) {
                    double u_lo = fmax(box_lo, root_lo);
                    double u_hi = fmin(box_hi, root_hi);
                    if (u_lo <= u_hi + 1e-9) {
                        sc_interval_set(first, u_lo, u_hi);
                    }
                }
            } else if (disc_raw < -1e-12) {
                /* Opens downwards with no roots: inside everywhere. */
                sc_interval_set(first, box_lo, box_hi);
            } else {
                /* Opens downwards: inside before the first root and after the second one. */
                double w1_hi = fmin(box_hi, root_lo);
                double w2_lo = fmax(box_lo, root_hi);
                int has_before = box_lo <= w1_hi + 1e-9;
                int has_after = w2_lo <= box_hi + 1e-9;
                if (has_before) {
                    sc_interval_set(first, box_lo, w1_hi);
                } else if (has_after) {
                    sc_interval_set(first, w2_lo, box_hi);
                }
                if (has_before && has_after) {
                    sc_interval_set(second, w2_lo, box_hi);
                }
            }
        }
    }
}

/* Walk the tool profile: each pair of samples is a cylinder or a cone. Collect where the ray passes
 * through each piece. Returns the number of intervals stored in `slots`.
 */
static int sc_collect_slots(
    const ScRay *ray, double tx, double ty, double tz, const ScProfile *profile, ScInterval *slots) {
    int nslots = 0;
    int i;
    for (i = 0; i < profile->n - 1 && nslots < SC_MAX_SLOTS; i++) {
        double za = profile->zs[i];
        double zb = profile->zs[i + 1];
        double ra = profile->rs[i];
        double rb = profile->rs[i + 1];
        ScInterval first, second;
        if (fabs(zb - za) < 1e-12 && fabs(rb - ra) < 1e-12) {
            continue; /* zero-size piece */
        }
        if (zb < za) {
            double tmp_z = za;
            double tmp_r = ra;
            za = zb;
            zb = tmp_z;
            ra = rb;
            rb = tmp_r;
        }
        if (fabs(rb - ra) < 1e-12) {
            sc_cylinder_interval(ray, tx, ty, tz, ra, za, zb, &slots[nslots]);
            nslots++;
            continue;
        }
        sc_frustum_intervals(ray, tx, ty, tz, za, zb, ra, rb, &first, &second);
        slots[nslots++] = first;
        if (second.valid && nslots < SC_MAX_SLOTS) {
            slots[nslots++] = second;
        }
    }
    return nslots;
}

/* Cut a ray with a tool of any shape sitting at (tx, ty, tz). The tool is made of several pieces, so if
 * the leftover radius is inside some piece's stretch, the overlapping and touching stretches of the other
 * pieces are merged in first, and the radius is cut back to the start of the merged stretch.
 */
static void sc_revolution_cut(
    const ScRay *ray,
    double tx,
    double ty,
    double tz,
    const ScProfile *profile,
    double s_hi,
    double probe,
    double *new_s,
    int *hit) {
    ScInterval slots[SC_MAX_SLOTS];
    int nslots, i, pass;
    int any = 0;
    double enter = SC_INF;
    double exit_ = -SC_INF;
    double s_probe;
    nslots = sc_collect_slots(ray, tx, ty, tz, profile, slots);
    if (nslots <= 0) {
        *new_s = s_hi;
        *hit = 0;
        return;
    }
    if (nslots == 1) {
        sc_hit_from_interval(&slots[0], s_hi, probe, new_s, hit);
        return;
    }
    /* Start from the pieces that contain the leftover radius. */
    s_probe = fmax(s_hi - probe, 0.0);
    for (i = 0; i < nslots; i++) {
        if (!sc_interval_contains(&slots[i], s_hi) && !sc_interval_contains(&slots[i], s_probe)) {
            continue;
        }
        any = 1;
        if (slots[i].lo < enter) {
            enter = slots[i].lo;
        }
        if (slots[i].hi > exit_) {
            exit_ = slots[i].hi;
        }
    }
    *hit = any && s_hi >= 0.0;
    if (!*hit) {
        *new_s = s_hi;
        return;
    }
    /* Absorb every piece that overlaps the merged stretch. Each pass can only reach pieces that touch the
     * stretch as it was at the start of that pass, so up to nslots - 1 passes are needed. */
    for (pass = 0; pass < nslots - 1; pass++) {
        double next_enter = enter;
        double next_exit = exit_;
        for (i = 0; i < nslots; i++) {
            if (!slots[i].valid) {
                continue;
            }
            if (!(slots[i].lo <= exit_ + 1e-9 && slots[i].hi >= enter - 1e-9)) {
                continue;
            }
            if (slots[i].lo < next_enter) {
                next_enter = slots[i].lo;
            }
            if (slots[i].hi > next_exit) {
                next_exit = slots[i].hi;
            }
        }
        enter = next_enter;
        exit_ = next_exit;
    }
    *new_s = fmax(enter, 0.0);
}

/* How many binary-search steps to land within about one cell. */
static int sc_radius_iters(double cell, double stock_radius) {
    double step = fmax(cell * 0.02, 1e-5);
    double ratio = fmax(stock_radius, cell) / step;
    int n = (int)ceil(log2(ratio)) + 1;
    return sc_clamp_int(n, 8, 14);
}

/* Is the point at distance r along the ray inside the swept tool? */
static int sc_ray_point_in_tool(const ScRay *ray, double r, const ScSegTool *move) {
    if (r < 0.0) {
        return 0;
    }
    return sc_seg_tool_contains(move, ray->x, ray->y0 + r * ray->uy, ray->z0 + r * ray->uz);
}

/* Middle of a move, or its start if it hardly moves. */
static void sc_move_midpoint(const ScSegTool *move, double *x, double *y, double *z) {
    if (move->seg_len_sq < 1e-18) {
        *x = move->p0x;
        *y = move->p0y;
        *z = move->p0z;
    } else {
        *x = move->p0x + 0.5 * move->dx;
        *y = move->p0y + 0.5 * move->dy;
        *z = move->p0z + 0.5 * move->dz;
    }
}

/* Cut one ray (leftover radius s_hi) with the tool moving along `move`. Sets *hit and the new radius.
 *   Short move: treat the tool as sitting at the move's middle and use the closed-form cylinder / cone hit.
 *   Long move, plain cylinder, horizontal or plunge: the swept-cylinder closed form.
 *   Anything else (ball / V-bit, or a cylinder moving in XY and Z together): binary search for the largest
 *   radius at which the ray is still outside the tool.
 */
static void sc_cut_one(
    const ScRay *ray,
    double s_hi,
    const ScSegTool *move,
    double cell,
    double stock_radius,
    double *new_s,
    int *hit) {
    const ScProfile *profile = move->profile;
    double z0 = move->flute_lo_z;
    double z1 = move->flute_hi_z;
    double probe = cell * 0.5; /* also test slightly inside the leftover radius, to not miss a graze */
    ScInterval iv;

    if (move->seg_len_sq <= cell * cell) {
        double tx, ty, tz;
        sc_move_midpoint(move, &tx, &ty, &tz);
        if (profile->const_r >= 0.0) {
            sc_cylinder_interval(ray, tx, ty, tz, profile->const_r, z0, z1, &iv);
            sc_hit_from_interval(&iv, s_hi, probe, new_s, hit);
            return;
        }
        sc_revolution_cut(ray, tx, ty, tz, profile, s_hi, probe, new_s, hit);
        return;
    }
    if (profile->const_r >= 0.0) {
        if (move->xy_len_sq < 1e-18 || fabs(move->dz) < 1e-12) {
            sc_swept_cylinder_interval(ray, move, profile->const_r, z0, z1, &iv);
            sc_hit_from_interval(&iv, s_hi, probe, new_s, hit);
            return;
        }
    }
    {
        int iters, k;
        double lo, hi;
        *hit = sc_ray_point_in_tool(ray, s_hi, move) || sc_ray_point_in_tool(ray, fmax(s_hi - probe, 0.0), move);
        if (!*hit) {
            *new_s = s_hi;
            return;
        }
        /* The tool is solid up to s_hi: find where it starts. [lo, hi] always brackets that point,
         * with `lo` outside the tool and `hi` inside. */
        lo = 0.0;
        hi = s_hi;
        iters = sc_radius_iters(cell, stock_radius);
        for (k = 0; k < iters; k++) {
            double mid = 0.5 * (lo + hi);
            if (sc_ray_point_in_tool(ray, mid, move)) {
                hi = mid;
            } else {
                lo = mid;
            }
        }
        *new_s = fmax(lo, 0.0);
    }
}

/* ------------------------------------------------------------------------- */
/* Grid indexing and angle bins                                              */
/* ------------------------------------------------------------------------- */

/* Scratch memory and settings shared by every move of one sc_cylindrical_carve call. */
typedef struct ScCylCtx {
    const ScCylGrid *grid;
    const ScProfile *profile;
    ScCarveOutputs out;
    double *work;       /* [nx * n_theta] leftover radii as doubles; only the rows being carved are filled */
    int *theta_idx;     /* [n_theta] angle bins the tool can reach in the current pose */
    double *ray_uy;     /* [n_theta] ray direction of each bin in theta_idx, for the current pose */
    double *ray_uz;     /* [n_theta] */
    uint8_t *changed;   /* [nx * n_theta] which cells of the rows being carved were lowered */
    double *r_cut;      /* [nx] new radius of each row (used when A spins in place) */
    int *all_theta;     /* [n_theta] 0, 1, 2, ... */
    double *volume;     /* optional accumulator for the move being carved; NULL skips it */
} ScCylCtx;

/* cos/sin of -angle_deg: the tool is spun by -A so the stock rays stay put. */
static void sc_pose_cs(double angle_deg, double *c, double *s) {
    double rad = -angle_deg * (M_PI / 180.0);
    *c = cos(rad);
    *s = sin(rad);
}

static int sc_x_index(double x, double min_x, double cell) {
    return (int)floor((x - min_x) / cell);
}

static double sc_cell_center_x(const ScCylGrid *grid, int ix) {
    return grid->min_x + ((double)ix + 0.5) * grid->cell;
}

/* Rows (X cells) the tool can reach while its tip moves between x_lo and x_hi. Returns 0 if there are none. */
static int sc_row_range(const ScCylCtx *ctx, double x_lo, double x_hi, int *ix0, int *ix1) {
    const ScCylGrid *grid = ctx->grid;
    double pad = ctx->profile->max_r + grid->cell;
    *ix0 = sc_x_index(x_lo - pad, grid->min_x, grid->cell);
    *ix1 = sc_x_index(x_hi + pad, grid->min_x, grid->cell);
    return sc_clip_range(ix0, ix1, grid->nx);
}

static int sc_theta_index(double angle_deg, double d_theta, int n_theta) {
    double a = sc_py_mod(angle_deg, 360.0);
    int i = (int)(a / d_theta);
    if (i < 0) {
        i = 0;
    }
    if (n_theta <= 0) {
        return 0;
    }
    return i % n_theta;
}

/* Angle (degrees, in stock space) of a world point seen from the rotation axis, at this A pose. */
static double sc_stock_theta(double y, double z, double angle, double y_axis, double z_axis) {
    return atan2(y - y_axis, z - z_axis) * (180.0 / M_PI) - angle;
}

/* Angle bins covering [a_start, a_end] degrees, wrapping at 360. Returns how many bins went into `out`. */
static int sc_theta_indices(double a_start, double a_end, double d_theta, int n_theta, int *out) {
    double span = a_end - a_start;
    int i0, n, i, count;
    if (span < 0.0) {
        double tmp = a_start;
        a_start = a_end;
        a_end = tmp;
        span = -span;
    }
    /* Covers (nearly) the full circle: use every bin. */
    if (span >= 360.0 - 1e-6) {
        for (i = 0; i < n_theta; i++) {
            out[i] = i;
        }
        return n_theta;
    }
    i0 = sc_theta_index(a_start, d_theta, n_theta);
    n = (int)ceil(span / d_theta) + 2;
    if (n + 1 >= n_theta) {
        for (i = 0; i < n_theta; i++) {
            out[i] = i;
        }
        return n_theta;
    }
    count = n + 1;
    for (i = 0; i < count; i++) {
        out[i] = (i0 + i) % n_theta;
    }
    return count;
}

/* Fill ctx->theta_idx with the angle bins the tool can reach while its tip moves (p0y, p0z) -> (p1y, p1z)
 * at this A pose, and return how many there are. If the path comes close to the axis, every bin is in range.
 */
static int sc_theta_window(const ScCylCtx *ctx, double p0y, double p0z, double p1y, double p1z, double angle) {
    const ScCylGrid *grid = ctx->grid;
    double d_theta = grid->d_theta;
    double y_axis, z_axis, dy0, dz0, dy1, dz1, vy, vz, len_sq, min_dist, reach;
    double th0, th1, delta, lo, hi, pad;
    double ca, sa;
    int i;
    sc_pose_cs(angle, &ca, &sa);
    sc_rotate_yz_cs(grid->axis_y, grid->axis_z, ca, sa, &y_axis, &z_axis);
    /* Path relative to the axis, and the closest it comes to the axis. */
    dy0 = p0y - y_axis;
    dz0 = p0z - z_axis;
    dy1 = p1y - y_axis;
    dz1 = p1z - z_axis;
    vy = dy1 - dy0;
    vz = dz1 - dz0;
    len_sq = vy * vy + vz * vz;
    if (len_sq < 1e-18) {
        min_dist = hypot(dy0, dz0);
    } else {
        double t = sc_clamp(-(dy0 * vy + dz0 * vz) / len_sq, 0.0, 1.0);
        min_dist = hypot(dy0 + t * vy, dz0 + t * vz);
    }
    reach = ctx->profile->max_r + grid->cell;
    if (min_dist < reach + 1e-9) {
        for (i = 0; i < grid->n_theta; i++) {
            ctx->theta_idx[i] = i;
        }
        return grid->n_theta;
    }
    /* Seen from the axis, the tool covers an angular half-width of asin(reach / distance) around the path. */
    pad = asin(fmin(1.0, reach / min_dist)) * (180.0 / M_PI) + d_theta;
    th0 = sc_stock_theta(p0y, p0z, angle, y_axis, z_axis);
    th1 = sc_stock_theta(p1y, p1z, angle, y_axis, z_axis);
    delta = sc_py_mod(th1 - th0 + 180.0, 360.0) - 180.0; /* the shorter way round */
    lo = fmin(th0, th0 + delta) - pad;
    hi = fmax(th0, th0 + delta) + pad;
    return sc_theta_indices(lo, hi, d_theta, grid->n_theta, ctx->theta_idx);
}

/* For the first n_it bins of ctx->theta_idx, compute each ray's direction at this A pose into ctx->ray_uy/uz.
 * Returns where the rotation axis sits at this pose in (*y0, *z0).
 */
static void sc_pose_rays(ScCylCtx *ctx, double angle, int n_it, double *y0, double *z0) {
    const ScCylGrid *grid = ctx->grid;
    double ca, sa;
    int col;
    sc_pose_cs(angle, &ca, &sa);
    sc_rotate_yz_cs(grid->axis_y, grid->axis_z, ca, sa, y0, z0);
    for (col = 0; col < n_it; col++) {
        int ith = ctx->theta_idx[col];
        sc_rotate_yz_cs(grid->sin_t[ith], grid->cos_t[ith], ca, sa, &ctx->ray_uy[col], &ctx->ray_uz[col]);
    }
}

/* Copy the leftover radii of rows ix0 .. ix0 + n_rows - 1 into ctx->work. */
static void sc_copy_rows(ScCylCtx *ctx, int ix0, int n_rows) {
    int n_theta = ctx->grid->n_theta;
    int row, th;
    for (row = 0; row < n_rows; row++) {
        const float *src = ctx->grid->radii + (size_t)(ix0 + row) * (size_t)n_theta;
        double *dst = ctx->work + (size_t)row * (size_t)n_theta;
        for (th = 0; th < n_theta; th++) {
            dst[th] = (double)src[th];
        }
    }
}

/* ------------------------------------------------------------------------- */
/* Reporting changes                                                         */
/* ------------------------------------------------------------------------- */

static int sc_row_has_change(const uint8_t *changed, int row, int n_cols) {
    int c;
    for (c = 0; c < n_cols; c++) {
        if (changed[row * n_cols + c]) {
            return 1;
        }
    }
    return 0;
}

static int sc_col_has_change(const uint8_t *changed, int col, int n_rows, int n_cols) {
    int r;
    for (r = 0; r < n_rows; r++) {
        if (changed[r * n_cols + col]) {
            return 1;
        }
    }
    return 0;
}

/* Flag the tiles touched by a block of changed cells. `changed` is [n_rows][n_cols]; row r is X cell
 * ix0 + r, and column c is angle bin cols[c]. Every row and column that has any change is paired up, which
 * may flag a few extra tiles but is cheap.
 */
static void sc_mark_tiles(
    const ScCylCtx *ctx, const uint8_t *changed, int n_rows, int ix0, const int *cols, int n_cols) {
    const ScCarveOutputs *out = &ctx->out;
    int r, c;
    if (out->tile_mask == NULL || out->tile <= 0 || n_cols <= 0) {
        return;
    }
    for (r = 0; r < n_rows; r++) {
        if (!sc_row_has_change(changed, r, n_cols)) {
            continue;
        }
        for (c = 0; c < n_cols; c++) {
            int tx, ty;
            if (!sc_col_has_change(changed, c, n_rows, n_cols)) {
                continue;
            }
            tx = (r + ix0) / out->tile;
            ty = cols[c] / out->tile;
            if (tx >= 0 && ty >= 0 && ty < out->tile_stride) {
                out->tile_mask[tx * out->tile_stride + ty] = 1;
            }
        }
    }
}

static void sc_add_shell_volume(ScCylCtx *ctx, double old_r, double new_r) {
    double theta, drop;
    if (ctx->volume == NULL || !(new_r < old_r) || !(old_r > 0.0)) {
        return;
    }
    if (new_r < 0.0) {
        new_r = 0.0;
    }
    theta = ctx->grid->d_theta * (M_PI / 180.0);
    drop = 0.5 * (old_r * old_r - new_r * new_r) * theta * ctx->grid->cell;
    if (drop > 0.0) {
        *ctx->volume += drop;
    }
}

/* Store the new radius of cell (ix, ith) from ctx->work (row `row`) into the grid and the change mask. */
static void sc_store_cell(ScCylCtx *ctx, int row, int ix, int ith) {
    int n_theta = ctx->grid->n_theta;
    ctx->grid->radii[ix * n_theta + ith] = (float)ctx->work[row * n_theta + ith];
    if (ctx->out.changed_mask != NULL) {
        ctx->out.changed_mask[ix * n_theta + ith] = 1;
    }
}

/* ------------------------------------------------------------------------- */
/* Carving strategies                                                        */
/* ------------------------------------------------------------------------- */

/* Carve a move at one fixed A angle (A barely moved, or this is one slice of a larger A change). */
static void sc_carve_constant(ScCylCtx *ctx, const ScSegTool *move, double angle) {
    const ScCylGrid *grid = ctx->grid;
    int n_theta = grid->n_theta;
    int ix0, ix1, n_it, n_rows, row, col;
    double y0, z0;
    int any = 0;
    if (!sc_row_range(ctx, fmin(move->p0x, move->p1x), fmax(move->p0x, move->p1x), &ix0, &ix1)) {
        return;
    }
    n_it = sc_theta_window(ctx, move->p0y, move->p0z, move->p1y, move->p1z, angle);
    if (n_it <= 0) {
        return;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(ctx, ix0, n_rows);
    memset(ctx->changed, 0, (size_t)n_rows * (size_t)n_it);
    sc_pose_rays(ctx, angle, n_it, &y0, &z0);

    for (row = 0; row < n_rows; row++) {
        double wx = sc_cell_center_x(grid, ix0 + row);
        for (col = 0; col < n_it; col++) {
            int ith = ctx->theta_idx[col];
            double s = ctx->work[row * n_theta + ith];
            ScRay ray;
            double neu;
            int hit = 0;
            ray.x = wx;
            ray.y0 = y0;
            ray.z0 = z0;
            ray.uy = ctx->ray_uy[col];
            ray.uz = ctx->ray_uz[col];
            sc_cut_one(&ray, s, move, grid->cell, grid->stock_radius, &neu, &hit);
            if (hit && neu < s - 1e-9) {
                sc_add_shell_volume(ctx, s, neu);
                ctx->work[row * n_theta + ith] = neu;
                ctx->changed[row * n_it + col] = 1;
                any = 1;
            }
        }
    }
    if (!any) {
        return;
    }
    for (row = 0; row < n_rows; row++) {
        for (col = 0; col < n_it; col++) {
            if (ctx->changed[row * n_it + col]) {
                sc_store_cell(ctx, row, ix0 + row, ctx->theta_idx[col]);
            }
        }
    }
    sc_mark_tiles(ctx, ctx->changed, n_rows, ix0, ctx->theta_idx, n_it);
}

/* A spun a full turn with (almost) no XYZ travel: the tool just digs in while the stock rotates under it,
 * so one cut radius applies to every angle at that X.
 */
static void sc_carve_full_rev(ScCylCtx *ctx, const ScSegTool *move, double angle) {
    const ScCylGrid *grid = ctx->grid;
    int n_theta = grid->n_theta;
    int ix0, ix1, n_it, n_rows, row, col;
    double y0, z0;
    if (!sc_row_range(ctx, move->p0x, move->p0x, &ix0, &ix1)) {
        return;
    }
    n_it = sc_theta_window(ctx, move->p0y, move->p0z, move->p0y, move->p0z, angle);
    if (n_it <= 0) {
        return;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(ctx, ix0, n_rows);
    sc_pose_rays(ctx, angle, n_it, &y0, &z0);

    /* For each row, the smallest radius the tool cuts to at any angle it can reach. */
    for (row = 0; row < n_rows; row++) {
        double wx = sc_cell_center_x(grid, ix0 + row);
        ctx->r_cut[row] = SC_INF;
        for (col = 0; col < n_it; col++) {
            double s = ctx->work[row * n_theta + ctx->theta_idx[col]];
            ScRay ray;
            double neu;
            int hit = 0;
            ray.x = wx;
            ray.y0 = y0;
            ray.z0 = z0;
            ray.uy = ctx->ray_uy[col];
            ray.uz = ctx->ray_uz[col];
            sc_cut_one(&ray, s, move, grid->cell, grid->stock_radius, &neu, &hit);
            if (hit && neu < ctx->r_cut[row]) {
                ctx->r_cut[row] = neu;
            }
        }
    }
    /* Apply that radius to every angle of the row. */
    memset(ctx->changed, 0, (size_t)n_rows * (size_t)n_theta);
    for (row = 0; row < n_rows; row++) {
        if (ctx->r_cut[row] >= SC_INF) {
            continue; /* the tool didn't touch this row */
        }
        for (col = 0; col < n_theta; col++) {
            double s = ctx->work[row * n_theta + col];
            if (ctx->r_cut[row] < s - 1e-9) {
                sc_add_shell_volume(ctx, s, ctx->r_cut[row]);
                ctx->work[row * n_theta + col] = ctx->r_cut[row];
                ctx->changed[row * n_theta + col] = 1;
                sc_store_cell(ctx, row, ix0 + row, col);
            }
        }
    }
    sc_mark_tiles(ctx, ctx->changed, n_rows, ix0, ctx->all_theta, n_theta);
}

/* Append t to a growing array of move fractions. Returns 0, or -1 if memory ran out (the array is freed). */
static int sc_ts_push(double **ts, int *n, int *cap, double t) {
    if (*n >= *cap) {
        double *grown;
        *cap *= 2;
        grown = (double *)realloc(*ts, (size_t)*cap * sizeof(double));
        if (grown == NULL) {
            free(*ts);
            *ts = NULL;
            return -1;
        }
        *ts = grown;
    }
    (*ts)[(*n)++] = t;
    return 0;
}

static int sc_cmp_double(const void *a, const void *b) {
    double da = *(const double *)a;
    double db = *(const double *)b;
    if (da < db) {
        return -1;
    }
    if (da > db) {
        return 1;
    }
    return 0;
}

/* Sample times (0..1 along the move) at the start, the end, and every X-cell center and A-bin center in
 * between. Without these, a long move could skip over a grid line. Returns 0, or -1 if memory ran out.
 */
static int sc_pose_ts(
    const ScSegTool *move, double a0, double a1, double min_x, double cell, double d_theta, double **out_ts, int *n_out) {
    double da = a1 - a0;
    double xyz_len = sqrt(move->seg_len_sq);
    double *ts = NULL;
    int n = 0, cap = 0, i, w;
    if (xyz_len < 1e-12 && fabs(da) < 1e-9) {
        ts = (double *)malloc(sizeof(double));
        if (ts == NULL) {
            return -1;
        }
        ts[0] = 0.0;
        *out_ts = ts;
        *n_out = 1;
        return 0;
    }
    cap = 16;
    ts = (double *)malloc((size_t)cap * sizeof(double));
    if (ts == NULL) {
        return -1;
    }
    ts[n++] = 0.0;
    ts[n++] = 1.0;
    if (fabs(move->dx) >= 1e-12) {
        /* X-cell centers the tool passes over. */
        double lo = move->dx > 0.0 ? move->p0x : move->p1x;
        double hi = move->dx > 0.0 ? move->p1x : move->p0x;
        double ix0d = ceil((lo - min_x) / cell - 0.5);
        double ix1d = floor((hi - min_x) / cell - 0.5);
        long ix;
        if (ix1d >= ix0d) {
            for (ix = (long)ix0d; (double)ix <= ix1d; ix++) {
                double wx = min_x + ((double)ix + 0.5) * cell;
                if (sc_ts_push(&ts, &n, &cap, (wx - move->p0x) / move->dx) != 0) {
                    return -1;
                }
            }
        }
    }
    if (fabs(da) >= 1e-9) {
        /* Angle-bin centers the A axis passes through. */
        double lo_a = da > 0.0 ? a0 : a1;
        double hi_a = da > 0.0 ? a1 : a0;
        double k0 = ceil(lo_a / d_theta - 0.5);
        double k1 = floor(hi_a / d_theta - 0.5);
        long k;
        if (k1 >= k0) {
            for (k = (long)k0; (double)k <= k1; k++) {
                double ac = ((double)k + 0.5) * d_theta;
                if (sc_ts_push(&ts, &n, &cap, (ac - a0) / da) != 0) {
                    return -1;
                }
            }
        }
    }
    /* Keep the times in [0, 1], rounded so near-duplicates merge, then sort and drop duplicates. */
    for (i = 0; i < n; i++) {
        double t = ts[i];
        if (t < 0.0) {
            t = 0.0;
        }
        if (t > 1.0) {
            t = 1.0;
        }
        ts[i] = round(t * 1e10) / 1e10;
    }
    qsort(ts, (size_t)n, sizeof(double), sc_cmp_double);
    w = 0;
    for (i = 0; i < n; i++) {
        if (w == 0 || ts[i] != ts[w - 1]) {
            ts[w++] = ts[i];
        }
    }
    if (w < 2) {
        ts[0] = 0.0;
        ts[1] = 1.0;
        w = 2;
    }
    *out_ts = ts;
    *n_out = w;
    return 0;
}

/* A changed a lot: stamp the (stationary) tool at a series of poses along the move. Returns 0, or -1. */
static int sc_carve_moving(ScCylCtx *ctx, const ScSegTool *move, double a0, double a1) {
    const ScCylGrid *grid = ctx->grid;
    int n_theta = grid->n_theta;
    double da = a1 - a0;
    double pad = ctx->profile->max_r + grid->cell;
    int ix0, ix1, n_rows, si, row, col;
    double *ts = NULL;
    int n_ts = 0;
    if (!sc_row_range(ctx, fmin(move->p0x, move->p1x), fmax(move->p0x, move->p1x), &ix0, &ix1)) {
        return 0;
    }
    if (sc_pose_ts(move, a0, a1, grid->min_x, grid->cell, grid->d_theta, &ts, &n_ts) != 0) {
        return -1;
    }
    n_rows = ix1 - ix0 + 1;
    sc_copy_rows(ctx, ix0, n_rows);
    memset(ctx->changed, 0, (size_t)n_rows * (size_t)n_theta);

    for (si = 0; si < n_ts; si++) {
        double t = ts[si];
        double tipx = move->p0x + t * move->dx;
        double tipy = move->p0y + t * move->dy;
        double tipz = move->p0z + t * move->dz;
        double ang = a0 + t * da;
        int n_it = sc_theta_window(ctx, tipy, tipz, tipy, tipz, ang);
        int j0, j1;
        double y0, z0;
        ScSegTool stamp;
        if (n_it <= 0) {
            continue;
        }
        /* Rows (relative to ix0) the tool at this pose reaches. */
        j0 = sc_x_index(tipx - pad, grid->min_x, grid->cell) - ix0;
        j1 = sc_x_index(tipx + pad, grid->min_x, grid->cell) - ix0;
        if (j0 < 0) {
            j0 = 0;
        }
        if (j1 > n_rows - 1) {
            j1 = n_rows - 1;
        }
        if (j0 > j1) {
            continue;
        }
        sc_pose_rays(ctx, ang, n_it, &y0, &z0);
        sc_seg_tool_init(&stamp, tipx, tipy, tipz, tipx, tipy, tipz, ctx->profile);
        for (row = j0; row <= j1; row++) {
            double wx = sc_cell_center_x(grid, ix0 + row);
            for (col = 0; col < n_it; col++) {
                int ith = ctx->theta_idx[col];
                double s = ctx->work[row * n_theta + ith];
                ScRay ray;
                double neu;
                int hit = 0;
                ray.x = wx;
                ray.y0 = y0;
                ray.z0 = z0;
                ray.uy = ctx->ray_uy[col];
                ray.uz = ctx->ray_uz[col];
                sc_cut_one(&ray, s, &stamp, grid->cell, grid->stock_radius, &neu, &hit);
                if (hit && neu < s - 1e-9) {
                    sc_add_shell_volume(ctx, s, neu);
                    ctx->work[row * n_theta + ith] = neu;
                    ctx->changed[row * n_theta + ith] = 1;
                }
            }
        }
    }
    for (row = 0; row < n_rows; row++) {
        for (col = 0; col < n_theta; col++) {
            if (ctx->changed[row * n_theta + col]) {
                sc_store_cell(ctx, row, ix0 + row, col);
            }
        }
    }
    sc_mark_tiles(ctx, ctx->changed, n_rows, ix0, ctx->all_theta, n_theta);
    free(ts);
    return 0;
}

/* Pick a carve strategy from how much A (and XYZ) moved. Returns 0, or -1 if memory ran out. */
static int sc_carve_one(
    ScCylCtx *ctx,
    double p0x,
    double p0y,
    double p0z,
    double p1x,
    double p1y,
    double p1z,
    double a0,
    double a1) {
    const ScCylGrid *grid = ctx->grid;
    double cell = grid->cell;
    double step_a = grid->d_theta;
    double da = a1 - a0;
    ScSegTool move;
    int n_a, n, i;
    sc_seg_tool_init(&move, p0x, p0y, p0z, p1x, p1y, p1z, ctx->profile);

    if (fabs(da) >= 360.0 - 1e-6 && move.seg_len_sq <= cell * cell) {
        /* Full revolution with almost no XYZ travel. */
        double tx, ty, tz;
        ScSegTool at_tip;
        sc_move_midpoint(&move, &tx, &ty, &tz);
        sc_seg_tool_init(&at_tip, tx, ty, tz, tx, ty, tz, ctx->profile);
        sc_carve_full_rev(ctx, &at_tip, 0.5 * (a0 + a1));
        return 0;
    }
    if (fabs(da) <= step_a + 1e-9) {
        /* A stayed within one angle bin: treat it as fixed at the middle angle. */
        sc_carve_constant(ctx, &move, 0.5 * (a0 + a1));
        return 0;
    }
    n_a = (int)ceil(fabs(da) / step_a) + 1;
    if (n_a > 4) {
        /* Large A change: sample poses instead of splitting into many tiny moves. */
        return sc_carve_moving(ctx, &move, a0, a1);
    }
    /* Modest A change: split into a few constant-A slices. */
    n = (int)ceil(fabs(da) / step_a);
    if (n < 1) {
        n = 1;
    }
    for (i = 0; i < n; i++) {
        double t0 = (double)i / (double)n;
        double t1 = (double)(i + 1) / (double)n;
        double ang = a0 + 0.5 * (t0 + t1) * da;
        ScSegTool slice;
        sc_seg_tool_init(
            &slice,
            p0x + t0 * move.dx,
            p0y + t0 * move.dy,
            p0z + t0 * move.dz,
            p0x + t1 * move.dx,
            p0y + t1 * move.dy,
            p0z + t1 * move.dz,
            ctx->profile);
        sc_carve_constant(ctx, &slice, ang);
    }
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Entry point                                                               */
/* ------------------------------------------------------------------------- */

static void sc_ctx_free(ScCylCtx *ctx) {
    free(ctx->work);
    free(ctx->theta_idx);
    free(ctx->ray_uy);
    free(ctx->ray_uz);
    free(ctx->changed);
    free(ctx->r_cut);
    free(ctx->all_theta);
}

/* Allocate the scratch buffers. Returns 0, or -1 if memory ran out. */
static int sc_ctx_alloc(ScCylCtx *ctx) {
    size_t nx = (size_t)ctx->grid->nx;
    size_t n_theta = (size_t)ctx->grid->n_theta;
    int i;
    ctx->work = (double *)malloc(nx * n_theta * sizeof(double));
    ctx->theta_idx = (int *)malloc(n_theta * sizeof(int));
    ctx->ray_uy = (double *)malloc(n_theta * sizeof(double));
    ctx->ray_uz = (double *)malloc(n_theta * sizeof(double));
    ctx->changed = (uint8_t *)malloc(nx * n_theta);
    ctx->r_cut = (double *)malloc(nx * sizeof(double));
    ctx->all_theta = (int *)malloc(n_theta * sizeof(int));
    if (!ctx->work || !ctx->theta_idx || !ctx->ray_uy || !ctx->ray_uz || !ctx->changed || !ctx->r_cut ||
        !ctx->all_theta) {
        sc_ctx_free(ctx);
        return -1;
    }
    for (i = 0; i < ctx->grid->n_theta; i++) {
        ctx->all_theta[i] = i;
    }
    return 0;
}

int sc_cylindrical_carve(
    const ScCylGrid *grid,
    const double *p0,
    const double *p1,
    const double *a0,
    const double *a1,
    int nseg,
    const ScProfile *profile,
    const ScCarveOutputs *out,
    double *volumes) {
    static const ScCarveOutputs no_outputs = {0};
    ScCylCtx ctx;
    int i;
    uint8_t *local_mask = NULL;
    if (grid == NULL || grid->radii == NULL || profile == NULL || nseg <= 0 || grid->nx <= 0 || grid->n_theta <= 0) {
        return 0;
    }
    if (profile->max_r <= 0.0 && profile->flute_z <= 0.0) {
        return 0;
    }
    memset(&ctx, 0, sizeof(ctx));
    ctx.grid = grid;
    ctx.profile = profile;
    ctx.out = out != NULL ? *out : no_outputs;
    if (sc_ctx_alloc(&ctx) != 0) {
        return -1;
    }
    /* Remember which cells dropped so the laser wipe stays on that footprint. */
    if (ctx.out.laser != NULL && ctx.out.laser->intensity != NULL && ctx.out.changed_mask == NULL) {
        local_mask = (uint8_t *)calloc((size_t)grid->nx * (size_t)grid->n_theta, 1);
        if (local_mask == NULL) {
            sc_ctx_free(&ctx);
            return -1;
        }
        ctx.out.changed_mask = local_mask;
    }
    for (i = 0; i < nseg; i++) {
        const double *a = p0 + (size_t)i * 3;
        const double *b = p1 + (size_t)i * 3;
        int rc;
        if (volumes != NULL) {
            volumes[i] = 0.0;
            ctx.volume = &volumes[i];
        } else {
            ctx.volume = NULL;
        }
        rc = sc_carve_one(&ctx, a[0], a[1], a[2], b[0], b[1], b[2], a0[i], a1[i]);
        if (rc != 0) {
            free(local_mask);
            sc_ctx_free(&ctx);
            return rc;
        }
    }
    if (ctx.out.laser != NULL && ctx.out.laser->intensity != NULL && ctx.out.changed_mask != NULL) {
        int ix;
        int ith;
        for (ix = 0; ix < grid->nx; ix++) {
            for (ith = 0; ith < grid->n_theta; ith++) {
                if (!ctx.out.changed_mask[(size_t)ix * (size_t)grid->n_theta + (size_t)ith]) {
                    continue;
                }
                sc_laser_clear_coarse_cell(
                    ctx.out.laser, ix, ith, grid->min_x, 0.0, grid->cell, grid->d_theta, grid->n_theta,
                    ctx.out.laser_changed);
            }
        }
    }
    free(local_mask);
    sc_ctx_free(&ctx);
    return 0;
}
