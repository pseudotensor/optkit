#include <curand_kernel.h>
#include "optkit_defs_gpu.h"
#include "optkit_thrust.hpp"
#include "optkit_vector.h"

/* CUDA helper methods */

namespace optkit {

static __global__ void setup_kernel(curandState * state, unsigned long seed)
{
	int tid = blockIdx.x * blockDim.x + threadIdx.x;
	curand_init(seed, tid, 0, &state[tid]);
}

static __global__ void generate(curandState * globalState, ok_float * data,
	const size_t size, const size_t stride)
{
	int tid = blockIdx.x * blockDim.x + threadIdx.x, i;
	#ifndef FLOAT
	for (i = tid; i < size; i += gridDim.x * blockDim.x)
		data[i * stride] = curand_uniform_double(globalState + tid);
	#else
	for (i = tid; i < size; i += gridDim.x * blockDim.x)
		data[i * stride] = curand_uniform(globalState + tid);
	#endif
}

} /* namespace optkit */

static ok_status ok_rand_u01(ok_float * x, const size_t size,
	const size_t stride)
{
	const size_t num_rand = size <= kMaxGridSize ? size : kMaxGridSize;
	curandState * device_states;
	int grid_dim;

	OK_CHECK_PTR(x);
	OK_RETURNIF_ERR( ok_alloc_gpu(device_states, num_rand *
		sizeof(*device_states)) );

	grid_dim = calc_grid_dim(num_rand);

	optkit::setup_kernel<<<grid_dim, kBlockSize>>>(device_states, 0);
	OK_RETURNIF_ERR( OK_STATUS_CUDA );

	optkit::generate<<<grid_dim, kBlockSize>>>(device_states, x, size,
		stride);
	OK_RETURNIF_ERR( OK_STATUS_CUDA );

	return OK_SCAN_ERR( ok_free_gpu(device_states) );
}


template<typename T>
static __global__ void __vector_set(T * data, T val, size_t stride,
	size_t size)
{
	uint i, thread_id = blockIdx.x * blockDim.x + threadIdx.x;
	for (i = thread_id; i < size; i += gridDim.x * blockDim.x)
		data[i * stride] = val;
}

template<typename T>
static ok_status __vector_set_all(vector_<T> * v, T x)
{
	uint grid_dim = calc_grid_dim(v->size);
	__vector_set<T><<<grid_dim, kBlockSize>>>(v->data, x, v->stride, v->size);
	cudaDeviceSynchronize();
	return OK_STATUS_CUDA;
}

template<typename T>
static __global__ void __strided_memcpy(T * x, size_t stride_x, const T * y,
	size_t stride_y, size_t size)
{
	uint i, tid = blockIdx.x * blockDim.x + threadIdx.x;
	for (i = tid; i < size; i += gridDim.x * blockDim.x)
	x[i * stride_x] = y[i * stride_y];
}

template<typename T>
ok_status vector_alloc_(vector_<T> * v, size_t n)
{
	OK_CHECK_PTR(v);
	if (v->data)
		return OK_SCAN_ERR( OPTKIT_ERROR_OVERWRITE );
	v->size = n;
	v->stride = 1;
	return ok_alloc_gpu(v->data, n * sizeof(T));
}

template<typename T>
ok_status vector_calloc_(vector_<T> * v, size_t n)
{
	OK_RETURNIF_ERR( vector_alloc_<T>(v, n) );
	return __vector_set_all<T>(v, static_cast<T>(0));
}

template<typename T>
ok_status vector_free_(vector_<T> * v)
{
	OK_CHECK_VECTOR(v);
	v->size = (size_t) 0;
	v->stride = (size_t) 0;
	return ok_free_gpu(v->data);
}

template<typename T>
ok_status vector_set_all_(vector_<T> * v, T x)
{
	return __vector_set_all(v, x);
}

template<typename T>
ok_status vector_subvector_(vector_<T> * v_out, vector_<T> * v_in,
	size_t offset, size_t n)
{
	if (!v_out || !v_in || !v_in->data)
		return OK_SCAN_ERR( OPTKIT_ERROR_UNALLOCATED );
	v_out->size=n;
	v_out->stride=v_in->stride;
	v_out->data=v_in->data + offset * v_in->stride;
	return OPTKIT_SUCCESS;
}

template<typename T>
ok_status vector_view_array_(vector_<T> * v, T * base, size_t n)
{
	if (!v || !base)
		return OK_SCAN_ERR( OPTKIT_ERROR_UNALLOCATED );
	v->size=n;
	v->stride=1;
	v->data=base;
	return OPTKIT_SUCCESS;
}

template<typename T>
ok_status vector_memcpy_vv_(vector_<T> * v1, const vector_<T> * v2)
{
	uint grid_dim;
	OK_CHECK_VECTOR(v1);
	OK_CHECK_VECTOR(v2);
	if (v1->size != v2->size)
		return OK_SCAN_ERR( OPTKIT_ERROR_DIMENSION_MISMATCH );

	if ( v1->stride == 1 && v2->stride == 1) {
		return ok_memcpy_gpu(v1->data, v2->data, v1->size * sizeof(T));
	} else {
		grid_dim = calc_grid_dim(v1->size);
		__strided_memcpy<T><<<grid_dim, kBlockSize>>>(v1->data,
			v1->stride, v2->data, v2->stride, v1->size);
		cudaDeviceSynchronize();
		return OK_STATUS_CUDA;
	}
}

template<typename T>
ok_status vector_memcpy_va_(vector_<T> * v, const T *y, size_t stride_y)
{
	ok_status err = OPTKIT_SUCCESS;
	uint i;
	OK_CHECK_VECTOR(v);
	OK_CHECK_PTR(y);

	if (v->stride == 1 && stride_y == 1)
		return ok_memcpy_gpu(v->data, y, v->size * sizeof(T));
	else
		for (i = 0; i < v->size && !err; ++i)
			err = ok_memcpy_gpu(v->data + i * v->stride,
				y + i * stride_y, sizeof(T));
	return err;
}

template<typename T>
ok_status vector_memcpy_av_(T *x, const vector_<T> *v, size_t stride_x)
{
	ok_status err = OPTKIT_SUCCESS;
	uint i;
	OK_CHECK_VECTOR(v);
	OK_CHECK_PTR(x);

	if (v->stride == 1 && stride_x == 1)
		return ok_memcpy_gpu(x, v->data, v->size * sizeof(T));
	else
		for (i = 0; i < v->size && !err; ++i)
			err = ok_memcpy_gpu(x + i * stride_x,
				v->data + i * v->stride, sizeof(T));
	return err;
}

template<typename T>
ok_status vector_indmin_(const vector_<T> * v, const T default_value,
	size_t * idx)
{
	OK_CHECK_VECTOR(v);
	OK_CHECK_PTR(idx);
	*idx = __thrust_vector_indmin<T>(v);
	return OK_STATUS_CUDA;

}

template<typename T>
ok_status vector_min_(const vector_<T> * v, const T default_value, T * minval)
{
	OK_CHECK_VECTOR(v);
	OK_CHECK_PTR(minval);
	*minval = __thrust_vector_min<T>(v);
	return OK_STATUS_CUDA;
}

template<typename T>
ok_status vector_max_(const vector_<T> * v, const T default_value, T * maxval)
{
	OK_CHECK_VECTOR(v);
	OK_CHECK_PTR(maxval);
	*maxval = __thrust_vector_max<T>(v);
	return OK_STATUS_CUDA;
}


#ifdef __cplusplus
extern "C" {
#endif

ok_status vector_alloc(vector * v, size_t n)
	{ return vector_alloc_<ok_float>(v, n); }

ok_status vector_calloc(vector * v, size_t n)
	{ return vector_calloc_<ok_float>(v, n); }

ok_status vector_free(vector * v)
	{ return vector_free_<ok_float>(v); }

ok_status vector_set_all(vector * v, ok_float x)
	{ return vector_set_all_<ok_float>(v, x); }

ok_status vector_subvector(vector * v_out, vector * v_in, size_t offset, size_t n)
	{ return vector_subvector_<ok_float>(v_out, v_in, offset, n); }

ok_status vector_view_array(vector * v, ok_float * base, size_t n)
	{ return vector_view_array_<ok_float>(v, base, n); }

ok_status vector_memcpy_vv(vector * v1, const vector * v2)
	{ return vector_memcpy_vv_<ok_float>(v1, v2); }

ok_status vector_memcpy_va(vector * v, const ok_float *y, size_t stride_y)
	{ return vector_memcpy_va_<ok_float>(v, y, stride_y); }

ok_status vector_memcpy_av(ok_float * x, const vector * v, size_t stride_x)
	{ return vector_memcpy_av_<ok_float>(x, v, stride_x); }

ok_status vector_print(const vector * v)
{
	uint i;
	ok_float v_host[v->size];
	OK_RETURNIF_ERR( vector_memcpy_av(v_host, v, 1) );
	for (i = 0; i < v->size; ++i)
		printf("%e ", v_host[i]);
	printf("\n");
	return OPTKIT_SUCCESS;
}

ok_status vector_scale(vector * v, ok_float x)
{
	__thrust_vector_scale(v, x);
	return OK_STATUS_CUDA;
}

ok_status vector_add(vector * v1, const vector * v2)
{
	OK_CHECK_VECTOR(v1);
	OK_CHECK_VECTOR(v2);
	if (v1->size != v2->size)
		return OK_SCAN_ERR( OPTKIT_ERROR_DIMENSION_MISMATCH );

	__thrust_vector_add(v1, v2);
	return OK_STATUS_CUDA;
}

ok_status vector_sub(vector * v1, const vector * v2)
{
	OK_CHECK_VECTOR(v1);
	OK_CHECK_VECTOR(v2);
	if (v1->size != v2->size)
		return OK_SCAN_ERR( OPTKIT_ERROR_DIMENSION_MISMATCH );

	__thrust_vector_sub(v1, v2);
	return OK_STATUS_CUDA;
}

ok_status vector_mul(vector * v1, const vector * v2)
{
	OK_CHECK_VECTOR(v1);
	OK_CHECK_VECTOR(v2);
	if (v1->size != v2->size)
		return OK_SCAN_ERR( OPTKIT_ERROR_DIMENSION_MISMATCH );

	__thrust_vector_mul(v1, v2);
	return OK_STATUS_CUDA;
}

ok_status vector_div(vector * v1, const vector * v2)
{
	OK_CHECK_VECTOR(v1);
	OK_CHECK_VECTOR(v2);
	if (v1->size != v2->size)
		return OK_SCAN_ERR( OPTKIT_ERROR_DIMENSION_MISMATCH );

	__thrust_vector_div(v1, v2);
	return OK_STATUS_CUDA;
}

ok_status vector_add_constant(vector * v, const ok_float x)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_add_constant(v, x);
	return OK_STATUS_CUDA;
}

ok_status vector_abs(vector * v)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_abs(v);
	return OK_STATUS_CUDA;
}

ok_status vector_recip(vector * v)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_recip(v);
	return OK_STATUS_CUDA;
}

ok_status vector_safe_recip(vector * v)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_safe_recip(v);
	return OK_STATUS_CUDA;
}

ok_status vector_sqrt(vector * v)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_sqrt(v);
	return OK_STATUS_CUDA;
}

ok_status vector_pow(vector * v, const ok_float x)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_pow(v, x);
	return OK_STATUS_CUDA;
}

ok_status vector_exp(vector * v)
{
	OK_CHECK_VECTOR(v);
	__thrust_vector_exp(v);
	return OK_STATUS_CUDA;
}

ok_status vector_indmin(const vector * v, size_t * idx)
	{ return vector_indmin_<ok_float>(v, (ok_float) OK_FLOAT_MAX, idx); }

ok_status vector_min(const vector * v, ok_float * minval)
	{ return vector_min_<ok_float>(v, (ok_float) OK_FLOAT_MAX, minval); }

ok_status vector_max(const vector * v, ok_float * maxval)
	{ return vector_max_<ok_float>(v, (ok_float) -OK_FLOAT_MAX, maxval); }

ok_status vector_uniform_rand(vector * v, const ok_float minval,
	const ok_float maxval)
{
	OK_RETURNIF_ERR( ok_rand_u01(v->data, v->size, v->stride) );
	OK_RETURNIF_ERR( vector_scale(v, maxval - minval) );
	return OK_SCAN_ERR( vector_add_constant(v, minval) );
}

ok_status indvector_alloc(indvector * v, size_t n)
	{ return vector_alloc_<size_t>(v, n); }

ok_status indvector_calloc(indvector * v, size_t n)
	{ return vector_calloc_<size_t>(v, n); }

ok_status indvector_free(indvector * v)
	{ return vector_free_<size_t>(v); }

ok_status indvector_set_all(indvector * v, size_t x)
	{ return vector_set_all_<size_t>(v, x); }

ok_status indvector_subvector(indvector * v_out, indvector * v_in,
	size_t offset, size_t n)
	{ return vector_subvector_<size_t>(v_out, v_in, offset, n); }

ok_status indvector_view_array(indvector * v, size_t * base, size_t n)
	{ return vector_view_array_<size_t>(v, base, n); }

ok_status indvector_memcpy_vv(indvector * v1, const indvector * v2)
	{ return vector_memcpy_vv_<size_t>(v1, v2); }

ok_status indvector_memcpy_va(indvector * v, const size_t * y, size_t stride_y)
	{ return vector_memcpy_va_<size_t>(v, y, stride_y); }

ok_status indvector_memcpy_av(size_t * x, const indvector * v, size_t stride_x)
	{ return vector_memcpy_av_<size_t>(x, v, stride_x); }

ok_status indvector_print(const indvector * v)
{
	uint i;
	size_t v_host[v->size];
	OK_RETURNIF_ERR( indvector_memcpy_av(v_host, v, 1) );
	for (i = 0; i < v->size; ++i)
		printf("%zu ", v_host[i]);
	printf("\n");
	return OPTKIT_SUCCESS;
}

ok_status indvector_indmin(const indvector * v, size_t * idx)
	{ return vector_indmin_<size_t>(v, (size_t) INT_MAX, idx); }

ok_status indvector_min(const indvector * v, size_t * minval)
	{ return vector_min_<size_t>(v, (size_t) INT_MAX, minval); }

ok_status indvector_max(const indvector * v, size_t * maxval)
	{ return vector_max_<size_t>(v, 0, maxval); }

#ifdef __cplusplus
}
#endif
