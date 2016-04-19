import unittest
import os
import numpy as np
from scipy.sparse import csr_matrix, csc_matrix
from ctypes import c_void_p, byref, CFUNCTYPE
from optkit.libs import DenseLinsysLibs, SparseLinsysLibs, OperatorLibs
from optkit.libs.cg import ConjugateGradientLibs
from optkit.tests.defs import CONDITIONS, DEFAULT_SHAPE, DEFAULT_MATRIX_PATH
import optkit.tests.C.operator_helper as op_helper

CG_QUIET = 0

class ConjugateGradientLibsTestCase(OptkitCTestCase):
	"""TODO: docstring"""

	@classmethod
	def setUpClass(self):
		self.env_orig = os.getenv('OPTKIT_USE_LOCALLIBS', '0')
		os.environ['OPTKIT_USE_LOCALLIBS'] = '1'
		self.dense_libs = DenseLinsysLibs()
		self.sparse_libs = SparseLinsysLibs()
		self.op_libs = OperatorLibs()
		self.cg_libs = ConjugateGradientLibs()

		self.tol_cg = 1e-12
		self.rho_cg = 1e-4
		self.maxiter_cg = 1000

	@classmethod
	def tearDownClass(self):
		os.environ['OPTKIT_USE_LOCALLIBS'] = self.env_orig

	def setUp(self):
		self.shape = None
		if DEFAULT_MATRIX_PATH is not None:
			try:
				self.A_test = np.load(DEFAULT_MATRIX_PATH)
				self.A_test_sparse = self.A_test
				self.shape = A.shape
			except:
				pass
		if self.shape is None:
			self.shape = DEFAULT_SHAPE
			self.A_test = np.random.rand(*self.shape)
			self.A_test_sparse = np.zeros(self.shape)
			self.A_test_sparse += self.A_test
			for i in xrange(self.shape[0]):
				for j in xrange(self.shape[1]):
					if np.random.rand() > 0.4:
						self.A_test_sparse[i, j] *= 0

		self.x_test = np.random.rand(self.shape[1])
		self.nnz = sum(sum(self.A_test_sparse > 0))

	def tearDown(self):
		self.free_all_vars()

	@staticmethod
	def gen_preconditioning_operator(dlib, olib, A_py, rho):
		n = A_py.shape[1]
		p_vec = dlib.vector(0, 0, None)
		dlib.vector_calloc(p_vec, n)
		p_ = np.zeros(n).astype(dlib.pyfloat)
		p_ptr = p_.ctypes.data_as(dlib.ok_float_p)

		# calculate diagonal preconditioner
		for j in xrange(A_py.shape[1]):
			p_[j] = 1. / (rho +  np.linalg.norm(A_py[:, j])**2)

		dlib.vector_memcpy_va(p_vec, p_ptr, 1)
		p = olib.diagonal_operator_alloc(p_vec)
		return p_, p_vec, p, dlib.vector_free

	@property
	def op_keys(self):
		return ['dense', 'sparse']

	def get_opmethods(self, opkey, denselib, sparselib, operatorlib):
		if opkey == 'dense':
			A = self.A_test
			gen = op_helper.gen_dense_operator
			arg_gen = [denselib, operatorlib, A]
		elif opkey == 'sparse':
			A = self.A_test_sparse
			gen = op_helper.gen_sparse_operator
			arg_gen = [denselib, sparselib, operatorlib, A]
		else:
			raise ValueError('invalid operator type')

		return (A, gen, arg_gen)

	def test_libs_exist(self):
		dlibs = []
		slibs = []
		oplibs = []
		cglibs = []
		for (gpu, single_precision) in CONDITIONS:
			dlibs.append(self.dense_libs.get(
					gpu=gpu, single_precision=single_precision))
			slibs.append(self.sparse_libs.get(
					dlibs[-1], single_precision=single_precision, gpu=gpu))
			oplibs.append(self.op_libs.get(
					dlibs[-1], slibs[-1], single_precision=single_precision,
					gpu=gpu))
			oplibs.append(self.op_libs.get(
					dlibs[-1], slibs[-1], single_precision=single_precision,
					gpu=gpu))
			cglibs.append(self.cg_libs.get(
					dlibs[-1], oplibs[-1], single_precision=single_precision,
					gpu=gpu))

		self.assertTrue(any(dlibs))
		self.assertTrue(any(slibs))
		self.assertTrue(any(oplibs))
		self.assertTrue(any(cglibs))

	def test_cgls_helper_alloc_free(self):
		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			h = lib.cgls_helper_alloc(self.shape[0], self.shape[1])
			self.assertTrue(isinstance(h.contents.p, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.q, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.r, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.s, dlib.vector_p))
			lib.cgls_helper_free(h)

	def test_cgls_nonallocating(self):
		"""
		cgls_nonallocating test

		given operator A, vector b and scalar rho,
		cgls method attemps to solve

			min. ||Ax - b||_2^2 + rho ||x||_2^2

		to specified tolerance _tol_ by performing at most _maxiter_
		CG iterations on the above least squares problem
		"""
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, m)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(m).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += np.random.rand(m)
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test cgls for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test cgls (nonallocating), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				h = lib.cgls_helper_alloc(m, n)
				lib.register_var('h', h, lib.cgls_helper_free)

				flag = lib.cgls_nonallocating(h, o, b, x, rho, tol, maxiter,
											  CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)

				# checks:
				# 1. exit flag == 0
				# 2. KKT condition A'(Ax - b) + rho (x) == 0 (within tol)
				self.assertEqual(flag, 0)
				KKT = A_.T.dot(A_.dot(x_) - b_) + rho * x_
				self.assertTrue(np.linalg.norm(KKT) <= (tol * n)**0.5)

				self.free_var('o')
				self.free_var('A')
				self.free_var('h')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')

	def test_cgls_allocating(self):
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, m)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(m).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += np.random.rand(m)
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test cgls for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test cgls (allocating), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				flag = lib.cgls(o, b, x, rho, tol, maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)

				# checks:
				# 1. exit flag == 0
				# 2. KKT condition A'(Ax - b) + rho (x) == 0 (within tol)
				self.assertEqual(flag, 0)
				KKT = A_.T.dot(A_.dot(x_) - b_) + rho * x_
				self.assertTrue(np.linalg.norm(KKT) <= (tol * n)**0.5)

				self.free_var('o')
				self.free_var('A')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')

	def test_cgls_easy(self):
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, m)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(m).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += np.random.rand(m)
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test cgls for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test cgls (easy), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				cgls_work = lib.cgls_init(m, n)
				self.register_var('work', cgls_work, lib.cgls_finish)
				flag = lib.cgls_solve(cgls_work, o, b, x, rho, tol,
										   maxiter, CG_QUIET)

				self.free_var('work')
				dlib.vector_memcpy_av(x_ptr, x, 1)

				# checks:
				# 1. exit flag == 0
				# 2. KKT condition A'(Ax - b) + rho (x) == 0 (within tol)
				self.assertEqual(flag, 0)
				KKT = A_.T.dot(A_.dot(x_) - b_) + rho * x_
				self.assertTrue(np.linalg.norm(KKT) <= (tol * n)**0.5)

				self.free_var('o')
				self.free_var('A')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')

	def test_pcg_helper_alloc_free(self):
		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			h = lib.pcg_helper_alloc(self.shape[0], self.shape[1])
			self.register_var('h', h, lib.pcg_helper_free)
			self.assertTrue(isinstance(h.contents.p, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.q, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.r, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.z, dlib.vector_p))
			self.assertTrue(isinstance(h.contents.temp, dlib.vector_p))
			self.free_var('h')

	def test_diagonal_preconditioner(self):
		tol = self.tol_cg
		rho = 1e-2
		# rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			RTOL = 2e-2
			ATOLN = RTOL * n**0.5

			# -----------------------------------------
			# test pcg for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test pcg (nonallocating), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				T = rho * np.eye(n)
				T += A_.T.dot(A_)

				p_vec = dlib.vector(0, 0, None)
				dlib.vector_calloc(p_vec, n)
				self.register_var('p_vec', p_vec, dlib.vector_free)

				p_ = np.zeros(n).astype(dlib.pyfloat)
				p_py = np.zeros(n).astype(dlib.pyfloat)
				p_ptr = p_.ctypes.data_as(dlib.ok_float_p)

				# calculate diagonal preconditioner
				for j in xrange(n):
					p_py[j] = 1. / (rho +  np.linalg.norm(T[:, j])**2)

				lib.diagonal_preconditioner(o, p_vec, rho)
				dlib.vector_memcpy_av(p_ptr, p_vec, 1)
				self.assertTrue(np.linalg.norm(p_py - p_) <=
								ATOLN + RTOL * np.linalg.norm(p_py))

				self.free_var('o')
				self.free_var('A')
				self.free_var('p_vec')


	def test_pcg_nonallocating(self):
		"""
		pcg_nonallocating test

		given operator A, vector b, preconditioner M and scalar rho,
		pcg method attemps to solve

			(rho * I + A'A)x = b

		to specified tolerance _tol_ by performing at most _maxiter_
		CG iterations on the system

			M(rho * I + A'A)x = b
		"""
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			DIGITS = 7 - 2 * single_precision - 1 * gpu
			RTOL = 10**(-DIGITS)
			ATOLN = RTOL * n**0.5

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, n)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(n).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += self.x_test
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test pcg for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test pcg (nonallocating), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				h = lib.pcg_helper_alloc(m, n)
				self.register_var('h', h, lib.pcg_helper_free)

				T = rho * np.eye(n)
				T += A_.T.dot(A_)

				p_py, p_vec, p, free_p = self.gen_preconditioning_operator(
						dlib, olib, T, rho)
				self.register_var('p_vec', p_vec, free_p)
				self.register_var('p', p, p.contents.free)

				lib.pcg_nonallocating(h, o, p, b, x, rho, tol, maxiter,
									  CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				self.free_var('p')
				self.free_var('p_vec')
				self.free_var('o')
				self.free_var('A')
				self.free_var('h')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')

	def test_pcg_nonallocating_warmstart(self):
		"""TODO: DOCSTRING"""
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			DIGITS = 7 - 2 * single_precision - 1 * gpu
			RTOL = 10**(-DIGITS)
			ATOLN = RTOL * n**0.5

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, n)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(n).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += self.x_test
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test pcg for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test pcg (nonallocating) warmstart, operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				h = lib.pcg_helper_alloc(m, n)
				self.register_var('h', h, lib.pcg_helper_free)

				T = rho * np.eye(n)
				T += A_.T.dot(A_)

				p_py, p_vec, p, free_p = self.gen_preconditioning_operator(
						dlib, olib, T, rho)
				self.register_var('p_vec', p_vec, free_p)
				self.register_var('p', p, p.contents.free)

				iters1 = lib.pcg_nonallocating(h, o, p, b, x, rho, tol,
											   maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				iters2 = lib.pcg_nonallocating(h, o, p, b, x, rho, tol,
											   maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				print 'cold start iters:', iters1
				print 'warm start iters:', iters2
				self.assertTrue(iters2 <= iters1)

				self.free_var('p')
				self.free_var('p_vec')
				self.free_var('o')
				self.free_var('A')
				self.free_var('h')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')


	def test_pcg_allocating(self):
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			DIGITS = 7 - 2 * single_precision - 1 * gpu
			RTOL = 10**(-DIGITS)
			ATOLN = RTOL * n**0.5

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, n)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(n).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += self.x_test
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test pcg for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test pcg (allocating), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				T = rho * np.eye(n)
				T += A_.T.dot(A_)

				p_py, p_vec, p, free_p = self.gen_preconditioning_operator(
						dlib, olib, T, rho)
				self.register_var('p_vec', p_vec, free_p)
				self.register_var('p', p, p.contents.free)

				lib.pcg(o, p, b, x, rho, tol, maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				self.free_var('p')
				self.free_var('p_vec')
				self.free_var('o')
				self.free_var('A')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')

	def test_pcg_easy(self):
		tol = self.tol_cg
		rho = self.rho_cg
		maxiter = self.maxiter_cg

		m, n = self.shape

		for (gpu, single_precision) in CONDITIONS:
			dlib = self.dense_libs.get(
					single_precision=single_precision, gpu=gpu)
			slib = self.sparse_libs.get(
					dlib, single_precision=single_precision, gpu=gpu)
			olib = self.op_libs.get(
					dlib, slib, single_precision=single_precision, gpu=gpu)
			lib = self.cg_libs.get(
					dlib, olib, single_precision=single_precision, gpu=gpu)

			if lib is None:
				continue

			DIGITS = 7 - 2 * single_precision - 1 * gpu
			RTOL = 10**(-DIGITS)
			ATOLN = RTOL * n**0.5

			# -----------------------------------------
			# allocate x, b in python & C
			b = dlib.vector(0, 0, None)
			dlib.vector_calloc(b, n)
			self.register_var('b', b, dlib.vector_free)
			b_ = np.zeros(n).astype(dlib.pyfloat)
			b_ptr = b_.ctypes.data_as(dlib.ok_float_p)

			x = dlib.vector(0, 0, None)
			dlib.vector_calloc(x, n)
			self.register_var('x', x, dlib.vector_free)
			x_ = np.zeros(n).astype(dlib.pyfloat)
			x_ptr = x_.ctypes.data_as(dlib.ok_float_p)

			b_ += self.x_test
			dlib.vector_memcpy_va(b, b_ptr, 1)

			# -----------------------------------------
			# test pcg for each operator type defined in self.op_keys
			for op_ in self.op_keys:
				print "test pcg (easy), operator type:", op_
				A_, gen_operator, gen_args = self.get_opmethods(op_, dlib,
																slib, olib)

				A, o, freeA = gen_operator(*gen_args)
				self.register_var('A', A, freeA)
				self.register_var('o', o, o.contents.free)

				T = rho * np.eye(n)
				T += A_.T.dot(A_)

				p_py, p_vec, p, free_p = self.gen_preconditioning_operator(
						dlib, olib, T, rho)
				self.register_var('p_vec', p_vec, free_p)
				self.register_var('p', p, p.contents.free)

				pcg_work = lib.pcg_init(m, n)
				self.register_var('work', pcg_work, lib.pcg_finish)
				iters1 = lib.pcg_solve(pcg_work, o, p, b, x, rho, tol,
											maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				iters2 = lib.pcg_solve(pcg_work, o, p, b, x, rho, tol,
											maxiter, CG_QUIET)
				dlib.vector_memcpy_av(x_ptr, x, 1)
				self.assertTrue(np.linalg.norm(T.dot(x_) - b_) <=
								ATOLN + RTOL * np.linalg.norm(b_))

				print 'cold start iters:', iters1
				print 'warm start iters:', iters2
				self.assertTrue(iters2 <= iters1)

				self.free_var('work')
				self.free_var('p')
				self.free_var('p_vec')
				self.free_var('o')
				self.free_var('A')

			# -----------------------------------------
			# free x, b
			self.free_var('x')
			self.free_var('b')