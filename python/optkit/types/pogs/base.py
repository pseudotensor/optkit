from optkit.compat import *

import abc
import numpy as np

from optkit.utils.pyutils import const_iterator
from optkit.utils.proxutils import func_eval_python
from optkit.libs import error as okerr

class DoubleCache(object):
    def __init__(self, npz_file=None, dictionary=None):
        self.__local_cache = {}
        self.__npz_cache = {}

        if isinstance(npz_file, DoubleCache):
            self.set_file(npz_file._DoubleCache__npz_cache)
            self.update(npz_file._DoubleCache__local_cache)
        else:
            self.set_file(npz_file)
        self.update(dictionary)

    def set_file(self, npz_file):
        if isinstance(npz_file, np.lib.npyio.NpzFile):
            self.__npz_cache = npz_file
        elif isinstance(npz_file, dict):
            self.update(npz_file)

    def update(self, dictionary):
        if isinstance(dictionary, dict):
            self.__local_cache.update(dictionary)

    def __contains__(self, key):
        return key in self.__npz_cache or key in self.__local_cache

    def __setitem__(self, key, item):
        self.__local_cache[key] = item

    def __getitem__(self, key):
        if key in self.__npz_cache:
            return self.__npz_cache[key]
        elif key in self.__local_cache:
            return self.__local_cache[key]
        else:
            raise KeyError(
                    '{} has no entry for key=`{}`'.format(DoubleCache, key))

    def pop(self, key, default_value=None):
        if default_value is None:
            return self[key]
        else:
            if key in self:
                return self[key]
            else:
                return default_value

class PogsTypesBase:
    def __init__(self, backend, lib):
        PogsSettings = lib.pogs_settings
        PogsInfo = lib.pogs_info
        PogsOutput = lib.pogs_output
        PogsPrivateData = lib.pogs_solver_priv_data
        PogsFlags = lib.pogs_solver_flags

        class Objective:
            def __init__(self, n, **params):
                self.enums = lib.function_enums
                self.size = n
                self._fields = ['h', 'a', 'b', 'c', 'd', 'e', 's']
                self._h = np.zeros(self.size, dtype=int)
                self._a = np.ones(self.size)
                self._b = np.zeros(self.size)
                self._c = np.ones(self.size)
                self._d = np.zeros(self.size)
                self._e = np.zeros(self.size)
                self._s = np.ones(self.size)
                if 'f' in params:
                    self.copy_from(params['f'])
                else:
                    self.set(**params)

            def eval(self, vec):
                if self.size == 0:
                    return 0.

                vec = np.reshape(np.array(vec), np.size(vec,))
                if vec.size != self.size:
                    raise ValueError(
                            'argument `vec` must have same length as '
                            'this {} object.\nlength {}: {}\nlength '
                            'vec: {}'
                            ''.format(
                                    Objective, Objective, self.size,
                                    vec.size))

                return func_eval_python(self.list(lib.function), vec)


            def copy_from(self, obj, start_index_target=0,
                          start_index_source=0, n_values=None):
                if self.size == 0:
                    return
                if not isinstance(obj, Objective):
                    raise TypeError(
                            'argument `obj` must be of type {}'
                            ''.format(Objective))

                start_source = min(max(start_index_source, 0), obj.size)
                start_target = min(max(start_index_target, 0), self.size)

                end_source = obj.size
                if n_values is not None:
                    end_source = min(start_source + int(n_values), end_source)
                end_target = start_target + (end_source - start_source)

                for key in self._fields:
                    key = '_' + key
                    targ_arr = getattr(self, key)
                    source_arr = getattr(obj, key)
                    targ_arr[start_target : end_target] = (
                            source_arr[start_source : end_source])

            def list(self, function_t):
                return [
                        function_t(
                            self._h[t], self._a[t], self._b[t],
                            self._c[t], self._d[t], self._e[t],
                            self._s[t],
                            )
                        for t in xrange(self.size)]

            @property
            def arrays(self):
                return self.h, self.a, self.b, self.c, self.d, self.e, self.s

            @property
            def h(self):
                return self._h

            @property
            def a(self):
                return self._a

            @property
            def b(self):
                return self._b

            @property
            def c(self):
                return self._c

            @property
            def d(self):
                return self._d

            @property
            def e(self):
                return self._e

            @property
            def s(self):
                return self._s

            def set(self, **params):
                if self.size == 0:
                    return

                start = int(params['start']) if 'start' in params else 0
                end = int(params['end']) if 'end' in params else self.size

                if start < 0 : start = self.size + start
                if end < 0 : end = self.size + end

                r = params.pop('range', xrange(start,end))
                range_length = len(r)

                if range_length == 0:
                    raise ValueError(
                            'index range [{}:{}] results in length-0 '
                            'array when python array slicing applied '
                            'to an {} of length {}.'
                            ''.format(start, end, Objective, self.size))

                for item in self._fields:
                    if item in params:
                        if isinstance(params[item], (list, np.ndarray)):
                            if len(params[item]) != range_length:
                                raise ValueError(
                                        'keyword argument {} of type '
                                        '{} is incomptably sized with '
                                        'the requested {} slice [{}:{}]'
                                        ''.format(
                                                item, type(params[item]),
                                                Objective, start, end))

                param_types = {k: (int, float) for k in self._fields[1:]}
                param_types['h'] = (int, str)

                for key in param_types:
                    if key in params:
                        param = params[key]
                        attr = '_' + key
                        array = getattr(self, attr)
                        validate = self.enums.validator(key)
                        val = None
                        try:
                            val = map(validate, param)
                        except:
                            try:
                                param = validate(param)
                                val = const_iterator(param, range_length)
                            except:
                                allowed = [list, np.ndarray] + list(param_types[key])
                                raise ValueError(
                                        'objective parameter `{}` could '
                                        'not be set with argument of '
                                        'type {}.\n\n'
                                        'allowed types: {}, {}, {}, {}'
                                        ''.format(key, type(param), *allowed))

                        for i, v in enumerate(val):
                            array[r[i]] = v

            def __str__(self):
                return str(
                        'size: {}\nh: {}\na: {}\nb: {}\nc: {}\nd: '
                        '{}\ne: {}\ns: {}'
                        ''.format(
                                self.size, self.h, self.a, self.b, self.c,
                                self.d, self.e, self.s))

        self.Objective = Objective

        class SolverSettings:
            def __init__(self, **options):
                self.c = PogsSettings()
                self.c.x0 = None
                self.c.nu0 = None
                assert okerr.NO_ERR(lib.pogs_set_default_settings(self.c))
                self.update(**options)

            def update(self, **options):
                keys = (
                        'alpha',
                        'rho',
                        'abstol',
                        'reltol',
                        'tolproj',
                        'toladapt',
                        'anderson_regularization',
                        'maxiter',
                        'anderson_lookback',
                        'verbose',
                        'suppress',
                        'adaptiverho',
                        'accelerate',
                        'gapstop',
                        'warmstart',
                        'resume',
                        'diagnostic',
                )
                self.__keys = list(keys) + ['x0', 'nu0']

                if 'maxiters' in options:
                    options['maxiter'] = options['maxiters']

                for key in keys:
                    if key in options:
                        setattr(self.c, key, options[key])

                for key in ('x0', 'nu0'):
                    if key in options:
                        vec = options[key].astype(lib.pyfloat)
                        setattr(self.c, key, vec.ctypes.data_as(lib.ok_float_p))

            def __str__(self):
                summary = ''
                for key in self.__keys:
                    summary += '{}: {}\n'.format(key, getattr(self, key))
                return summary

        for key in (
                'alpha',
                'rho',
                'abstol',
                'reltol',
                'tolproj',
                'toladapt',
                'anderson_regularization'):
            def get_setting(settings):
                return getattr(settings.c, key)
            def set_setting(settings, value):
                value = float(value)
                if value < 0:
                    raise ValueError('argument `{}` must be >= 0'.format(key))
                setattr(settings.c, key, value)
            setattr(SolverSettings, key, property(get_setting, set_setting))

        # for key in ('maxiter', 'anderson_lookback', 'verbose', 'suppress'):
        #     def get_setting(settings):
        #         return getattr(settings.c, key)
        #     def set_setting(settings, value):
        #         value = int(value)
        #         if value < 0:
        #             raise ValueError('argument `{}` must be >= 0'.format(key))
        #         setattr(settings.c, key, value)
        #     setattr(SolverSettings, key, property(get_setting, set_setting))

        # for key in (
        #         'adaptiverho',
        #         'accelerate',
        #         'gapstop',
        #         'warmstart',
        #         'resume',
        #         'diagnostic'):
        #     def get_setting(settings):
        #         return getattr(settings.c, key)
        #     def set_setting(settings, value):
        #         setattr(settings.c, key, int(bool(value)))
        #     setattr(SolverSettings, key, property(get_setting, set_setting))

        # for key in ('x0', 'nu0'):
        #     def get_setting(settings):
        #         return getattr(settings.c, key)
        #     def set_setting(settings, value):
        #         value = value.astype(lib.pyfloat)
        #         setattr(settings.c, key, value.ctypes.data_as(lib.ok_float_p))
        #     setattr(SolverSettings, key, property(get_setting, set_setting))


        class SolverInfo(object):
            def __init__(self):
                self.c = PogsInfo()

            @property
            def err(self):
                return self.c.err

            @property
            def iters(self):
                return self.c.k

            @property
            def solve_time(self):
                return self.c.solve_time

            @property
            def setup_time(self):
                return self.c.setup_time

            @property
            def error(self):
                return self.c.error

            @property
            def converged(self):
                return self.c.converged

            @property
            def objval(self):
                return self.c.obj

            @property
            def rho(self):
                return self.c.rho

            def __str__(self):
                return str(
                        'error: {}\n'.format(self.err).join(
                        'converged: {}\n'.format(self.converged)).join(
                        'iterations: {}\n'.format(self.iters)).join(
                        'objective: {}\n'.format(self.objval)).join(
                        'rho: {}\n'.format(self.rho)).join(
                        'setup time: {}\n'.format(self.setup_time)).join(
                        'solve time: {}\n'.format(self.solve_time)))

        class SolverOutput:
            def __init__(self, m, n):
                self.x = np.zeros(n).astype(lib.pyfloat)
                self.y = np.zeros(m).astype(lib.pyfloat)
                self.mu = np.zeros(n).astype(lib.pyfloat)
                self.nu = np.zeros(m).astype(lib.pyfloat)
                self.c = PogsOutput(
                        self.x.ctypes.data_as(lib.ok_float_p),
                        self.y.ctypes.data_as(lib.ok_float_p),
                        self.mu.ctypes.data_as(lib.ok_float_p),
                        self.nu.ctypes.data_as(lib.ok_float_p))

            def __str__(self):
                return str(
                        'x:\n{}\ny:\n{}\nmu:\n{}\nnu:\n{}\n'.format(
                        str(self.x), str(self.y),
                        str(self.mu), str(self.nu)))

        class SolverState:
            def __init__(self, m, n):
                self.vec = np.zeros(
                        lib.POGS_STATE_LENGTH * (m + n), dtype=lib.pyfloat)
                self.ptr = self.vec.ctypes.data_as(lib.ok_float_p)
                self.rho = np.zeros(1, dtype=lib.pyfloat)
                self.rho_ptr = self.rho.ctypes.data_as(lib.ok_float_p)

            @property
            def dict(self):
                return {'state': self.vec, 'rho': self.rho[0]}

        @add_metaclass(abc.ABCMeta)
        class _SolverCacheBase:
            def __init__(self, shapes, array_dict=None):
                self.ptr = PogsPrivateData()
                self.flags = PogsFlags()
                if array_dict is None:
                    array_dict = dict()

                for key in shapes:
                    if key in array_dict:
                        array = array_dict[key].astype(lib.pyfloat)
                    else:
                        array = np.zeros(shapes[key], dtype=lib.pyfloat)
                    setattr(self, key, array)
                    setattr(self.ptr, key, array.ctypes.data_as(lib.ok_float_p))
                self.__keys = shapes.keys()

                flag_dict = array_dict.pop('flags', {})
                for k in self.flags._fields_:
                    if k[0] in flag_dict:
                        setattr(self.flags, k[0], flag_dict[k[0]])

            @property
            def dict(self):
                d = {k: getattr(self, k) for k in self.__keys}
                d['flags'] = {k[0]: getattr(self.flags, k[0]) for k in self.flags._fields_}
                return d

        self._SolverCacheBase = _SolverCacheBase

        class FunctionVectorLocal:
            def __init__(self, size):
                self.py = np.zeros(size).astype(lib.function)
                self.ptr = self.py.ctypes.data_as(lib.function_p)
                self.c = lib.function_vector(size, self.ptr)

        @add_metaclass(abc.ABCMeta)
        class _SolverBase:
            def __init__(self, A, **options):
                self.__backend = backend
                self.__c_solver = None
                self.__state = None
                self.__cache = None
                self.shape = self.m, self.n = m, n = A.shape
                self.A = A
                self.f = FunctionVectorLocal(m)
                self.g = FunctionVectorLocal(n)
                self.settings = SolverSettings()
                self.info = SolverInfo()
                self.output = SolverOutput(m, n)
                self.settings.update(**options)
                self.first_run = True

                cache = options.pop('cache', None)
                NO_INIT = options.pop('no_init', False) or cache is not None
                if NO_INIT:
                    if cache is not None:
                        self.load(cache, **options)
                else:
                    data = self._build_solver_data(self.A)
                    flags = self._build_solver_flags(self.A, **options)
                    self._register_solver(lib.pogs_init(data, flags))

            def __del__(self):
                self._unregister_solver()

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                self._unregister_solver()

            @property
            def c_solver(self):
                    return self.__c_solver

            @property
            @abc.abstractmethod
            def A(self):
                raise NotImplementedError

            @A.setter
            @abc.abstractmethod
            def A(self, A):
                raise NotImplementedError

            @abc.abstractmethod
            def _build_solver_data(self, A):
                raise NotImplementedError

            @abc.abstractmethod
            def _build_solver_flags(self, A, **options):
                raise NotImplementedError

            @abc.abstractmethod
            def _solver_cache_from_dict(self, cache, **options):
                raise NotImplementedError

            @abc.abstractproperty
            def _allocate_solver_cache(self):
                raise NotImplementedError

            def _register_solver(self, solver):
                try:
                    assert okerr.NO_ERR(lib.pogs_solver_exists(solver))
                    self.__backend.increment_cobject_count()
                    self.__c_solver = solver
                except:
                    raise RuntimeError('solver allocation failed')

            def _unregister_solver(self):
                if self.__c_solver is None:
                    return
                assert okerr.NO_ERR(lib.pogs_finish(self.c_solver, 0))
                self.__c_solver = None
                self.__backend.decrement_cobject_count()

            def _update_function_vectors(self, f, g):
                for i in xrange(f.size):
                    self.f.py[i] = lib.function(
                            f.h[i], f.a[i], f.b[i], f.c[i], f.d[i], f.e[i],
                            f.s[i])

                for j in xrange(g.size):
                    self.g.py[j] = lib.function(
                            g.h[j], g.a[j], g.b[j], g.c[j], g.d[j], g.e[j],
                            g.s[j])

            def solve(self, f, g, **options):
                if self.c_solver is None:
                    raise ValueError(
                            'No solver intialized, solve() call invalid')

                if not isinstance(f, Objective) and isinstance(g, Objective):
                    raise TypeError(
                        'inputs f, g must be of type {} \nprovided: {}, '
                        '{}'.format(Objective, type(f), type(g)))

                if not (f.size == self.m and g.size == self.n):
                    raise ValueError(
                        'inputs f, g not compatibly sized with solver'
                        '\nsolver dimensions ({}, {})\n provided: '
                        '({}{})'.format(self.m, self.n, f.size, g.size))


                # TODO : logic around resume, warmstart, rho input
                self._update_function_vectors(f, g)
                self.settings.update(**options)
                if self.settings.reltol < 1e-3:
                    if 'accelerate' not in options:
                        self.settings.accelerate = 1
                        self.settings.toladapt = 1e-2

                assert okerr.NO_ERR(lib.pogs_solve(
                        self.c_solver, self.f.c, self.g.c, self.settings.c,
                        self.info.c, self.output.c))
                self.first_run = False

            def _solver_state_from_dict(self, cache):
                state = SolverState(self.m, self.n)
                if 'state' in cache:
                    state.vec[:] = cache['state']
                if 'rho' in cache:
                    state.rho[0] = lib.pyfloat(cache['rho'])
                else:
                    state.rho[0] = 1.
                return state

            def _build_solver_from_cache(self, solver_cache, solver_state):
                if self.c_solver is not None:
                    self._unregister_solver()
                self._register_solver(lib.pogs_load_solver(
                        solver_cache.ptr,
                        solver_state.ptr,
                        solver_state.rho[0],
                        solver_cache.flags
                ))

            def _load_solver_from_cache(self, cache, allow_cholesky=True,
                                       cache_extra=None, **options):
                cache = DoubleCache(cache, cache_extra)
                solver_cache = self._solver_cache_from_dict(
                        cache, allow_cholesky=allow_cholesky)
                solver_state = self._solver_state_from_dict(cache)
                self._build_solver_from_cache(solver_cache, solver_state)
                self.__cache = solver_cache
                self.__state = solver_state

            def _build_cache_from_solver(self):
                if self.c_solver is None:
                    raise AttributeError(
                            'no solver exists, cannot build cache')

                state = self._state
                cache = self._allocate_solver_cache()
                assert okerr.NO_ERR(lib.pogs_export_solver(
                        cache.ptr,
                        state.ptr,
                        state.rho_ptr,
                        cache.flags,
                        self.c_solver
                ))
                return cache

            @property
            def _state(self):
                if self.c_solver is None:
                    raise AttributeError('no C solver built, state undefined')
                if self.__state is None:
                    self.__state = SolverState(*self.shape)
                state = self.__state
                assert okerr.NO_ERR(lib.pogs_solver_save_state(
                        state.ptr, state.rho_ptr, self.c_solver))
                return state

            @property
            def state(self):
                return self._state.dict

            @property
            def _cache(self):
                if self.__cache is None:
                    self.__cache = self._build_cache_from_solver()
                return self.__cache

            @property
            def cache(self):
                return self._cache.dict

            def load(self, filename, allow_cholesky=True, directory=None, **options):
                if directory is not None:
                    filename = os.path.join(directory, filename)
                if not '.npz' in filename:
                    filename += '.npz'

                try:
                    data = DoubleCache(np.load(filename))
                except:
                    data = DoubleCache()

                self._load_solver_from_cache(data, allow_cholesky=allow_cholesky)

            def save(self, directory, name, save_equil=True,
                     save_factorization=True):

                if self.c_solver is None:
                    raise ValueError(
                            'No solver intialized, save() call invalid')

                filename = os.path.join(directory, name)
                if not name.endswith('.npz'):
                    filename += '.npz'

                if not os.path.exists(directory):
                    raise ValueError('specified directory does not exist')

                if os.path.exists(filename):
                    raise ValueError('specified filepath already exists '
                                     'and would be overwritten, aborting.')

                cache = dict()
                cache.update(self.state)
                if save_equil:
                    cache.update(self.cache)
                    if not save_factorization:
                        cache.pop('ATA_cholesky', None)

                np.savez(filename, **cache)
                return filename

        self._SolverBase = _SolverBase
