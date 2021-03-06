#ifndef OPTKIT_EQUILIBRATION_H_
#define OPTKIT_EQUILIBRATION_H_

#include "optkit_dense.h"
#include "optkit_operator_transforms.h"
#include "optkit_operator_dense.h"
#include "optkit_operator_sparse.h"

#ifdef __cplusplus
extern "C" {
#endif

ok_status regularized_sinkhorn_knopp(void * linalg_handle, ok_float * A_in,
	matrix * A_out, vector * d, vector *e, enum CBLAS_ORDER ord);

ok_status operator_regularized_sinkhorn(void * linalg_handle, operator * A,
	vector * d, vector * e, const ok_float pnorm);
ok_status operator_equilibrate(void * linalg_handle, operator * A, vector * d,
	vector * e, const ok_float pnorm);
ok_status operator_estimate_norm(void * linalg_handle, operator * A,
	ok_float * norm_est);

#ifdef __cplusplus
}
#endif

#endif /* OPTKIT_EQUILIBRATION_H_ */
