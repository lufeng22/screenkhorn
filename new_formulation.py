# -*- coding: utf-8 -*-
"""
    screenkhorn: solver for screening Sinkhorn via dual projection
"""
__author__ = 'Mokhtar Z. Alaya'

import numpy as np
from scipy.optimize import fmin_l_bfgs_b
from time import time
from numba import jit

class Screenkhorn:

    def __init__(self, a, b, C, reg, N, M, verbose = True, uniform = True):

        tic_initial = time()
        self.a = np.asarray(a, dtype=np.float64)
        self.b = np.asarray(b, dtype=np.float64)
        self.C = np.asarray(C, dtype=np.float64)
        self.reg = reg
        n = C.shape[0]
        m = C.shape[1]
        self.N = N
        self.M = M
        self.verbose = verbose
        self.uniform = uniform

        # K
        self.K = np.empty_like(self.C)
        np.divide(self.C, - self.reg, out=self.K)
        np.exp(self.K, out=self.K)

        #self.K = np.exp(-self.C / self.reg)
 
        
        print('K',time() - tic_initial)

        # Test
        if self.N == n and self.M == m:

            # I, J
            self.I = list(range(n))
            self.J = list(range(m))

            # epsilon
            self.epsilon = 0.0
            # scale factor
            self.fact_scale = 1.0

            # restricted Sinkhron
            self.cst_u = 0.
            self.cst_v = 0.

            # box BFGS
            self.bounds_u = [(0.0, np.inf)] * n
            self.bounds_v = [(0.0, np.inf)] * m

        else:
            
            print(time() - tic_initial)
            # sum of rows and columns of K
            K_sum_cols = self.K.sum(axis=1)
            K_sum_rows = self.K.T.sum(axis=1)

            # K_min
            K_min = self.K.min()

            # 
            if not self.uniform:
                a_sort = np.sort(a)
                b_sort = np.sort(b)
            else:
                a_sort,b_sort = a,b
            aK_sort = np.sort(a / K_sum_cols)[::-1]
            bK_sort = np.sort(b / K_sum_rows)[::-1]

            epsilon_u_square = aK_sort[self.N - 1: self.N].mean()
            epsilon_v_square = bK_sort[self.M - 1: self.M].mean()

            self.epsilon = (epsilon_u_square * epsilon_v_square)**(1/4)
            self.fact_scale = (epsilon_v_square / epsilon_u_square)**(1/2)
            
            if self.verbose:
                print("Epsilon = %s\n" % self.epsilon)
                print("Scaling factor = %s\n" % self.fact_scale)
            
            print(time() - tic_initial)

            # I, J

            self.I = np.where(self.a >= self.epsilon**2 / self.fact_scale * K_sum_cols)[0].tolist()
            self.J = np.where(self.b >= self.epsilon**2 * self.fact_scale * K_sum_rows)[0].tolist()
            
            if self.verbose:
                print('|I_active| = %s \t |J_active| = %s \t |I_active| + |J_active| = %s'\
                      %(len(self.I), len(self.J), len(self.I) + len(self.J)))


            # LBFGS box
            self.bounds_u = [(max(self.fact_scale * a_sort[self.I][-1] / (self.epsilon * (m - len(self.J)) \
                                                    + len(self.J) * (
                                                                b_sort[self.J][0] / (self.epsilon * n * K_min))), self.epsilon / self.fact_scale), \
                              a_sort[self.I][0] / (self.epsilon * m * K_min))] * len(self.I)

            self.bounds_v = [(max(b_sort[self.J][-1] / (self.epsilon * (n - len(self.I)) \
                                                    + len(self.I) * (
                                                                a_sort[self.I][0] / (self.epsilon * m * K_min))), self.epsilon * self.fact_scale), \
                              b_sort[self.J][0] / (self.epsilon * n * K_min))] * len(self.J)
            
            print(time() - tic_initial)

        # Ic, Jc
        self.Ic = list(set(list(range(n))) - set(self.I))
        self.Jc = list(set(list(range(m))) - set(self.J))

        self.a_I = self.a[self.I]
        self.b_J = self.b[self.J]

        self.a_Ic = self.a[self.Ic]
        self.b_Jc = self.b[self.Jc]

        self.K_IJ = self.K[np.ix_(self.I, self.J)]
        self.K_IcJ = self.K[np.ix_(self.Ic, self.J)]
        self.K_IJc = self.K[np.ix_(self.I, self.Jc)]

        self.vec_eps_IJc = self.epsilon * self.fact_scale * (self.K_IJc * np.ones(len(self.Jc)).reshape((1, -1))).sum(axis=1)
        self.vec_eps_IcJ = (self.epsilon / self.fact_scale) * (np.ones(len(self.Ic)).reshape((-1, 1)) * self.K_IcJ).sum(axis=0)

        # restricted Sinkhron
        if self.N != n or self.M != m:
            self.cst_u = self.fact_scale * self.epsilon * self.K_IJc.sum(axis=1)
            self.cst_v = self.epsilon * self.K_IcJ.sum(axis=0) / self.fact_scale

        print(time() - tic_initial)

        self.toc_initial = time() - tic_initial


    def _projection(self, u, epsilon):

        u[np.where(u <= epsilon)] = epsilon
        return u

    def objective(self, u_param, v_param):

        part_IJ = u_param @ self.K_IJ @ v_param\
                  - self.fact_scale * self.a_I @ np.log(u_param) - (1. / self.fact_scale) * self.b_J @ np.log(v_param)
        part_IJc = u_param @ self.vec_eps_IJc
        part_IcJ = self.vec_eps_IcJ @ v_param
        psi_epsilon = part_IJ + part_IJc + part_IcJ
        return psi_epsilon

    def grad_objective(self, u_param, v_param):

        # gradients of Psi_epsilon w. r. t. u and v
        grad_u = self.K_IJ @ v_param + self.vec_eps_IJc - self.fact_scale * self.a_I / u_param
        grad_v = self.K_IJ.T @ u_param + self.vec_eps_IcJ - (1. / self.fact_scale) * self.b_J / v_param
        return grad_u, grad_v

    def restricted_sinkhorn(self, usc, vsc, max_iter=10):
        cpt = 1

        while (cpt < max_iter):

            K_IJ_v = self.K_IJ.T @ usc + self.cst_v
            vsc = self.b_J / (self.fact_scale * K_IJ_v)

            KIJ_u = self.K_IJ @ vsc + self.cst_u
            usc = (self.fact_scale * self.a_I) / KIJ_u
            # usc = np.divide(self.fact_scale * self.a_I, KIJ_u)

            cpt += 1

        usc = self._projection(usc, self.epsilon / self.fact_scale)
        vsc = self._projection(vsc, self.epsilon * self.fact_scale)

        return usc, vsc

    def _bfgspost(self, theta):
        u = theta[:len(self.I)]
        v = theta[len(self.I):]
        # objective value
        f = self.objective(u, v)
        # gradient
        g_u, g_v = self.grad_objective(u, v)
        g = np.hstack([g_u, g_v])
        return f, g

    def lbfgsb(self):

        (n, m) = self.C.shape

        u0 = np.full(len(self.I), (1. / len(self.I)) + self.epsilon / self.fact_scale)
        v0 = np.full(len(self.J), (1. / len(self.J)) + self.epsilon * self.fact_scale)

        u, v = self.restricted_sinkhorn(u0, v0, max_iter=10)

        # params of bfgs
        theta0 = np.hstack([u, v])
        maxiter = 1000 # max number of iterations
        maxfun = 1000 # max  number of function evaluations
        pgtol = 1e-09 # final objective function accuracy

        obj = lambda theta: self._bfgspost(theta)
        bounds = self.bounds_u + self.bounds_v

        theta, _, d = fmin_l_bfgs_b(func=obj,
                                      x0=theta0,
                                      bounds=bounds,
                                      maxfun=maxfun,
                                      pgtol=pgtol,
                                      maxiter=maxiter)

        usc = theta[:len(self.I)]
        vsc = theta[len(self.I):]

        usc_full = np.full(n, self.epsilon / self.fact_scale)
        vsc_full = np.full(m, self.epsilon * self.fact_scale)
        usc_full[self.I] = usc
        vsc_full[self.J] = vsc
        Psc = usc_full.reshape((-1, 1)) * self.K * vsc_full.reshape((1, -1))

        return usc_full, vsc_full, Psc, d
