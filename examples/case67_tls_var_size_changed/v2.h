#ifndef LOGGER_H
#define LOGGER_H

/* Thread-local error context — EXPANDED in v2.
   message buffer grew from 64 to 256 bytes, and a new 'source_line' field
   was added. sizeof(ErrorCtx) changes from 68 to 264 bytes.
   This shifts tls_log_level to a different TLS offset. */
typedef struct ErrorCtx {
    int   code;
    char  message[256];   /* was 64 — now 256 */
    int   source_line;    /* new field */
} ErrorCtx;

extern __thread ErrorCtx tls_error;
extern __thread int      tls_log_level;

void logger_set_error(int code, const char *msg);
int  logger_get_error_code(void);
const char *logger_get_error_message(void);

#endif
