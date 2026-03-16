/* good.c — same library with symbol versioning via .symver directives.
   This establishes a versioning baseline that enables future ABI evolution
   without SONAME bumps. */

int api_init(void) { return 0; }
int api_process(int x) { return x * 2; }
int api_cleanup(void) { return 0; }

/* Symbol versioning directives — assign all symbols to MYLIB_1.0 */
__asm__(".symver api_init,api_init@@MYLIB_1.0");
__asm__(".symver api_process,api_process@@MYLIB_1.0");
__asm__(".symver api_cleanup,api_cleanup@@MYLIB_1.0");
