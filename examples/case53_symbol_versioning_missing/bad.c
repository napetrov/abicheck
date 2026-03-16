/* bad.c — library without symbol versioning.
   Works today, but removes a powerful compatibility mechanism
   for future ABI evolution. */
int api_init(void) { return 0; }
int api_process(int x) { return x * 2; }
int api_cleanup(void) { return 0; }
