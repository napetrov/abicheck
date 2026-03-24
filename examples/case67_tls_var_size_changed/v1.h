#ifndef LOGGER_H
#define LOGGER_H

/* Thread-local error context — each thread gets its own copy */
typedef struct ErrorCtx {
    int   code;
    char  message[64];
} ErrorCtx;

extern __thread ErrorCtx tls_error;
extern __thread int      tls_log_level;

void logger_set_error(int code, const char *msg);
int  logger_get_error_code(void);
const char *logger_get_error_message(void);

#endif
