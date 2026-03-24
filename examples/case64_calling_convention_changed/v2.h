#ifndef MATHLIB_H
#define MATHLIB_H

#ifdef __cplusplus
extern "C" {
#endif

/* Changed to regcall convention — parameters passed in different registers.
   On x86-64 Linux, __attribute__((regcall)) uses a different register
   assignment than the default System V ABI. Callers compiled against v1
   pass arguments in the wrong registers. */
__attribute__((regcall))
double vector_dot(const double *a, const double *b, int len);

__attribute__((regcall))
void   vector_scale(double *out, const double *in, double factor, int len);

#ifdef __cplusplus
}
#endif

#endif
