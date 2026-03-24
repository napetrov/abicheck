/* DEMO: app compiled against v1 (ErrorCtx is 68 bytes).
   v2 expands ErrorCtx to 264 bytes. The TLS block layout changes —
   tls_log_level is at a different offset in v2's TLS segment.
   When the app accesses tls_log_level directly, it reads from the
   old offset, which now overlaps with tls_error.message[]. */
#include "v1.h"
#include <stdio.h>

int main(void) {
    /* Set a known log level */
    tls_log_level = 42;
    printf("log_level = %d (expected 42)\n", tls_log_level);

    /* Now set an error — in v2, the expanded message buffer may
       overwrite the old tls_log_level offset */
    logger_set_error(404, "resource not found");

    printf("error code = %d (expected 404)\n", logger_get_error_code());
    printf("error msg  = \"%s\"\n", logger_get_error_message());
    printf("log_level  = %d (expected 42)\n", tls_log_level);

    if (tls_log_level != 42) {
        printf("CORRUPTION: TLS variable layout shifted — "
               "tls_log_level overwritten by expanded tls_error!\n");
        return 1;
    }
    return 0;
}
