#ifndef OPTKIT_DENSE_H_GUARD
#define OPTKIT_DENSE_H_GUARD

#include "optkit_defs.h"

#ifdef cplusplus
extern "C" {
#endif


/* VECTOR definition and methods */

typedef struct vector {
	size_t size, stride;
	ok_float * data;
} vector;


void vector_alloc(vector * v, size_t n);
void vector_calloc(vector * v, size_t n);
void vector_free(vector * v);
void vector_set_all(vector * v, ok_float x);
void vector_subvector(vector * v_out, vector * v_in, size_t offset, size_t n);
void vector_view_array(vector * v, ok_float * base, size_t n);
void vector_memcpy_vv(vector * v1, const vector * v2);
void vector_memcpy_va(vector * v, const ok_float * y, size_t stride_y);
void vector_memcpy_av(ok_float * x, const vector * v, size_t stride_x);
void vector_print(const vector *v);
void vector_scale(vector * v, ok_float x);
void vector_add(vector * v1, const vector * v2);
void vector_sub(vector * v1, const vector * v2);
void vector_mul(vector * v1, const vector * v2);
void vector_div(vector * v1, const vector * v2);
void vector_add_constant(vector *v, const ok_float x);
void vector_pow(vector *v, const ok_float x);

/* MATRIX defition and methods */

typedef struct matrix {
  size_t size1, size2, tda;
  ok_float *data;
  CBLAS_ORDER_t rowmajor;
} matrix;


void matrix_alloc(matrix * A, size_t m, size_t n, CBLAS_ORDER_t ord);
void matrix_calloc(matrix * A, size_t m, size_t n, CBLAS_ORDER_t ord);
void matrix_free(matrix * A);
void matrix_submatrix(matrix * A_sub, matrix * A, size_t i, size_t j, size_t n1, size_t n2);
void matrix_row(vector * row, matrix * A, size_t i);
void matrix_column(vector * col, matrix * A, size_t j);
void matrix_diagonal(vector * diag, matrix * A);
void matrix_view_array(matrix * A, const ok_float * base, size_t n1, size_t n2, CBLAS_ORDER_t ord);
void matrix_set_all(matrix * A, ok_float x);
void matrix_memcpy_mm(matrix * A, const matrix *B);
void matrix_memcpy_ma(matrix * A, const ok_float *B, const CBLAS_ORDER_t ord);
void matrix_memcpy_am(ok_float * A, const matrix *B, const CBLAS_ORDER_t ord);
void matrix_print(matrix * A);
void matrix_scale(matrix * A, ok_float x);

int matrix_order_compat(const matrix * A, const matrix * B, const char * nm_A, 
                 const char * nm_B, const char * nm_routine){

  if (A->rowmajor == B->rowmajor) return 1;
  printf("OPTKIT ERROR (%s) matrices %s and %s must have same layout.\n", 
         nm_routine, nm_A, nm_B);
  return 0;
}


/* BLAS routines */

/* BLAS context */
void blas_make_handle(void * linalg_handle);
void blas_destroy_handle(void * linalg_handle);


/* BLAS LEVEL 1 */
void blas_axpy(void * linalg_handle, ok_float alpha, const vector *x, vector *y);
ok_float blas_nrm2(void * linalg_handle, const vector *x);
void blas_scal(void * linalg_handle, const ok_float alpha, vector *x);
ok_float blas_asum(void * linalg_handle, const vector *x);
ok_float blas_dot(void * linalg_handle, const vector *x, const vector *y);


/* BLAS LEVEL 2 */
void blas_gemv(void * linalg_handle, CBLAS_TRANSPOSE_t TransA, 
                 ok_float alpha, const matrix * A, const vector * x, 
                 ok_float beta, vector * y);

void blas_trsv(void * linalg_handle, CBLAS_UPLO_t Uplo, 
                 CBLAS_TRANSPOSE_t TransA, CBLAS_DIAG_t Diag, 
                 const matrix * A, vector * x);

/* BLAS LEVEL 3 */
void blas_syrk(void * linalg_handle, CBLAS_UPLO_t Uplo, 
                 CBLAS_TRANSPOSE_t Trans, ok_float alpha, 
                 const matrix *A, ok_float beta, matrix *C);

void blas_gemm(void * linalg_handle, CBLAS_TRANSPOSE_t TransA, 
                 CBLAS_TRANSPOSE_t TransB, ok_float alpha, 
                 const matrix *A, const matrix *B, 
                 ok_float beta, matrix *C);

void blas_trsm(void * linalg_handle, CBLAS_SIDE_t Side, 
                 CBLAS_UPLO_t Uplo, CBLAS_TRANSPOSE_t TransA,
                 CBLAS_DIAG_t Diag, ok_float alpha, 
                 const matrix *A, matrix *B);

/* LINEAR ALGEBRA routines */
void linalg_cholesky_decomp(void * linalg_handle, matrix * A);
void linalg_cholesky_svx(void * linalg_handle, const matrix * L, 
                            vector * x);



#ifdef cplusplus
}
#endif

#endif  // OPTKIT_DENSE_H_GUARD

