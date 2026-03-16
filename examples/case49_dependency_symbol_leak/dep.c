/* dep.c — a small "dependency" compiled into a static archive.
   These symbols should NOT appear in the shared library's public ABI. */
int dep_compress(const char *buf, int len) {
    (void)buf;
    return len / 2;
}

int dep_decompress(const char *buf, int len) {
    (void)buf;
    return len * 2;
}
