/* Python entry points. Unpack NumPy buffers, run the C kernels, return dirty tiles.
 * Heightmap and cylindrical drop the GIL while carving; voxel cannot, because it
 * calls back into Python for each chunk.
 *
 * Every entry point follows the same pattern: parse the arguments, borrow the NumPy arrays as raw
 * buffers (Py_buffer), call the kernel, then release the buffers. Buffers start zeroed, and
 * sc_release is safe to call on a buffer that was never filled, so a single cleanup path serves
 * both success and failure.
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#include "stock_carve.h"

#include <string.h>

/* ------------------------------------------------------------------------- */
/* Buffer helpers                                                            */
/* ------------------------------------------------------------------------- */

/* Release a buffer (if one is held) and reset it so it can be released again harmlessly. */
static void sc_release(Py_buffer *view) {
    PyBuffer_Release(view);
    memset(view, 0, sizeof(*view));
}

/* Borrow a C-contiguous buffer so the kernels can index it as a flat array. */
static int sc_get_buffer(PyObject *obj, Py_buffer *view, int writable) {
    int flags = writable ? PyBUF_WRITABLE | PyBUF_ND : PyBUF_ND;
    if (PyObject_GetBuffer(obj, view, flags) != 0) {
        return -1;
    }
    if (!PyBuffer_IsContiguous(view, 'C')) {
        PyErr_SetString(PyExc_ValueError, "stock carve buffer must be C-contiguous");
        sc_release(view);
        return -1;
    }
    return 0;
}

/* Borrow a read-only float64 array. */
static int sc_bind_f64(PyObject *obj, Py_buffer *view, const double **out, const char *what) {
    memset(view, 0, sizeof(*view));
    *out = NULL;
    if (sc_get_buffer(obj, view, 0) != 0) {
        return -1;
    }
    if (view->itemsize != (Py_ssize_t)sizeof(double)) {
        PyErr_Format(PyExc_TypeError, "%s must be float64", what);
        sc_release(view);
        return -1;
    }
    *out = (const double *)view->buf;
    return 0;
}

/* Borrow an optional writable float64 array of at least `n` items (None -> *out NULL). */
static int sc_bind_volumes(PyObject *obj, Py_buffer *view, int n, double **out) {
    *out = NULL;
    memset(view, 0, sizeof(*view));
    if (obj == NULL || obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    if (view->itemsize != (Py_ssize_t)sizeof(double) || view->len / (Py_ssize_t)sizeof(double) < (Py_ssize_t)n) {
        PyErr_SetString(PyExc_ValueError, "volumes must be a float64 buffer of length nseg");
        sc_release(view);
        return -1;
    }
    *out = (double *)view->buf;
    return 0;
}

/* Borrow an optional writable uint8 array: None leaves *ptr NULL. */
static int sc_bind_optional_mask(PyObject *obj, Py_buffer *view, uint8_t **ptr) {
    *ptr = NULL;
    if (obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    *ptr = (uint8_t *)view->buf;
    return 0;
}

/* Python set of (tx, ty, 0) for tiles that changed. */
static PyObject *sc_tiles_from_mask(const uint8_t *mask, int ntx, int nty) {
    PyObject *set = PySet_New(NULL);
    int tx, ty;
    if (set == NULL) {
        return NULL;
    }
    if (mask == NULL) {
        return set;
    }
    for (tx = 0; tx < ntx; tx++) {
        for (ty = 0; ty < nty; ty++) {
            PyObject *tup;
            if (!mask[(size_t)tx * (size_t)nty + (size_t)ty]) {
                continue;
            }
            tup = Py_BuildValue("(iii)", tx, ty, 0);
            if (tup == NULL) {
                Py_DECREF(set);
                return NULL;
            }
            if (PySet_Add(set, tup) < 0) {
                Py_DECREF(tup);
                Py_DECREF(set);
                return NULL;
            }
            Py_DECREF(tup);
        }
    }
    return set;
}

/* Borrow the tool profile arrays and derive the fields the kernels need. */
static int sc_load_profile(PyObject *zs_obj, PyObject *rs_obj, Py_buffer *zs, Py_buffer *rs, ScProfile *profile) {
    if (sc_get_buffer(zs_obj, zs, 0) != 0 || sc_get_buffer(rs_obj, rs, 0) != 0) {
        return -1;
    }
    if (zs->itemsize != (Py_ssize_t)sizeof(double) || rs->itemsize != (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_TypeError, "profile arrays must be float64");
        return -1;
    }
    if (zs->len / (Py_ssize_t)sizeof(double) != rs->len / (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "profile z/r length mismatch");
        return -1;
    }
    sc_profile_prepare(
        profile, (const double *)zs->buf, (const double *)rs->buf, (int)(zs->len / (Py_ssize_t)sizeof(double)));
    return 0;
}

/* ------------------------------------------------------------------------- */
/* Laser decal arguments                                                     */
/* ------------------------------------------------------------------------- */

/* The laser-related buffers of one call: the decal image, an optional "something changed" flag, and the
 * optional dirty-texel log (indices plus a small [count, overflow] meta array).
 */
typedef struct ScPyLaser {
    Py_buffer decal_view;
    Py_buffer flag_view;
    Py_buffer dirty_iu_view;
    Py_buffer dirty_iv_view;
    Py_buffer dirty_meta_view;
    ScLaserDecal decal;
    ScLaserDirty dirty;
    uint8_t *flag;
    int has_decal;
    int has_dirty;
    int changed; /* set by the kernels when any texel changed */
} ScPyLaser;

/* Bind the decal image. `obj` of None means there is no decal (*present = 0). */
static int sc_bind_decal(
    PyObject *obj,
    int nx,
    int nv,
    double cell_u,
    double cell_v,
    double origin_u,
    double origin_v,
    int wrap,
    double v_period,
    double v_scale,
    Py_buffer *view,
    ScLaserDecal *out,
    int *present) {
    *present = 0;
    memset(view, 0, sizeof(*view));
    if (obj == NULL || obj == Py_None) {
        return 0;
    }
    if (nx <= 0 || nv <= 0) {
        PyErr_SetString(PyExc_ValueError, "laser map has no cells");
        return -1;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    if ((size_t)view->len < (size_t)nx * (size_t)nv) {
        PyErr_SetString(PyExc_ValueError, "laser buffer is shorter than nx * nv");
        sc_release(view);
        return -1;
    }
    out->intensity = (uint8_t *)view->buf;
    out->nx = nx;
    out->nv = nv;
    out->cell_u = cell_u;
    out->cell_v = cell_v;
    out->origin_u = origin_u;
    out->origin_v = origin_v;
    out->wrap_v = wrap;
    out->v_period = v_period;
    out->v_scale = v_scale != 0.0 ? v_scale : 1.0;
    out->dirty = NULL;
    *present = 1;
    return 0;
}

/* Bind the optional dirty-index arrays. meta is int32[2]: [n, overflow]. All three must be given, or none. */
static int sc_bind_dirty(
    PyObject *iu_obj,
    PyObject *iv_obj,
    PyObject *meta_obj,
    Py_buffer *iu_view,
    Py_buffer *iv_view,
    Py_buffer *meta_view,
    ScLaserDirty *out,
    int *present) {
    Py_ssize_t cap;
    int32_t *meta;
    *present = 0;
    memset(iu_view, 0, sizeof(*iu_view));
    memset(iv_view, 0, sizeof(*iv_view));
    memset(meta_view, 0, sizeof(*meta_view));
    memset(out, 0, sizeof(*out));
    if (iu_obj == NULL || iu_obj == Py_None || iv_obj == NULL || iv_obj == Py_None || meta_obj == NULL ||
        meta_obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(iu_obj, iu_view, 1) != 0 || sc_get_buffer(iv_obj, iv_view, 1) != 0 ||
        sc_get_buffer(meta_obj, meta_view, 1) != 0) {
        goto fail;
    }
    if (iu_view->itemsize != (Py_ssize_t)sizeof(int32_t) || iv_view->itemsize != (Py_ssize_t)sizeof(int32_t) ||
        meta_view->itemsize != (Py_ssize_t)sizeof(int32_t)) {
        PyErr_SetString(PyExc_TypeError, "laser dirty buffers must be int32");
        goto fail;
    }
    cap = iu_view->len / (Py_ssize_t)sizeof(int32_t);
    if (cap <= 0 || iv_view->len / (Py_ssize_t)sizeof(int32_t) < cap) {
        PyErr_SetString(PyExc_ValueError, "laser dirty index buffers are empty or mismatched");
        goto fail;
    }
    if (meta_view->len / (Py_ssize_t)sizeof(int32_t) < 2) {
        PyErr_SetString(PyExc_ValueError, "laser dirty meta must hold [n, overflow]");
        goto fail;
    }
    meta = (int32_t *)meta_view->buf;
    out->iu = (int32_t *)iu_view->buf;
    out->iv = (int32_t *)iv_view->buf;
    out->cap = (int)cap;
    out->n = meta[0] > 0 ? (int)meta[0] : 0;
    out->overflow = meta[1] ? 1 : 0;
    if (out->n > out->cap) {
        out->n = out->cap;
        out->overflow = 1;
    }
    *present = 1;
    return 0;
fail:
    sc_release(iu_view);
    sc_release(iv_view);
    sc_release(meta_view);
    return -1;
}

/* Bind the optional one-byte "laser changed" flag. */
static int sc_bind_flag(PyObject *obj, Py_buffer *view, uint8_t **out) {
    *out = NULL;
    memset(view, 0, sizeof(*view));
    if (obj == NULL || obj == Py_None) {
        return 0;
    }
    if (sc_get_buffer(obj, view, 1) != 0) {
        return -1;
    }
    if (view->len < 1) {
        PyErr_SetString(PyExc_ValueError, "laser changed flag is empty");
        sc_release(view);
        return -1;
    }
    *out = (uint8_t *)view->buf;
    return 0;
}

/* Bind every laser argument of a call. On failure the caller still calls sc_laser_release. */
static int sc_laser_bind(
    ScPyLaser *laser,
    PyObject *decal_obj,
    int nx,
    int nv,
    double cell_u,
    double cell_v,
    double origin_u,
    double origin_v,
    int wrap,
    double v_period,
    double v_scale,
    PyObject *flag_obj,
    PyObject *dirty_iu_obj,
    PyObject *dirty_iv_obj,
    PyObject *dirty_meta_obj) {
    if (sc_bind_decal(
            decal_obj, nx, nv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, v_scale, &laser->decal_view,
            &laser->decal, &laser->has_decal) != 0) {
        return -1;
    }
    if (sc_bind_flag(flag_obj, &laser->flag_view, &laser->flag) != 0) {
        return -1;
    }
    if (sc_bind_dirty(
            dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &laser->dirty_iu_view, &laser->dirty_iv_view,
            &laser->dirty_meta_view, &laser->dirty, &laser->has_dirty) != 0) {
        return -1;
    }
    if (laser->has_decal && laser->has_dirty) {
        laser->decal.dirty = &laser->dirty;
    }
    return 0;
}

/* Hand the results back to Python: the dirty-log counters and the "changed" flag. */
static void sc_laser_writeback(ScPyLaser *laser) {
    if (laser->has_dirty) {
        int32_t *meta = (int32_t *)laser->dirty_meta_view.buf;
        meta[0] = (int32_t)laser->dirty.n;
        meta[1] = laser->dirty.overflow ? 1 : 0;
    }
    if (laser->flag != NULL) {
        *laser->flag = laser->changed ? 1 : 0;
    }
}

static void sc_laser_release(ScPyLaser *laser) {
    sc_release(&laser->decal_view);
    sc_release(&laser->flag_view);
    sc_release(&laser->dirty_iu_view);
    sc_release(&laser->dirty_iv_view);
    sc_release(&laser->dirty_meta_view);
}

/* ------------------------------------------------------------------------- */
/* Carving                                                                   */
/* ------------------------------------------------------------------------- */

static PyObject *py_heightmap(PyObject *self, PyObject *args) {
    PyObject *heights_obj, *p0_obj, *p1_obj, *zs_obj, *rs_obj, *hit_obj, *tile_obj;
    PyObject *laser_obj, *flag_obj, *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj, *volumes_obj;
    int nx, ny, tile, nseg, lnx, lnv, wrap;
    double min_x, min_y, min_z, cell, cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer heights = {0}, p0 = {0}, p1 = {0}, zs = {0}, rs = {0}, hit = {0}, tiles = {0}, volumes = {0};
    ScPyLaser laser;
    ScProfile profile;
    ScHeightGrid grid;
    ScCarveOutputs out;
    double *volume_ptr = NULL;
    PyObject *result = NULL;
    int ntx, nty, rc;
    (void)self;
    memset(&laser, 0, sizeof(laser));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddiOOOOiiOOOiiddddidOOOOO",
            &heights_obj,
            &nx,
            &ny,
            &tile,
            &min_x,
            &min_y,
            &min_z,
            &cell,
            &nseg,
            &p0_obj,
            &p1_obj,
            &zs_obj,
            &rs_obj,
            &ntx,
            &nty,
            &hit_obj,
            &tile_obj,
            &laser_obj,
            &lnx,
            &lnv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &flag_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj,
            &volumes_obj)) {
        return NULL;
    }
    memset(&out, 0, sizeof(out));
    if (sc_get_buffer(heights_obj, &heights, 1) != 0 || sc_get_buffer(p0_obj, &p0, 0) != 0 ||
        sc_get_buffer(p1_obj, &p1, 0) != 0 || sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0 ||
        sc_bind_optional_mask(hit_obj, &hit, &out.changed_mask) != 0 ||
        sc_bind_optional_mask(tile_obj, &tiles, &out.tile_mask) != 0 ||
        sc_laser_bind(
            &laser, laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, flag_obj,
            dirty_iu_obj, dirty_iv_obj, dirty_meta_obj) != 0 ||
        sc_bind_volumes(volumes_obj, &volumes, nseg, &volume_ptr) != 0) {
        goto done;
    }
    grid.heights = (float *)heights.buf;
    grid.nx = nx;
    grid.ny = ny;
    grid.min_x = min_x;
    grid.min_y = min_y;
    grid.min_z = min_z;
    grid.cell = cell;
    out.tile = tile;
    out.tile_stride = nty;
    out.laser = laser.has_decal ? &laser.decal : NULL;
    out.laser_changed = &laser.changed;

    /* Drop the GIL so Python can keep running while we carve. */
    Py_BEGIN_ALLOW_THREADS
    rc = sc_heightmap_carve(&grid, (const double *)p0.buf, (const double *)p1.buf, nseg, &profile, &out, volume_ptr);
    Py_END_ALLOW_THREADS
    if (rc != 0) {
        PyErr_SetString(PyExc_MemoryError, "heightmap carve failed");
        goto done;
    }
    sc_laser_writeback(&laser);
    result = sc_tiles_from_mask(out.tile_mask, ntx, nty);
done:
    sc_release(&heights);
    sc_release(&p0);
    sc_release(&p1);
    sc_release(&zs);
    sc_release(&rs);
    sc_release(&hit);
    sc_release(&tiles);
    sc_release(&volumes);
    sc_laser_release(&laser);
    return result;
}

static PyObject *py_cylindrical(PyObject *self, PyObject *args) {
    PyObject *radii_obj, *sin_obj, *cos_obj, *p0_obj, *p1_obj, *a0_obj, *a1_obj, *zs_obj, *rs_obj, *chg_obj, *tile_obj;
    PyObject *laser_obj, *flag_obj, *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj, *volumes_obj;
    int nx, n_theta, tile, nseg, ntx, ntt, lnx, lnv, wrap;
    double min_x, cell, d_theta, axis_y, axis_z, stock_radius;
    double cell_u, cell_v, origin_u, origin_v, v_period;
    Py_buffer radii = {0}, sint = {0}, cost = {0}, p0 = {0}, p1 = {0}, a0 = {0}, a1 = {0};
    Py_buffer zs = {0}, rs = {0}, chg = {0}, tiles = {0}, volumes = {0};
    ScPyLaser laser;
    ScProfile profile;
    ScCylGrid grid;
    ScCarveOutputs out;
    double *volume_ptr = NULL;
    PyObject *result = NULL;
    int rc;
    (void)self;
    memset(&laser, 0, sizeof(laser));
    if (!PyArg_ParseTuple(
            args,
            "OiiiddddddOOiOOOOOOiiOOOiiddddidOOOOO",
            &radii_obj,
            &nx,
            &n_theta,
            &tile,
            &min_x,
            &cell,
            &d_theta,
            &axis_y,
            &axis_z,
            &stock_radius,
            &sin_obj,
            &cos_obj,
            &nseg,
            &p0_obj,
            &p1_obj,
            &a0_obj,
            &a1_obj,
            &zs_obj,
            &rs_obj,
            &ntx,
            &ntt,
            &chg_obj,
            &tile_obj,
            &laser_obj,
            &lnx,
            &lnv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &flag_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj,
            &volumes_obj)) {
        return NULL;
    }
    memset(&out, 0, sizeof(out));
    if (sc_get_buffer(radii_obj, &radii, 1) != 0 || sc_get_buffer(sin_obj, &sint, 0) != 0 ||
        sc_get_buffer(cos_obj, &cost, 0) != 0 || sc_get_buffer(p0_obj, &p0, 0) != 0 ||
        sc_get_buffer(p1_obj, &p1, 0) != 0 || sc_get_buffer(a0_obj, &a0, 0) != 0 ||
        sc_get_buffer(a1_obj, &a1, 0) != 0 || sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0 ||
        sc_bind_optional_mask(chg_obj, &chg, &out.changed_mask) != 0 ||
        sc_bind_optional_mask(tile_obj, &tiles, &out.tile_mask) != 0 ||
        sc_laser_bind(
            &laser, laser_obj, lnx, lnv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, 1.0, flag_obj,
            dirty_iu_obj, dirty_iv_obj, dirty_meta_obj) != 0 ||
        sc_bind_volumes(volumes_obj, &volumes, nseg, &volume_ptr) != 0) {
        goto done;
    }
    grid.radii = (float *)radii.buf;
    grid.nx = nx;
    grid.n_theta = n_theta;
    grid.min_x = min_x;
    grid.cell = cell;
    grid.d_theta = d_theta;
    grid.axis_y = axis_y;
    grid.axis_z = axis_z;
    grid.stock_radius = stock_radius;
    grid.sin_t = (const double *)sint.buf;
    grid.cos_t = (const double *)cost.buf;
    out.tile = tile;
    out.tile_stride = ntt;
    out.laser = laser.has_decal ? &laser.decal : NULL;
    out.laser_changed = &laser.changed;

    Py_BEGIN_ALLOW_THREADS
    rc = sc_cylindrical_carve(
        &grid,
        (const double *)p0.buf,
        (const double *)p1.buf,
        (const double *)a0.buf,
        (const double *)a1.buf,
        nseg,
        &profile,
        &out,
        volume_ptr);
    Py_END_ALLOW_THREADS
    if (rc != 0) {
        PyErr_SetString(PyExc_MemoryError, "cylindrical carve failed");
        goto done;
    }
    sc_laser_writeback(&laser);
    result = sc_tiles_from_mask(out.tile_mask, ntx, ntt);
done:
    sc_release(&radii);
    sc_release(&sint);
    sc_release(&cost);
    sc_release(&p0);
    sc_release(&p1);
    sc_release(&a0);
    sc_release(&a1);
    sc_release(&zs);
    sc_release(&rs);
    sc_release(&chg);
    sc_release(&tiles);
    sc_release(&volumes);
    sc_laser_release(&laser);
    return result;
}

/* Voxel occupancy lives in Python. `keepers` holds the chunk buffers so they are
 * not freed while C is still writing into them.
 */
typedef struct ScVoxelPyCtx {
    PyObject *cb;
    PyObject *keepers;
    int failed;
} ScVoxelPyCtx;

/* Called by the kernel to load a chunk. The Python callback returns None for an empty chunk,
 * or (buffer, solid_count, was_full).
 */
static int sc_py_get_chunk(void *vctx, int cx, int cy, int cz, uint8_t **data, int *solid, int *was_full) {
    ScVoxelPyCtx *ctx = (ScVoxelPyCtx *)vctx;
    PyObject *ret;
    Py_buffer view;
    if (ctx->failed) {
        return 0;
    }
    ret = PyObject_CallFunction(ctx->cb, "iii", cx, cy, cz);
    if (ret == NULL) {
        ctx->failed = 1;
        return 0;
    }
    if (ret == Py_None) {
        Py_DECREF(ret);
        return 0; /* empty chunk */
    }
    if (!PyTuple_Check(ret) || PyTuple_GET_SIZE(ret) != 3) {
        Py_DECREF(ret);
        PyErr_SetString(PyExc_TypeError, "voxel chunk callback must return None or (buf, solid, was_full)");
        ctx->failed = 1;
        return 0;
    }
    if (PyObject_GetBuffer(PyTuple_GET_ITEM(ret, 0), &view, PyBUF_WRITABLE | PyBUF_ND) != 0) {
        Py_DECREF(ret);
        ctx->failed = 1;
        return 0;
    }
    *data = (uint8_t *)view.buf;
    *solid = (int)PyLong_AsLong(PyTuple_GET_ITEM(ret, 1));
    *was_full = PyObject_IsTrue(PyTuple_GET_ITEM(ret, 2));
    PyBuffer_Release(&view); /* drop the view; keep the object in `keepers` so the memory stays alive */
    if (PyList_Append(ctx->keepers, PyTuple_GET_ITEM(ret, 0)) < 0) {
        Py_DECREF(ret);
        ctx->failed = 1;
        return 0;
    }
    Py_DECREF(ret);
    return 1;
}

/* Python list of (cx, cy, cz, solid, hits, was_full) for each chunk touched. */
static PyObject *sc_touched_to_list(const ScChunkRec *touched, int n_touched) {
    PyObject *list = PyList_New(n_touched);
    int i;
    if (list == NULL) {
        return NULL;
    }
    for (i = 0; i < n_touched; i++) {
        PyObject *item = Py_BuildValue(
            "(iiiiii)", touched[i].cx, touched[i].cy, touched[i].cz, touched[i].solid, touched[i].hits, touched[i].was_full);
        if (item == NULL) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(list, i, item);
    }
    return list;
}

static PyObject *py_voxel(PyObject *self, PyObject *args) {
    PyObject *p0_obj, *p1_obj, *a0_obj, *a1_obj, *zs_obj, *rs_obj, *cb, *volumes_obj;
    double min_x, min_y, min_z, voxel;
    int chunk, nx, ny, nz, ncx, ncy, ncz, nseg;
    Py_buffer p0 = {0}, p1 = {0}, a0 = {0}, a1 = {0}, zs = {0}, rs = {0}, volumes = {0};
    double *volume_ptr = NULL;
    ScProfile profile;
    ScVoxelGrid grid;
    ScVoxelPyCtx ctx;
    ScChunkRec *touched = NULL;
    int n_touched = 0;
    int rc;
    PyObject *result = NULL;
    (void)self;
    ctx.keepers = NULL;
    if (!PyArg_ParseTuple(
            args,
            "ddddiiiiiiiiOOOOOOOO",
            &min_x,
            &min_y,
            &min_z,
            &voxel,
            &chunk,
            &nx,
            &ny,
            &nz,
            &ncx,
            &ncy,
            &ncz,
            &nseg,
            &p0_obj,
            &p1_obj,
            &a0_obj,
            &a1_obj,
            &zs_obj,
            &rs_obj,
            &cb,
            &volumes_obj)) {
        return NULL;
    }
    if (!PyCallable_Check(cb)) {
        PyErr_SetString(PyExc_TypeError, "voxel chunk callback must be callable");
        return NULL;
    }
    if (sc_get_buffer(p0_obj, &p0, 0) != 0 || sc_get_buffer(p1_obj, &p1, 0) != 0 ||
        sc_get_buffer(a0_obj, &a0, 0) != 0 || sc_get_buffer(a1_obj, &a1, 0) != 0 ||
        sc_load_profile(zs_obj, rs_obj, &zs, &rs, &profile) != 0 ||
        sc_bind_volumes(volumes_obj, &volumes, nseg, &volume_ptr) != 0) {
        goto done;
    }
    grid.min_x = min_x;
    grid.min_y = min_y;
    grid.min_z = min_z;
    grid.voxel = voxel;
    grid.chunk = chunk;
    grid.nx = nx;
    grid.ny = ny;
    grid.nz = nz;
    grid.ncx = ncx;
    grid.ncy = ncy;
    grid.ncz = ncz;
    ctx.cb = cb;
    ctx.keepers = PyList_New(0);
    ctx.failed = 0;
    if (ctx.keepers == NULL) {
        goto done;
    }
    /* The GIL stays held: the kernel calls back into Python for every chunk it needs. */
    rc = sc_voxel_carve(
        &grid,
        (const double *)p0.buf,
        (const double *)p1.buf,
        (const double *)a0.buf,
        (const double *)a1.buf,
        nseg,
        &profile,
        sc_py_get_chunk,
        &ctx,
        &touched,
        &n_touched,
        volume_ptr);
    if (ctx.failed || rc != 0) {
        if (!PyErr_Occurred()) {
            PyErr_SetString(PyExc_RuntimeError, "voxel carve failed");
        }
        goto done;
    }
    result = sc_touched_to_list(touched, n_touched);
done:
    free(touched);
    Py_XDECREF(ctx.keepers);
    sc_release(&p0);
    sc_release(&p1);
    sc_release(&a0);
    sc_release(&a1);
    sc_release(&zs);
    sc_release(&rs);
    sc_release(&volumes);
    return result;
}

/* ------------------------------------------------------------------------- */
/* Laser painting                                                            */
/* ------------------------------------------------------------------------- */

static PyObject *py_laser_paint(PyObject *self, PyObject *args) {
    PyObject *img_obj, *u0_obj, *v0_obj, *u1_obj, *v1_obj, *burn_obj, *allow_obj, *occ_obj, *zr_obj;
    PyObject *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, nv, wrap, nseg, au0, av0, occ_kind, occ_nx, occ_nv;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    double occ_min_x, occ_min_y, occ_cell, occ_d_theta, occ_period;
    Py_buffer u0 = {0}, v0 = {0}, u1 = {0}, v1 = {0}, burn = {0}, allow = {0}, occ = {0}, zr = {0};
    const double *u0p, *v0p, *u1p, *v1p, *zrp = NULL;
    ScPyLaser laser;
    ScLaserOcc occupancy;
    int have_allow = 0, have_occ = 0, allow_rows = 0, allow_cols = 0;
    PyObject *result = NULL;
    (void)self;
    memset(&laser, 0, sizeof(laser));
    memset(&occupancy, 0, sizeof(occupancy));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOOdOiiiOiidddddOOOO",
            &img_obj,
            &nx,
            &nv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &v_scale,
            &nseg,
            &u0_obj,
            &v0_obj,
            &u1_obj,
            &v1_obj,
            &burn_obj,
            &radius,
            &allow_obj,
            &au0,
            &av0,
            &occ_kind,
            &occ_obj,
            &occ_nx,
            &occ_nv,
            &occ_min_x,
            &occ_min_y,
            &occ_cell,
            &occ_d_theta,
            &occ_period,
            &zr_obj,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
        return NULL;
    }
    /* Decal, then segment arrays, then the dirty log. A missing intensity buffer must win over later errors. */
    if (sc_bind_decal(
            img_obj, nx, nv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, v_scale, &laser.decal_view,
            &laser.decal, &laser.has_decal) != 0) {
        goto done;
    }
    if (!laser.has_decal) {
        PyErr_SetString(PyExc_ValueError, "laser paint requires an intensity buffer");
        goto done;
    }
    if (sc_bind_f64(u0_obj, &u0, &u0p, "u0") != 0 || sc_bind_f64(v0_obj, &v0, &v0p, "v0") != 0 ||
        sc_bind_f64(u1_obj, &u1, &u1p, "u1") != 0 || sc_bind_f64(v1_obj, &v1, &v1p, "v1") != 0) {
        goto done;
    }
    if (sc_get_buffer(burn_obj, &burn, 0) != 0) {
        goto done;
    }
    if (allow_obj != Py_None) {
        if (sc_get_buffer(allow_obj, &allow, 0) != 0) {
            goto done;
        }
        if (allow.ndim != 2 || allow.shape == NULL) {
            PyErr_SetString(PyExc_ValueError, "laser allow mask must be a 2D array");
            goto done;
        }
        allow_rows = (int)allow.shape[0];
        allow_cols = (int)allow.shape[1];
        have_allow = 1;
    }
    if (occ_kind != 0 && occ_obj != Py_None) {
        if (sc_get_buffer(occ_obj, &occ, 0) != 0) {
            goto done;
        }
        occupancy.kind = occ_kind;
        occupancy.data = (const float *)occ.buf;
        occupancy.nx = occ_nx;
        occupancy.nv = occ_nv;
        occupancy.min_x = occ_min_x;
        occupancy.min_y = occ_min_y;
        occupancy.cell = occ_cell;
        occupancy.d_theta = occ_d_theta;
        occupancy.period = occ_period;
        have_occ = 1;
    }
    if (zr_obj != Py_None && sc_bind_f64(zr_obj, &zr, &zrp, "z_or_r") != 0) {
        goto done;
    }
    if (sc_bind_dirty(
            dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &laser.dirty_iu_view, &laser.dirty_iv_view,
            &laser.dirty_meta_view, &laser.dirty, &laser.has_dirty) != 0) {
        goto done;
    }
    if (laser.has_decal && laser.has_dirty) {
        laser.decal.dirty = &laser.dirty;
    }

    Py_BEGIN_ALLOW_THREADS
    sc_laser_paint(
        &laser.decal,
        u0p,
        v0p,
        u1p,
        v1p,
        (const uint8_t *)burn.buf,
        zrp,
        nseg,
        radius,
        have_allow ? (const uint8_t *)allow.buf : NULL,
        au0,
        av0,
        allow_rows,
        allow_cols,
        have_occ ? &occupancy : NULL,
        &laser.changed);
    Py_END_ALLOW_THREADS
    sc_laser_writeback(&laser);
    result = PyBool_FromLong(laser.changed);
done:
    sc_release(&u0);
    sc_release(&v0);
    sc_release(&u1);
    sc_release(&v1);
    sc_release(&burn);
    sc_release(&allow);
    sc_release(&occ);
    sc_release(&zr);
    sc_laser_release(&laser);
    return result;
}

static PyObject *py_laser_clear(PyObject *self, PyObject *args) {
    PyObject *img_obj, *u0_obj, *v0_obj, *u1_obj, *v1_obj;
    PyObject *dirty_iu_obj, *dirty_iv_obj, *dirty_meta_obj;
    int nx, nv, wrap, nseg;
    double cell_u, cell_v, origin_u, origin_v, v_period, v_scale, radius;
    Py_buffer u0 = {0}, v0 = {0}, u1 = {0}, v1 = {0};
    const double *u0p, *v0p, *u1p, *v1p;
    ScPyLaser laser;
    PyObject *result = NULL;
    (void)self;
    memset(&laser, 0, sizeof(laser));
    if (!PyArg_ParseTuple(
            args,
            "OiiddddiddiOOOOdOOO",
            &img_obj,
            &nx,
            &nv,
            &cell_u,
            &cell_v,
            &origin_u,
            &origin_v,
            &wrap,
            &v_period,
            &v_scale,
            &nseg,
            &u0_obj,
            &v0_obj,
            &u1_obj,
            &v1_obj,
            &radius,
            &dirty_iu_obj,
            &dirty_iv_obj,
            &dirty_meta_obj)) {
        return NULL;
    }
    /* Decal, then segment arrays, then the dirty log. A missing intensity buffer must win over later errors. */
    if (sc_bind_decal(
            img_obj, nx, nv, cell_u, cell_v, origin_u, origin_v, wrap, v_period, v_scale, &laser.decal_view,
            &laser.decal, &laser.has_decal) != 0) {
        goto done;
    }
    if (!laser.has_decal) {
        PyErr_SetString(PyExc_ValueError, "laser clear requires an intensity buffer");
        goto done;
    }
    if (sc_bind_f64(u0_obj, &u0, &u0p, "u0") != 0 || sc_bind_f64(v0_obj, &v0, &v0p, "v0") != 0 ||
        sc_bind_f64(u1_obj, &u1, &u1p, "u1") != 0 || sc_bind_f64(v1_obj, &v1, &v1p, "v1") != 0) {
        goto done;
    }
    if (sc_bind_dirty(
            dirty_iu_obj, dirty_iv_obj, dirty_meta_obj, &laser.dirty_iu_view, &laser.dirty_iv_view,
            &laser.dirty_meta_view, &laser.dirty, &laser.has_dirty) != 0) {
        goto done;
    }
    if (laser.has_decal && laser.has_dirty) {
        laser.decal.dirty = &laser.dirty;
    }
    Py_BEGIN_ALLOW_THREADS
    sc_laser_clear_capsules(&laser.decal, u0p, v0p, u1p, v1p, nseg, radius, &laser.changed);
    Py_END_ALLOW_THREADS
    sc_laser_writeback(&laser);
    result = PyBool_FromLong(laser.changed);
done:
    sc_release(&u0);
    sc_release(&v0);
    sc_release(&u1);
    sc_release(&v1);
    sc_laser_release(&laser);
    return result;
}

/* ------------------------------------------------------------------------- */
/* Meshing                                                                   */
/* ------------------------------------------------------------------------- */

/* Python list of (vertex bytes, index bytes), one tuple per mesh part. */
static PyObject *sc_batch_to_list(ScMeshBatch *batch) {
    PyObject *list = PyList_New(batch->nparts);
    int i;
    if (list == NULL) {
        return NULL;
    }
    for (i = 0; i < batch->nparts; i++) {
        ScMeshPart *part = &batch->parts[i];
        PyObject *verts = PyBytes_FromStringAndSize(
            (const char *)part->verts, (Py_ssize_t)part->nverts * 12 * (Py_ssize_t)sizeof(float));
        PyObject *indices = PyBytes_FromStringAndSize(
            (const char *)part->indices, (Py_ssize_t)part->nindices * (Py_ssize_t)sizeof(uint16_t));
        PyObject *item;
        if (verts == NULL || indices == NULL) {
            Py_XDECREF(verts);
            Py_XDECREF(indices);
            Py_DECREF(list);
            return NULL;
        }
        item = PyTuple_Pack(2, verts, indices);
        Py_DECREF(verts);
        Py_DECREF(indices);
        if (item == NULL) {
            Py_DECREF(list);
            return NULL;
        }
        PyList_SET_ITEM(list, i, item);
    }
    return list;
}

/* Turn a finished mesh batch into the Python result, or a MemoryError if meshing failed. Frees the batch. */
static PyObject *sc_mesh_result(int rc, ScMeshBatch *batch) {
    PyObject *list;
    if (rc != 0) {
        sc_mesh_batch_free(batch);
        return PyErr_NoMemory();
    }
    list = sc_batch_to_list(batch);
    sc_mesh_batch_free(batch);
    return list;
}

static PyObject *py_mesh_heightmap(PyObject *self, PyObject *args) {
    PyObject *patch_obj;
    Py_buffer patch = {0};
    int gw, gh, x0, y0, nx, ny;
    double ox, oy, min_z, cell, cr, cg, cb, ca;
    ScMeshBatch batch;
    int rc;
    (void)self;
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args, "Oiiiiiidddddddd", &patch_obj, &gw, &gh, &x0, &y0, &nx, &ny, &ox, &oy, &min_z, &cell, &cr, &cg, &cb, &ca)) {
        return NULL;
    }
    if (sc_get_buffer(patch_obj, &patch, 0) != 0) {
        return NULL;
    }
    if (gw < 0 || gh < 0 || patch.len < (Py_ssize_t)(gw + 2) * (gh + 2) * (Py_ssize_t)sizeof(float)) {
        PyErr_SetString(PyExc_ValueError, "heightmap patch is smaller than the halo");
        sc_release(&patch);
        return NULL;
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_heightmap((const float *)patch.buf, gw, gh, x0, y0, nx, ny, ox, oy, min_z, cell, cr, cg, cb, ca, &batch);
    Py_END_ALLOW_THREADS
    sc_release(&patch);
    return sc_mesh_result(rc, &batch);
}

static PyObject *py_mesh_cylinder(PyObject *self, PyObject *args) {
    PyObject *radii_obj, *sin_obj, *cos_obj;
    Py_buffer radii = {0}, sint = {0}, cost = {0};
    int nx, n_theta, ix0, nx_total;
    double min_x, cell, ay, az, floor_r, cr, cg, cb, ca;
    ScMeshBatch batch;
    int rc;
    (void)self;
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args,
            "OiiiiddddOOddddd",
            &radii_obj,
            &nx,
            &n_theta,
            &ix0,
            &nx_total,
            &min_x,
            &cell,
            &ay,
            &az,
            &sin_obj,
            &cos_obj,
            &floor_r,
            &cr,
            &cg,
            &cb,
            &ca)) {
        return NULL;
    }
    if (sc_get_buffer(radii_obj, &radii, 0) != 0 || sc_get_buffer(sin_obj, &sint, 0) != 0 ||
        sc_get_buffer(cos_obj, &cost, 0) != 0) {
        goto fail;
    }
    if (nx < 0 || n_theta < 0 || radii.len < (Py_ssize_t)nx * n_theta * (Py_ssize_t)sizeof(float) ||
        sint.len < (Py_ssize_t)n_theta * (Py_ssize_t)sizeof(double) ||
        cost.len < (Py_ssize_t)n_theta * (Py_ssize_t)sizeof(double)) {
        PyErr_SetString(PyExc_ValueError, "cylindrical mesh buffers are the wrong size");
        goto fail;
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_cylinder(
        (const float *)radii.buf,
        nx,
        n_theta,
        ix0,
        nx_total,
        min_x,
        cell,
        ay,
        az,
        (const double *)sint.buf,
        (const double *)cost.buf,
        floor_r,
        cr,
        cg,
        cb,
        ca,
        &batch);
    Py_END_ALLOW_THREADS
    sc_release(&radii);
    sc_release(&sint);
    sc_release(&cost);
    return sc_mesh_result(rc, &batch);
fail:
    sc_release(&radii);
    sc_release(&sint);
    sc_release(&cost);
    return NULL;
}

static PyObject *py_mesh_voxel(PyObject *self, PyObject *args) {
    PyObject *occ_obj, *valid_obj, *modes_obj, *faces_obj;
    Py_buffer occ = {0}, valid = {0}, face_views[6] = {{0}};
    int face_mode[6];
    const uint8_t *face_ptr[6];
    int cs, i, rc;
    double ox, oy, oz, vs, cr, cg, cb, ca;
    ScMeshBatch batch;
    PyObject *result = NULL;
    (void)self;
    memset(&batch, 0, sizeof(batch));
    if (!PyArg_ParseTuple(
            args, "OOiOOdddddddd", &occ_obj, &valid_obj, &cs, &modes_obj, &faces_obj, &ox, &oy, &oz, &vs, &cr, &cg, &cb, &ca)) {
        return NULL;
    }
    if (cs <= 0) {
        PyErr_SetString(PyExc_ValueError, "voxel chunk size must be positive");
        return NULL;
    }
    if ((occ_obj != Py_None && sc_get_buffer(occ_obj, &occ, 0) != 0) ||
        (valid_obj != Py_None && sc_get_buffer(valid_obj, &valid, 0) != 0)) {
        goto done;
    }
    if (!PySequence_Check(modes_obj) || !PySequence_Check(faces_obj) || PySequence_Size(modes_obj) != 6 ||
        PySequence_Size(faces_obj) != 6) {
        PyErr_SetString(PyExc_ValueError, "voxel mesh expects 6 face modes and 6 faces");
        goto done;
    }
    /* Per side (+X, -X, +Y, -Y, +Z, -Z), the chunk beyond it is: 0 = empty, 1 = solid, 2 = described by an
     * occupancy array, so only mode 2 needs a buffer.
     */
    for (i = 0; i < 6; i++) {
        PyObject *mode_obj = PySequence_GetItem(modes_obj, i);
        PyObject *face_obj = PySequence_GetItem(faces_obj, i);
        long mode;
        if (mode_obj == NULL || face_obj == NULL) {
            Py_XDECREF(mode_obj);
            Py_XDECREF(face_obj);
            goto done;
        }
        mode = PyLong_AsLong(mode_obj);
        Py_DECREF(mode_obj);
        if (mode < 0 || mode > 2) {
            Py_DECREF(face_obj);
            PyErr_SetString(PyExc_ValueError, "voxel face mode must be 0, 1, or 2");
            goto done;
        }
        face_mode[i] = (int)mode;
        face_ptr[i] = NULL;
        if (mode == 2) {
            if (sc_get_buffer(face_obj, &face_views[i], 0) != 0) {
                Py_DECREF(face_obj);
                goto done;
            }
            if (face_views[i].len < (Py_ssize_t)cs * cs) {
                Py_DECREF(face_obj);
                PyErr_SetString(PyExc_ValueError, "voxel face is smaller than the chunk");
                goto done;
            }
            face_ptr[i] = (const uint8_t *)face_views[i].buf;
        }
        Py_DECREF(face_obj);
    }
    Py_BEGIN_ALLOW_THREADS
    rc = sc_mesh_voxel_chunk(
        occ.buf ? (const uint8_t *)occ.buf : NULL,
        valid.buf ? (const uint8_t *)valid.buf : NULL,
        cs,
        face_mode,
        face_ptr,
        ox,
        oy,
        oz,
        vs,
        cr,
        cg,
        cb,
        ca,
        &batch);
    Py_END_ALLOW_THREADS
    result = sc_mesh_result(rc, &batch);
done:
    for (i = 0; i < 6; i++) {
        sc_release(&face_views[i]);
    }
    sc_release(&occ);
    sc_release(&valid);
    sc_mesh_batch_free(&batch);
    return result;
}

/* ------------------------------------------------------------------------- */
/* Module definition                                                         */
/* ------------------------------------------------------------------------- */

static PyMethodDef methods[] = {
    {"heightmap", py_heightmap, METH_VARARGS, "Carve a heightmap batch."},
    {"cylindrical", py_cylindrical, METH_VARARGS, "Carve a cylindrical batch."},
    {"voxel", py_voxel, METH_VARARGS, "Carve a voxel batch."},
    {"laser_paint", py_laser_paint, METH_VARARGS, "Paint laser capsules into a decal."},
    {"laser_clear", py_laser_clear, METH_VARARGS, "Clear laser capsules from a decal."},
    {"mesh_heightmap", py_mesh_heightmap, METH_VARARGS, "Weld a heightmap window into Kivy meshes."},
    {"mesh_cylinder", py_mesh_cylinder, METH_VARARGS, "Weld a cylindrical shell into Kivy meshes."},
    {"mesh_voxel", py_mesh_voxel, METH_VARARGS, "Greedy-mesh one voxel chunk."},
    {NULL, NULL, 0, NULL},
};

static struct PyModuleDef moduledef = {
    PyModuleDef_HEAD_INIT,
    "_stock_carve",
    "Native stock carving kernels.",
    -1,
    methods,
    NULL,
    NULL,
    NULL,
    NULL,
};

PyMODINIT_FUNC PyInit__stock_carve(void) {
    return PyModule_Create(&moduledef);
}
