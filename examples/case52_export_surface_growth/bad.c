/* bad.c — v2 of a library that adds new exported functions without
   updating the public header. These "shadow exports" become accidental ABI. */
int public_api(int x) { return x; }

/* These are new internal functions that the developer forgot to hide.
   They get exported by default because -fvisibility=hidden was not used. */
int _process_buffer_internal(const char *buf, int len) {
    (void)buf;
    return len;
}

int _validate_input_impl(int x) {
    return x > 0;
}

int _cache_lookup_detail(int key) {
    return key % 16;
}
